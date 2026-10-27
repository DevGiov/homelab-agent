import { useCallback, useEffect, useState } from 'react';
import {
  deleteIntegration,
  fetchIntegrations,
  saveIntegration,
  testIntegration,
  type IntegrationTestResult,
  type ServiceIntegration,
} from '../api/integrations';
import { formatApiError } from '../utils/error';
import type { Notify } from './useFeedback';

/** Integrazioni configurate con salvataggio, test di connessione ed eliminazione. */
export function useIntegrations(notify: Notify) {
  const [integrations, setIntegrations] = useState<ServiceIntegration[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, IntegrationTestResult>>({});

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      setIntegrations(await fetchIntegrations());
    } catch (err) {
      console.error('Errore caricamento integrazioni:', err);
      notify('error', 'Impossibile caricare le integrazioni configurate.');
    } finally {
      setIsLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    reload();
  }, [reload]);

  const save = async (payload: Partial<ServiceIntegration>, success: string, failure: string) => {
    try {
      await saveIntegration(payload);
      notify('success', success);
      await reload();
    } catch (err) {
      notify('error', `${failure}: ${formatApiError(err)}`);
    }
  };

  const test = async (id: string) => {
    setTestingId(id);
    try {
      const res = await testIntegration(id);
      setTestResults((prev) => ({ ...prev, [id]: res }));
      if (res.success) notify('success', res.message || 'Test di connessione superato con successo!');
      else notify('error', res.error || 'Test di connessione fallito.');
      await reload();
    } catch (err) {
      notify('error', `Errore durante il test: ${formatApiError(err)}`);
    } finally {
      setTestingId(null);
    }
  };

  const remove = async (id: string) => {
    if (!confirm(`Sei sicuro di voler rimuovere l'integrazione "${id}"?`)) return;
    try {
      await deleteIntegration(id);
      notify('success', `Integrazione "${id}" rimossa.`);
      await reload();
    } catch (err) {
      notify('error', `Errore eliminazione: ${formatApiError(err)}`);
    }
  };

  return { integrations, isLoading, reload, save, test, remove, testingId, testResults };
}

export type Integrations = ReturnType<typeof useIntegrations>;
