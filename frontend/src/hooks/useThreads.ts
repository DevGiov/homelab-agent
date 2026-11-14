import { useState, useEffect, useCallback } from 'react';
import { checkHealth } from '../api/system';
import {
  listThreads,
  deleteThread as deleteThreadApi,
  deleteAllThreads as deleteAllThreadsApi,
  type ThreadItem,
} from '../api/threads';

/** Elenco delle conversazioni e salute del backend. Quale conversazione è aperta lo dice la URL (useRoute). */
export function useThreads() {
  const [threads, setThreads] = useState<ThreadItem[]>([]);
  // Vero dopo il primo elenco arrivato: prima non si sa quali conversazioni esistono
  const [hasLoadedThreads, setHasLoadedThreads] = useState(false);
  // Conversazioni nate in questa pagina, che l'elenco caricato prima non contiene ancora
  const [createdThreadIds, setCreatedThreadIds] = useState<string[]>([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState<boolean>(false);
  const [isBackendHealthy, setIsBackendHealthy] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Check Backend Health
  const verifyHealth = useCallback(async () => {
    try {
      const res = await checkHealth();
      setIsBackendHealthy(res.status === 'ok');
    } catch {
      setIsBackendHealthy(false);
    }
  }, []);

  // Fetch threads list
  const loadThreads = useCallback(async () => {
    setIsLoadingThreads(true);
    try {
      setThreads(await listThreads());
      setHasLoadedThreads(true);
    } catch (err: any) {
      console.error('Failed to load threads:', err);
      setError("Impossibile raggiungere l'API di Main Agent: controlla che il backend sia in esecuzione.");
    } finally {
      setIsLoadingThreads(false);
    }
  }, []);

  useEffect(() => {
    verifyHealth();
    loadThreads();
    const interval = setInterval(verifyHealth, 15000);
    return () => clearInterval(interval);
  }, [verifyHealth, loadThreads]);

  /** Una conversazione appena creata da questa pagina esiste anche se l'elenco non la mostra ancora. */
  const registerThread = useCallback((threadId: string) => {
    setCreatedThreadIds((prev) => (prev.includes(threadId) ? prev : [...prev, threadId]));
    setError(null);
  }, []);

  /** Vero quando l'elenco è arrivato e la conversazione non c'è: eliminata, o un link a una che non è mai esistita. */
  const isMissingThread = (threadId: string) =>
    hasLoadedThreads && !createdThreadIds.includes(threadId) && !threads.some((t) => t.thread_id === threadId);

  const deleteThread = useCallback(async (threadId: string) => {
    try {
      await deleteThreadApi(threadId);
      setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
      setCreatedThreadIds((prev) => prev.filter((id) => id !== threadId));
    } catch (err: any) {
      console.error(`Failed to delete thread ${threadId}:`, err);
      setError(`Eliminazione della conversazione ${threadId} non riuscita`);
    }
  }, []);

  const deleteAllThreads = useCallback(async () => {
    try {
      await deleteAllThreadsApi();
      setThreads([]);
      setCreatedThreadIds([]);
    } catch (err: any) {
      console.error('Failed to clear threads:', err);
      setError('Eliminazione delle conversazioni non riuscita');
    }
  }, []);

  return {
    threads,
    isLoadingThreads,
    isBackendHealthy,
    error,
    setError,
    loadThreads,
    registerThread,
    isMissingThread,
    deleteThread,
    deleteAllThreads,
  };
}
