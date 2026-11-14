import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ExecutionTraceViewer } from './ExecutionTraceViewer';
import { PlanViewer } from './PlanViewer';

// Parole inglesi che la UI mostrava prima della traduzione (testi, title, aria-label, placeholder)
const ENGLISH = /\b(Reasoning|Process|Collapsed|Expanded|Show|Hide|Trace|FAILED|Parameters|Error detail|Rollback Actions|Undo|Executed|Success|Failed|Rolled Back|Running|Pending|Execution Plan|nodes|Depends on|executions?)\b/;

function visibleText(container: HTMLElement) {
  const attributes = [...container.querySelectorAll('[title], [aria-label], [placeholder]')].flatMap((el) =>
    ['title', 'aria-label', 'placeholder'].map((name) => el.getAttribute(name) ?? ''),
  );
  return [container.textContent ?? '', ...attributes].join(' ');
}

describe('testi in italiano', () => {
  afterEach(cleanup);

  it('traccia di esecuzione, con uno step aperto e un rollback', () => {
    const { container } = render(
      <ExecutionTraceViewer
        reasoning="Controllo lo stato del container"
        trace={[
          { step_id: 1, tool_name: 'proxmox-mcp__get_container_status', args: { vmid: 101 }, output: 'running', sandboxed: false },
          { step_id: 2, tool_name: 'proxmox-mcp__start_container', args: { vmid: 101 }, error: 'timeout' },
        ]}
        rollbackTrace={[{ tool_name: 'proxmox-mcp__stop_container', args: { vmid: 101 } }]}
        initialCollapsed={false}
      />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: 'Mostra i dettagli dello step' })[1]);
    expect(screen.getByText("Dettaglio dell'errore:")).toBeTruthy();
    expect(visibleText(container)).not.toMatch(ENGLISH);
  });

  it('piano con tutti gli stati dei nodi', () => {
    const { container } = render(
      <PlanViewer
        planStructure={{
          goal: 'Aggiornare il CT 101',
          nodes: (['success', 'failed', 'rolled_back', 'running', 'pending'] as const).map((status, i) => ({
            id: `n${i}`,
            tool_name: `tool_${i}`,
            status,
            depends_on: i ? [`n${i - 1}`] : [],
          })),
        }}
      />,
    );
    expect(screen.getByText('Annullato (rollback)')).toBeTruthy();
    expect(visibleText(container)).not.toMatch(ENGLISH);
  });
});
