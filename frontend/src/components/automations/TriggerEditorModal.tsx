import React, { useState, useEffect } from 'react';
import {
  Clock,
  Globe,
  Copy,
  Check,
  RefreshCw,
  AlertCircle,
  Calendar,
  Zap,
  Sliders,
  X,
  Code
} from 'lucide-react';
import { updateAutomationTriggers, regenerateWebhookToken, type AutomationSummary } from '../../api';

interface TriggerEditorModalProps {
  automation: AutomationSummary;
  onClose: () => void;
  onSaved: () => void;
}

type FrequencyType = 'daily' | 'weekly' | 'hourly' | 'custom';

export const TriggerEditorModal: React.FC<TriggerEditorModalProps> = ({
  automation,
  onClose,
  onSaved,
}) => {
  // Existing triggers inspection
  const existingCron = (automation.triggers || []).find((t) => t.type === 'cron');
  const existingWebhook = (automation.triggers || []).find((t) => t.type === 'webhook');

  // Cron state
  const [cronEnabled, setCronEnabled] = useState<boolean>(!!existingCron);
  const [frequency, setFrequency] = useState<FrequencyType>('daily');
  const [hour, setHour] = useState<number>(8);
  const [minute, setMinute] = useState<number>(0);
  const [dayOfWeek, setDayOfWeek] = useState<number>(1); // 1 = Monday
  const [hourlyInterval, setHourlyInterval] = useState<number>(2);
  const [customCron, setCustomCron] = useState<string>('0 8 * * *');

  // Webhook state
  const [webhookEnabled, setWebhookEnabled] = useState<boolean>(!!existingWebhook);
  const [webhookToken, setWebhookToken] = useState<string>(existingWebhook?.webhook_token || '');
  const [copiedUrl, setCopiedUrl] = useState<boolean>(false);
  const [copiedCurl, setCopiedCurl] = useState<boolean>(false);
  const [isRegenerating, setIsRegenerating] = useState<boolean>(false);

  // General state
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Parse existing cron expression on mount
  useEffect(() => {
    if (existingCron?.cron_expression) {
      const parts = existingCron.cron_expression.trim().split(/\s+/);
      if (parts.length === 5) {
        const [m, h, dom, mon, dow] = parts;
        if (dom === '*' && mon === '*' && dow === '*' && !isNaN(Number(m)) && !isNaN(Number(h))) {
          setFrequency('daily');
          setHour(Number(h));
          setMinute(Number(m));
        } else if (dom === '*' && mon === '*' && !isNaN(Number(m)) && !isNaN(Number(h)) && dow !== '*') {
          setFrequency('weekly');
          setHour(Number(h));
          setMinute(Number(m));
          setDayOfWeek(Number(dow) || 1);
        } else if (h.startsWith('*/') && dom === '*' && mon === '*' && dow === '*') {
          setFrequency('hourly');
          const interval = parseInt(h.replace('*/', ''), 10);
          setHourlyInterval(interval || 2);
          setMinute(Number(m) || 0);
        } else {
          setFrequency('custom');
          setCustomCron(existingCron.cron_expression);
        }
      } else {
        setFrequency('custom');
        setCustomCron(existingCron.cron_expression);
      }
    }
  }, [existingCron]);

  // Compute computed cron string
  const getComputedCron = (): string => {
    if (frequency === 'daily') {
      return `${minute} ${hour} * * *`;
    }
    if (frequency === 'weekly') {
      return `${minute} ${hour} * * ${dayOfWeek}`;
    }
    if (frequency === 'hourly') {
      return `${minute} */${hourlyInterval} * * *`;
    }
    return customCron.trim();
  };

  const getHumanScheduleText = (): string => {
    if (!cronEnabled) return 'Nessuna esecuzione pianificata automatica.';
    const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
    const timeStr = `${pad(hour)}:${pad(minute)}`;
    const dayNames = ['Domenica', 'Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica'];

    if (frequency === 'daily') {
      return `Ogni giorno alle ore ${timeStr} (fuso Europe/Rome).`;
    }
    if (frequency === 'weekly') {
      return `Ogni ${dayNames[dayOfWeek] || 'settimana'} alle ore ${timeStr} (fuso Europe/Rome).`;
    }
    if (frequency === 'hourly') {
      return `Ogni ${hourlyInterval} ore al minuto ${pad(minute)}.`;
    }
    return `Espressione cron personalizzata: ${customCron}`;
  };

  const originUrl = window.location.origin;
  const webhookPath = webhookToken
    ? `/v1/automations/${automation.id}/webhook/${webhookToken}`
    : `/v1/automations/${automation.id}/webhook/<GENERA_TOKEN>`;
  const fullWebhookUrl = `${originUrl}${webhookPath}`;

  const curlSnippet = `curl -X POST "${fullWebhookUrl}" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {}}'`;

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(fullWebhookUrl);
    setCopiedUrl(true);
    setTimeout(() => setCopiedUrl(false), 2000);
  };

  const handleCopyCurl = () => {
    navigator.clipboard.writeText(curlSnippet);
    setCopiedCurl(true);
    setTimeout(() => setCopiedCurl(false), 2000);
  };

  const handleRegenerateToken = async () => {
    if (!confirm('Sei sicuro di voler rigenerare il token webhook? Il token precedente non funzionerà più.')) {
      return;
    }
    setIsRegenerating(true);
    setError(null);
    try {
      const res = await regenerateWebhookToken(automation.id);
      setWebhookToken(res.webhook_token);
      setWebhookEnabled(true);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Errore durante la rigenerazione del token.');
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);

    const triggersToSave: any[] = [];

    // 1. Cron Trigger
    if (cronEnabled) {
      const finalCron = getComputedCron();
      triggersToSave.push({
        id: existingCron?.id || 'trg_cron_main',
        type: 'cron',
        cron_expression: finalCron,
        timezone: 'Europe/Rome',
        enabled: true,
      });
    }

    // 2. Webhook Trigger
    if (webhookEnabled) {
      triggersToSave.push({
        id: existingWebhook?.id || 'trg_webhook_main',
        type: 'webhook',
        webhook_token: webhookToken || undefined,
        enabled: true,
      });
    }

    // 3. Fallback manual trigger if neither is active
    if (triggersToSave.length === 0) {
      triggersToSave.push({
        id: 'trg_manual',
        type: 'manual',
        enabled: true,
      });
    }

    try {
      await updateAutomationTriggers(automation.id, triggersToSave);
      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Errore durante il salvataggio dei trigger.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#121622] border border-slate-700/80 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Sliders className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
                Pianificazione & Trigger
              </h2>
              <p className="text-xs text-slate-400">
                Automazione: <span className="text-indigo-300 font-mono">{automation.name}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 space-y-6 overflow-y-auto flex-1 custom-scrollbar text-sm">
          {error && (
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* SECTION 1: CRON SCHEDULE */}
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800/80 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Clock className="w-4 h-4 text-emerald-400" />
                <span className="font-medium text-slate-200">Schedulazione Temporale (Cron)</span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={cronEnabled}
                  onChange={(e) => setCronEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500"></div>
              </label>
            </div>

            {cronEnabled && (
              <div className="space-y-4 pt-2 border-t border-slate-800/60">
                {/* Frequency Selector Pills */}
                <div className="flex gap-2">
                  {(['daily', 'weekly', 'hourly', 'custom'] as FrequencyType[]).map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setFrequency(f)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                        frequency === f
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm'
                          : 'bg-slate-800/50 text-slate-400 hover:text-slate-300 border border-slate-700/40'
                      }`}
                    >
                      {f === 'daily' && 'Giornaliero'}
                      {f === 'weekly' && 'Settimanale'}
                      {f === 'hourly' && 'Intervallo Orario'}
                      {f === 'custom' && 'Cron Avanzato'}
                    </button>
                  ))}
                </div>

                {/* Daily or Weekly Controls */}
                {(frequency === 'daily' || frequency === 'weekly') && (
                  <div className="grid grid-cols-2 gap-4">
                    {frequency === 'weekly' && (
                      <div>
                        <label className="block text-xs text-slate-400 mb-1">Giorno della settimana</label>
                        <select
                          value={dayOfWeek}
                          onChange={(e) => setDayOfWeek(Number(e.target.value))}
                          className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                        >
                          <option value={1}>Lunedì</option>
                          <option value={2}>Martedì</option>
                          <option value={3}>Mercoledì</option>
                          <option value={4}>Giovedì</option>
                          <option value={5}>Venerdì</option>
                          <option value={6}>Sabato</option>
                          <option value={0}>Domenica</option>
                        </select>
                      </div>
                    )}
                    <div className={frequency === 'daily' ? 'col-span-2 flex gap-4' : ''}>
                      <div className="flex-1">
                        <label className="block text-xs text-slate-400 mb-1">Ora (0-23)</label>
                        <input
                          type="number"
                          min={0}
                          max={23}
                          value={hour}
                          onChange={(e) => setHour(Math.max(0, Math.min(23, Number(e.target.value))))}
                          className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="block text-xs text-slate-400 mb-1">Minuto (0-59)</label>
                        <input
                          type="number"
                          min={0}
                          max={59}
                          value={minute}
                          onChange={(e) => setMinute(Math.max(0, Math.min(59, Number(e.target.value))))}
                          className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Hourly interval controls */}
                {frequency === 'hourly' && (
                  <div className="flex gap-4">
                    <div className="flex-1">
                      <label className="block text-xs text-slate-400 mb-1">Ogni quante ore</label>
                      <select
                        value={hourlyInterval}
                        onChange={(e) => setHourlyInterval(Number(e.target.value))}
                        className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                      >
                        <option value={1}>Ogni 1 ora</option>
                        <option value={2}>Ogni 2 ore</option>
                        <option value={3}>Ogni 3 ore</option>
                        <option value={4}>Ogni 4 ore</option>
                        <option value={6}>Ogni 6 ore</option>
                        <option value={12}>Ogni 12 ore</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs text-slate-400 mb-1">Al minuto</label>
                      <input
                        type="number"
                        min={0}
                        max={59}
                        value={minute}
                        onChange={(e) => setMinute(Math.max(0, Math.min(59, Number(e.target.value))))}
                        className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                      />
                    </div>
                  </div>
                )}

                {/* Custom Cron input */}
                {frequency === 'custom' && (
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Espressione Cron standard (5 campi: m h dom mon dow)
                    </label>
                    <input
                      type="text"
                      value={customCron}
                      onChange={(e) => setCustomCron(e.target.value)}
                      placeholder="es. 0 8 * * 1-5"
                      className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>
                )}

                {/* Human natural language preview */}
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 text-emerald-300">
                    <Calendar className="w-4 h-4 shrink-0" />
                    <span>{getHumanScheduleText()}</span>
                  </div>
                  <span className="font-mono text-[11px] bg-slate-950/80 px-2 py-0.5 rounded text-emerald-400 border border-emerald-500/30">
                    {getComputedCron()}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* SECTION 2: WEBHOOK HTTP TRIGGER */}
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800/80 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Globe className="w-4 h-4 text-sky-400" />
                <span className="font-medium text-slate-200">Trigger Webhook HTTP (Eventi Esterni)</span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={webhookEnabled}
                  onChange={(e) => setWebhookEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-sky-500"></div>
              </label>
            </div>

            <p className="text-xs text-slate-400">
              Permette di far scattare questa automazione da sistemi esterni (Home Assistant, sensori IoT, GitHub Webhook, Grafana Alerts, script bash) tramite richiesta POST HTTP con autenticazione via token dedicato.
            </p>

            {webhookEnabled && (
              <div className="space-y-3 pt-2 border-t border-slate-800/60">
                {/* Webhook URL bar */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-slate-400 font-medium">URL Endpoint Webhook</label>
                    <button
                      type="button"
                      onClick={handleRegenerateToken}
                      disabled={isRegenerating}
                      className="text-[11px] text-amber-400 hover:text-amber-300 flex items-center gap-1 transition"
                    >
                      <RefreshCw className={`w-3 h-3 ${isRegenerating ? 'animate-spin' : ''}`} />
                      <span>Rigenera Token Segreto</span>
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      readOnly
                      value={fullWebhookUrl}
                      className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-sky-300 font-mono truncate select-all focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={handleCopyUrl}
                      className="p-2 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 transition flex items-center gap-1.5"
                    >
                      {copiedUrl ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                      <span className="text-xs">{copiedUrl ? 'Copiato' : 'Copia'}</span>
                    </button>
                  </div>
                </div>

                {/* Curl Code Example */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-slate-400 flex items-center gap-1">
                      <Code className="w-3.5 h-3.5" />
                      <span>Esempio di chiamata cURL</span>
                    </label>
                    <button
                      type="button"
                      onClick={handleCopyCurl}
                      className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1 transition"
                    >
                      {copiedCurl ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                      <span>{copiedCurl ? 'Copiato' : 'Copia cURL'}</span>
                    </button>
                  </div>
                  <pre className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-[11px] font-mono text-slate-300 overflow-x-auto">
                    {curlSnippet}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-900/60 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
          >
            Annulla
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/20 flex items-center gap-2 transition disabled:opacity-50"
          >
            {saving ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Zap className="w-3.5 h-3.5" />
            )}
            <span>{saving ? 'Salvataggio...' : 'Salva Modifiche Trigger'}</span>
          </button>
        </div>

      </div>
    </div>
  );
};
