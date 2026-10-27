import type { Dispatch, SetStateAction } from 'react';
import {
  bulkDeleteAutomationRuns,
  deleteAutomationRun,
  pauseAutomationRun,
  resumeAutomationRun,
  toggleAutomationRunFavorite,
  toggleAutomationRunPreserve,
  type AutomationRunSummary,
} from '../api/automationRuns';
import { formatApiError } from '../utils/error';
import type { Notify } from './useFeedback';

/** Azioni sulle run delle automazioni, condivise tra le card e lo storico. */
export function useRunActions(
  notify: Notify,
  reload: () => void,
  setRuns: Dispatch<SetStateAction<AutomationRunSummary[]>>
) {
  const patchRun = (runId: string, patch: Partial<AutomationRunSummary>) =>
    setRuns((prev) => prev.map((r) => (r.run_id === runId ? { ...r, ...patch } : r)));

  const attempt = async (action: () => Promise<unknown>, success: string, failure: string, refresh = true) => {
    try {
      await action();
      notify('success', success);
      if (refresh) reload();
      return true;
    } catch (err) {
      notify('error', `${failure}: ${formatApiError(err)}`);
      return false;
    }
  };

  return {
    pause: (runId: string) =>
      attempt(() => pauseAutomationRun(runId), `Richiesta di pausa inviata per la run ${runId}.`, 'Errore pausa run'),

    resume: (runId: string) =>
      attempt(() => resumeAutomationRun(runId), `Run ${runId} ripresa con successo.`, 'Errore ripresa run'),

    remove: async (runId: string, isPreserved?: boolean) => {
      if (isPreserved) {
        alert('Questa esecuzione è preservata (bloccata con lucchetto). Sbloccala prima di eliminarla.');
        return;
      }
      if (!confirm(`Sei sicuro di voler eliminare la run ${runId}?`)) return;
      const ok = await attempt(() => deleteAutomationRun(runId), `Run ${runId} eliminata.`, 'Errore eliminazione run', false);
      if (ok) setRuns((prev) => prev.filter((r) => r.run_id !== runId));
    },

    toggleFavorite: async (run: AutomationRunSummary) => {
      const next = !run.is_favorite;
      const ok = await attempt(
        () => toggleAutomationRunFavorite(run.run_id, next),
        next ? 'Aggiunto ai preferiti.' : 'Rimosso dai preferiti.',
        'Errore toggle preferito',
        false
      );
      if (ok) patchRun(run.run_id, { is_favorite: next });
    },

    togglePreserve: async (run: AutomationRunSummary) => {
      const next = !run.is_preserved;
      const ok = await attempt(
        () => toggleAutomationRunPreserve(run.run_id, next),
        next ? 'Esecuzione preservata da auto-cleanup!' : 'Protezione rimossa.',
        'Errore toggle preserva',
        false
      );
      if (ok) patchRun(run.run_id, { is_preserved: next });
    },

    /** Elimina le run selezionate; restituisce true se l'eliminazione è andata a buon fine. */
    removeMany: async (runIds: string[]) => {
      const count = runIds.length;
      const label = count === 1 ? 'esecuzione selezionata' : 'esecuzioni selezionate';
      if (!confirm(`Sei sicuro di voler eliminare ${count} ${label}? Le run protette da lucchetto non verranno eliminate.`)) {
        return false;
      }
      try {
        const res = await bulkDeleteAutomationRuns({ run_ids: runIds });
        notify('success', `Eliminate ${res.deleted_count} esecuzioni con successo.`);
        reload();
        return true;
      } catch (err) {
        notify('error', `Errore durante l'eliminazione: ${formatApiError(err)}`);
        return false;
      }
    },
  };
}

export type RunActions = ReturnType<typeof useRunActions>;
