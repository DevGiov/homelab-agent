import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutomationRunSummary } from '../../api/automationRuns';
import { jsonResponse, mockBackend } from '../../test/backend';
import { AutomationsView } from './AutomationsView';

const run = (run_id: string): AutomationRunSummary => ({
  run_id,
  automation_id: 'backup-di-prova',
  version_applied: 1,
  trigger_type: 'manual',
  status: 'completed',
  is_dry_run: false,
  started_at: '2026-11-14T10:00:00Z',
  total_tokens: 0,
  total_duration_ms: 0,
});

const setup = () =>
  mockBackend({
    'GET /v1/automations': () => jsonResponse([]),
    'GET /v1/automations/runs': () => jsonResponse([run('run-1'), run('run-2')]),
    'GET /v1/automations/approvals': () => jsonResponse([]),
    'GET /v1/automations/templates': () => jsonResponse([]),
    'GET /v1/automations/scheduler/jobs': () => jsonResponse({ running: true, jobs: [] }),
    'DELETE /v1/automations/runs/run-1': () => jsonResponse({ deleted: true, run_id: 'run-1' }),
    'POST /v1/automations/runs/delete-batch': () => jsonResponse({ deleted_count: 2 }),
  });

const nativeConfirm = vi.fn(() => true);

beforeEach(() => {
  // La conferma è un dialogo dell'app: il confirm() nativo, che direbbe sì, non deve servire
  nativeConfirm.mockClear();
  vi.stubGlobal('confirm', nativeConfirm);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const openRunsTab = async () => {
  fireEvent.click(screen.getByRole('button', { name: /Storico Run/ }));
  return screen.findByRole('button', { name: "Elimina l'esecuzione run-1" });
};

/** Lascia risolvere le promesse in sospeso: un'eliminazione partita per errore farebbe qui la sua richiesta. */
const settle = () => act(async () => {});

describe('AutomationsView, eliminazione delle esecuzioni', () => {
  it("elimina una run solo dopo la conferma nel dialogo; Escape e Annulla non eliminano", async () => {
    const { requests } = setup();
    render(<AutomationsView />);
    const deleteButton = await openRunsTab();
    const deletes = () => requests.filter((r) => r.method === 'DELETE');

    fireEvent.click(deleteButton);
    const dialog = screen.getByRole('alertdialog');
    expect(within(dialog).getByText('Sei sicuro di voler eliminare la run run-1?')).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Annulla' }));
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    await settle();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(deletes()).toEqual([]);

    fireEvent.click(deleteButton);
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Annulla' }));
    await settle();
    expect(deletes()).toEqual([]);

    fireEvent.click(deleteButton);
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Elimina' }));
    await waitFor(() => expect(deletes().map((r) => r.path)).toEqual(['/v1/automations/runs/run-1']));
    expect(await screen.findByText('Run run-1 eliminata.')).toBeTruthy();
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  it('elimina le run selezionate solo dopo la conferma; Annulla lascia la selezione', async () => {
    const { requests } = setup();
    render(<AutomationsView />);
    await openRunsTab();
    const batches = () => requests.filter((r) => r.path === '/v1/automations/runs/delete-batch');

    fireEvent.click(screen.getByRole('checkbox', { name: "Seleziona l'esecuzione run-1" }));
    fireEvent.click(screen.getByRole('checkbox', { name: "Seleziona l'esecuzione run-2" }));
    fireEvent.click(screen.getByRole('button', { name: /Elimina Selezionate \(2\)/ }));
    const dialog = screen.getByRole('alertdialog');
    expect(within(dialog).getByText(/eliminare 2 esecuzioni selezionate\? Le run protette da lucchetto non verranno eliminate\./)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Annulla' }));
    await settle();
    expect(batches()).toEqual([]);
    const bulk = screen.getByRole('button', { name: /Elimina Selezionate \(2\)/ });
    expect(bulk.hasAttribute('disabled')).toBe(false);

    fireEvent.click(bulk);
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Elimina' }));
    await waitFor(() => expect(batches().map((r) => r.body.run_ids)).toEqual([['run-1', 'run-2']]));
    expect(nativeConfirm).not.toHaveBeenCalled();
  });
});
