import { useCallback, useEffect, useState } from 'react';
import {
  fetchAutomationApprovals,
  fetchAutomationRuns,
  type AutomationApprovalItem,
  type AutomationRunSummary,
} from '../api/automationRuns';
import {
  fetchAutomations,
  fetchAutomationTemplates,
  fetchScheduledJobs,
  type AutomationSummary,
  type ScheduledJobInfo,
} from '../api/automations';
import type { Notify } from './useFeedback';

const POLL_INTERVAL_MS = 10_000;

/** Automazioni, run, approvazioni, template e job dello scheduler, ricaricati ogni 10 secondi. */
export function useAutomationsData(notify: Notify) {
  const [automations, setAutomations] = useState<AutomationSummary[]>([]);
  const [runs, setRuns] = useState<AutomationRunSummary[]>([]);
  const [approvals, setApprovals] = useState<AutomationApprovalItem[]>([]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [scheduledJobs, setScheduledJobs] = useState<ScheduledJobInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      const [autos, runList, pending, tpls, scheduler] = await Promise.all([
        fetchAutomations(),
        fetchAutomationRuns(),
        fetchAutomationApprovals(),
        fetchAutomationTemplates(),
        fetchScheduledJobs(),
      ]);
      setAutomations(autos);
      setRuns(runList);
      setApprovals(pending);
      setTemplates(tpls);
      setScheduledJobs(scheduler.jobs || []);
    } catch (err) {
      console.error('Errore caricamento dati automazioni:', err);
      notify('error', 'Impossibile caricare i dati delle automazioni.');
    } finally {
      setIsLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    reload();
    const interval = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [reload]);

  return { automations, setAutomations, runs, setRuns, approvals, templates, scheduledJobs, isLoading, reload };
}
