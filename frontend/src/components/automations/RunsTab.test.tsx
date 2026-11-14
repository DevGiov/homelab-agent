import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AutomationRunSummary } from '../../api/automationRuns';
import type { RunActions } from '../../hooks/useRunActions';
import { RunsTab } from './RunsTab';

const run = (run_id: string, extra: Partial<AutomationRunSummary> = {}): AutomationRunSummary => ({
  run_id,
  automation_id: 'backup-di-prova',
  version_applied: 1,
  trigger_type: 'manual',
  status: 'completed',
  is_dry_run: false,
  started_at: '2026-11-14T10:00:00Z',
  total_tokens: 0,
  total_duration_ms: 0,
  ...extra,
});

const actions = () =>
  ({
    pause: vi.fn(),
    resume: vi.fn(),
    remove: vi.fn(),
    toggleFavorite: vi.fn(),
    togglePreserve: vi.fn(),
    removeMany: vi.fn(),
  }) as unknown as RunActions & { remove: ReturnType<typeof vi.fn> };

describe('RunsTab', () => {
  afterEach(cleanup);

  it('caselle e colonne a icona hanno un nome per i lettori di schermo', () => {
    render(<RunsTab runs={[run('run-1'), run('run-2')]} runActions={actions()} onInspect={vi.fn()} onOpenArtifacts={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: 'Seleziona tutte le esecuzioni visibili' })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: "Seleziona l'esecuzione run-2" })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Preferita' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Preservata' })).toBeTruthy();
    const unnamed = screen.getAllByRole('columnheader').filter((th) => !th.textContent?.trim() && !th.querySelector('input'));
    expect(unnamed).toEqual([]);
  });

  it("l'eliminazione di un'esecuzione preservata è disattivata, col motivo, e un clic non fa nulla", () => {
    const runActions = actions();
    render(
      <RunsTab runs={[run('run-1'), run('run-3', { is_preserved: true })]} runActions={runActions} onInspect={vi.fn()} onOpenArtifacts={vi.fn()} />,
    );
    const preserved = screen.getByRole('button', { name: "Elimina l'esecuzione run-3" });
    expect(preserved.getAttribute('aria-disabled')).toBe('true');
    expect(preserved.getAttribute('title')).toMatch(/preservata/);
    fireEvent.click(preserved);
    expect(runActions.remove).not.toHaveBeenCalled();

    const normal = screen.getByRole('button', { name: "Elimina l'esecuzione run-1" });
    expect(normal.hasAttribute('aria-disabled')).toBe(false);
    fireEvent.click(normal);
    expect(runActions.remove).toHaveBeenCalledWith('run-1');
  });
});
