import { useState, useEffect, useCallback } from 'react';
import { checkHealth } from '../api/system';
import {
  listThreads,
  deleteThread as deleteThreadApi,
  deleteAllThreads as deleteAllThreadsApi,
  type ThreadItem,
} from '../api/threads';

const LOCAL_STORAGE_KEY = 'main_agent_current_thread';

export function useThreads() {
  const [threads, setThreads] = useState<ThreadItem[]>([]);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(() => {
    return localStorage.getItem(LOCAL_STORAGE_KEY) || null;
  });
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
      const data = await listThreads();
      setThreads(data);

      const savedThread = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (savedThread && data.some((t) => t.thread_id === savedThread)) {
        setCurrentThreadId((prev) => prev || savedThread);
      } else if (data.length > 0) {
        setCurrentThreadId((prev) => prev || data[0].thread_id);
      }
    } catch (err: any) {
      console.error('Failed to load threads:', err);
      setError('Unable to reach Main Agent API. Make sure the backend service is running.');
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

  const selectThread = useCallback((id: string) => {
    setCurrentThreadId(id);
    localStorage.setItem(LOCAL_STORAGE_KEY, id);
    setError(null);
  }, []);

  const createNewThread = useCallback(() => {
    const newId = `thread_${Date.now()}`;
    setCurrentThreadId(newId);
    localStorage.setItem(LOCAL_STORAGE_KEY, newId);
    setError(null);
    return newId;
  }, []);

  const deleteThread = useCallback(async (threadId: string) => {
    try {
      await deleteThreadApi(threadId);
      setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
      if (currentThreadId === threadId) {
        const remaining = threads.filter((t) => t.thread_id !== threadId);
        if (remaining.length > 0) {
          selectThread(remaining[0].thread_id);
        } else {
          setCurrentThreadId(null);
          localStorage.removeItem(LOCAL_STORAGE_KEY);
        }
      }
    } catch (err: any) {
      console.error(`Failed to delete thread ${threadId}:`, err);
      setError(`Failed to delete thread ${threadId}`);
    }
  }, [currentThreadId, threads, selectThread]);

  const deleteAllThreads = useCallback(async () => {
    try {
      await deleteAllThreadsApi();
      setThreads([]);
      setCurrentThreadId(null);
      localStorage.removeItem(LOCAL_STORAGE_KEY);
    } catch (err: any) {
      console.error('Failed to clear threads:', err);
      setError('Failed to clear all threads');
    }
  }, []);

  return {
    threads,
    currentThreadId,
    isLoadingThreads,
    isBackendHealthy,
    error,
    setError,
    loadThreads,
    selectThread,
    createNewThread,
    deleteThread,
    deleteAllThreads,
  };
}
