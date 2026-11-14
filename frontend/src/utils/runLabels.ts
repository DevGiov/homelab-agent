/** Etichette italiane degli stati e dei trigger delle run; i valori restano quelli del backend (RunStatus, TriggerType). */
const RUN_STATUS_LABELS: Record<string, string> = {
  pending: 'In coda',
  running: 'In corso',
  waiting_approval: 'In attesa di approvazione',
  paused: 'In pausa',
  completed: 'Completata',
  failed: 'Fallita',
  blocked: 'Bloccata',
  cancelled: 'Annullata',
  exhausted: 'Budget esaurito',
};

const TRIGGER_LABELS: Record<string, string> = {
  cron: 'Cron',
  webhook: 'Webhook',
  manual: 'Manuale',
  event: 'Evento',
};

/** Uno stato o un trigger nuovo del backend compare così com'è. */
export const runStatusLabel = (status: string) => RUN_STATUS_LABELS[status.toLowerCase()] ?? status;
export const triggerLabel = (trigger: string) => TRIGGER_LABELS[trigger.toLowerCase()] ?? trigger;
