import { useCallback, useEffect, useState } from 'react';
import {
  approveProcedure,
  createProcedure,
  deleteProcedure,
  listProcedures,
  listProcedureTools,
  rejectProcedure,
  updateProcedure,
  type Procedure,
  type ProcedureInput,
} from '../api/memory';
import { formatApiError } from '../utils/error';
import type { Notify } from './useFeedback';

/** Procedure (note sui tool e piani modello) con approvazione, modifica ed eliminazione. `onChange` riallinea i contatori. */
export function useProcedures(notify: Notify, onChange: () => void) {
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [tools, setTools] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      setProcedures(await listProcedures());
    } catch (err) {
      notify('error', `Procedure non caricate: ${formatApiError(err)}`);
    } finally {
      setIsLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    load();
    listProcedureTools()
      .then(setTools)
      .catch(() => setTools([]));
  }, [load]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      notify('success', success);
      await load();
      onChange();
      return true;
    } catch (err) {
      notify('error', formatApiError(err));
      return false;
    }
  };

  return {
    procedures,
    tools,
    isLoading,
    reload: load,
    create: (input: ProcedureInput) => run(() => createProcedure(input), 'Procedura aggiunta: è già in uso.'),
    save: (id: number, input: Omit<ProcedureInput, 'kind'>) => run(() => updateProcedure(id, input), 'Procedura aggiornata.'),
    approve: (id: number) => run(() => approveProcedure(id), "Procedura approvata: l'agente la userà da ora."),
    reject: (id: number) => run(() => rejectProcedure(id), "Procedura rifiutata: l'agente non la userà."),
    remove: (id: number) => run(() => deleteProcedure(id), 'Procedura eliminata.'),
  };
}

export type ProceduresState = ReturnType<typeof useProcedures>;
