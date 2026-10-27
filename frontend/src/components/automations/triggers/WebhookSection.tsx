import React, { useState } from 'react';
import { Check, Code, Copy, Globe, RefreshCw } from 'lucide-react';
import { regenerateWebhookToken } from '../../../api/automations';
import { useCopyFeedback } from '../../../hooks/useCopyFeedback';
import { formatApiError } from '../../../utils/error';
import { Toggle } from '../../Toggle';

interface WebhookSectionProps {
  automationId: string;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  token: string;
  onTokenChange: (token: string) => void;
  onError: (message: string | null) => void;
}

export const WebhookSection: React.FC<WebhookSectionProps> = ({ automationId, enabled, onEnabledChange, token, onTokenChange, onError }) => {
  const [isRegenerating, setIsRegenerating] = useState(false);
  const urlCopy = useCopyFeedback();
  const curlCopy = useCopyFeedback();

  const url = `${window.location.origin}/v1/automations/${automationId}/webhook/${token || '<GENERA_TOKEN>'}`;
  const curl = `curl -X POST "${url}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"inputs": {}}'`;

  const regenerate = async () => {
    if (!confirm('Sei sicuro di voler rigenerare il token webhook? Il token precedente non funzionerà più.')) return;
    setIsRegenerating(true);
    onError(null);
    try {
      const res = await regenerateWebhookToken(automationId);
      onTokenChange(res.webhook_token);
      onEnabledChange(true);
    } catch (err) {
      onError(formatApiError(err, 'Errore durante la rigenerazione del token.'));
    } finally {
      setIsRegenerating(false);
    }
  };

  return (
    <div className="p-4 rounded-xl bg-panel-header/20 border border-border/70 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Globe className="w-4 h-4 text-sky-400" />
          <span className="font-medium text-fg">Trigger Webhook HTTP (Eventi Esterni)</span>
        </div>
        <Toggle checked={enabled} onChange={onEnabledChange} activeClass="peer-checked:bg-sky-500" />
      </div>

      <p className="text-xs text-fg-muted">
        Permette di far scattare questa automazione da sistemi esterni (Home Assistant, sensori IoT, GitHub Webhook, Grafana Alerts, script bash)
        tramite richiesta POST HTTP con autenticazione via token dedicato.
      </p>

      {enabled && (
        <div className="space-y-3 pt-2 border-t border-border/60">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-fg-muted font-medium">URL Endpoint Webhook</label>
              <button
                type="button"
                onClick={regenerate}
                disabled={isRegenerating}
                className="text-[11px] text-amber-500 hover:text-amber-400 flex items-center gap-1 transition"
              >
                <RefreshCw className={`w-3 h-3 ${isRegenerating ? 'animate-spin' : ''}`} />
                <span>Rigenera Token Segreto</span>
              </button>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={url}
                className="flex-1 bg-input-bg border border-input-border rounded-lg px-3 py-2 text-xs text-sky-500 font-mono truncate select-all focus:outline-none"
              />
              <button
                type="button"
                onClick={() => urlCopy.copy(url)}
                className="p-2 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-500 border border-sky-500/30 transition flex items-center gap-1.5"
              >
                {urlCopy.copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                <span className="text-xs">{urlCopy.copied ? 'Copiato' : 'Copia'}</span>
              </button>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-fg-muted flex items-center gap-1">
                <Code className="w-3.5 h-3.5" />
                <span>Esempio di chiamata cURL</span>
              </label>
              <button
                type="button"
                onClick={() => curlCopy.copy(curl)}
                className="text-[11px] text-fg-muted hover:text-fg flex items-center gap-1 transition"
              >
                {curlCopy.copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>{curlCopy.copied ? 'Copiato' : 'Copia cURL'}</span>
              </button>
            </div>
            <pre className="bg-input-bg border border-border rounded-lg p-3 text-[11px] font-mono text-fg/90 overflow-x-auto">{curl}</pre>
          </div>
        </div>
      )}
    </div>
  );
};
