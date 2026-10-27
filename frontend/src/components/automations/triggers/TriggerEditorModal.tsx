import React, { useState } from 'react';
import { AlertCircle, RefreshCw, Sliders, X, Zap } from 'lucide-react';
import { updateAutomationTriggers, type AutomationSummary } from '../../../api/automations';
import { buildTriggers, parseCron, toCron, type Schedule, type Trigger } from '../../../utils/cronSchedule';
import { formatApiError } from '../../../utils/error';
import { CronScheduleSection } from './CronScheduleSection';
import { WebhookSection } from './WebhookSection';

const DEFAULT_TIMEZONE = 'Europe/Rome';

interface TriggerEditorModalProps {
  automation: AutomationSummary;
  onClose: () => void;
  onSaved: () => void;
}

/** Pianificazione cron e webhook di un'automazione; gli altri trigger (manuali, eventi) restano invariati. */
export const TriggerEditorModal: React.FC<TriggerEditorModalProps> = ({ automation, onClose, onSaved }) => {
  const existing = (automation.triggers || []) as Trigger[];
  const cronTrigger = existing.find((t) => t.type === 'cron');
  const webhookTrigger = existing.find((t) => t.type === 'webhook');
  const timezone = cronTrigger?.timezone || DEFAULT_TIMEZONE;

  const [cronEnabled, setCronEnabled] = useState(Boolean(cronTrigger));
  const [schedule, setSchedule] = useState<Schedule>(() => parseCron(cronTrigger?.cron_expression));
  const [webhookEnabled, setWebhookEnabled] = useState(Boolean(webhookTrigger));
  const [webhookToken, setWebhookToken] = useState(webhookTrigger?.webhook_token || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await updateAutomationTriggers(
        automation.id,
        buildTriggers(existing, { enabled: cronEnabled, expression: toCron(schedule), timezone }, { enabled: webhookEnabled, token: webhookToken })
      );
      onSaved();
      onClose();
    } catch (err) {
      setError(formatApiError(err, 'Errore durante il salvataggio dei trigger.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-panel border border-border rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-panel-header/40">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-accent/10 border border-accent/20 text-accent">
              <Sliders className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-fg flex items-center gap-2">Pianificazione & Trigger</h2>
              <p className="text-xs text-fg-muted">
                Automazione: <span className="text-accent font-mono">{automation.name}</span>
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-fg-muted hover:text-fg hover:bg-panel-header transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6 overflow-y-auto flex-1 custom-scrollbar text-sm">
          {error && (
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-rose-500 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <CronScheduleSection
            enabled={cronEnabled}
            onEnabledChange={setCronEnabled}
            schedule={schedule}
            onChange={(patch) => setSchedule((s) => ({ ...s, ...patch }))}
            timezone={timezone}
          />
          <WebhookSection
            automationId={automation.id}
            enabled={webhookEnabled}
            onEnabledChange={setWebhookEnabled}
            token={webhookToken}
            onTokenChange={setWebhookToken}
            onError={setError}
          />
        </div>

        <div className="px-6 py-4 border-t border-border bg-panel-header/40 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-medium text-fg-muted hover:text-fg hover:bg-panel-header transition"
          >
            Annulla
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="px-5 py-2 rounded-xl text-xs font-semibold bg-accent hover:bg-accent-hover text-white shadow-lg shadow-accent/25 flex items-center gap-2 transition disabled:opacity-50"
          >
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
            <span>{saving ? 'Salvataggio...' : 'Salva Modifiche Trigger'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
