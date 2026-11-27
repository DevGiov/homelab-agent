import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AutomationRunDetails } from '../../api/automationRuns';
import { RunInspectorModal } from './RunInspectorModal';

afterEach(cleanup);

const run = {
  run_id: 'run-0123456789abcdef0123456789abcdef',
  automation_id: 'daily-report',
  status: 'completed',
  trigger_type: 'manual',
  is_dry_run: false,
  total_duration_ms: 1200,
  total_tokens: 4200,
  step_runs: [],
  artifacts: [],
} as unknown as AutomationRunDetails;

const classes = (el: Element) => el.className.split(/\s+/);

describe('RunInspectorModal su telefono', () => {
  it('le statistiche stanno su due colonne sotto sm e su quattro da sm', () => {
    render(<RunInspectorModal run={run} isOpen onClose={() => {}} />);
    const grid = screen.getByText('Durata').closest('.grid') as HTMLElement;
    expect(classes(grid)).toEqual(expect.arrayContaining(['grid-cols-2', 'sm:grid-cols-4']));
    expect(classes(grid)).not.toContain('grid-cols-4');
  });

  it("l'identificativo lungo della run può andare a capo invece di uscire dalla finestra", () => {
    render(<RunInspectorModal run={run} isOpen onClose={() => {}} />);
    const title = screen.getByRole('dialog').querySelector('h2') as HTMLElement;
    expect(classes(title)).toContain('break-all');
    expect(classes(title.parentElement as HTMLElement)).toContain('flex-wrap');
    expect(classes(title.parentElement!.parentElement as HTMLElement)).toContain('min-w-0');
  });
});
