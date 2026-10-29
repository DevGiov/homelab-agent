import { useCallback, useEffect, useState } from 'react';
import { getConsolidation, startConsolidation, type ConsolidationStatus } from '../api/memory';
import { formatApiError } from '../utils/error';
import type { Notify } from './useFeedback';

const POLL_MS = 3000;

/** Stato del consolidamento della memoria; mentre è in corso lo riaggiorna e alla fine chiama `onDone`. */
export function useConsolidation(notify: Notify, onDone: () => void) {
  const [status, setStatus] = useState<ConsolidationStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await getConsolidation();
      setStatus((prev) => {
        if (prev?.running && !next.running) onDone();
        return next;
      });
    } catch {
      setStatus(null);
    }
  }, [onDone]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!status?.running) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [status?.running, load]);

  const start = async () => {
    try {
      await startConsolidation();
      notify('success', 'Consolidamento avviato: usa il modello attivo e può richiedere qualche minuto.');
      await load();
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  return { status, start, reload: load };
}
