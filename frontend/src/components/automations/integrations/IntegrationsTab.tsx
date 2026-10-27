import React from 'react';
import { Check, Key, RefreshCw, Shield } from 'lucide-react';
import type { Notify } from '../../../hooks/useFeedback';
import { useIntegrations } from '../../../hooks/useIntegrations';
import { IntegrationForm } from './IntegrationForm';
import { INTEGRATION_SPECS } from './specs';

const GUARANTEES = [
  [
    'Nessun Invio Automatico',
    "l'agente può leggere le email e creare bozze di risposta (Draft), ma non invierà mai email senza autorizzazione esplicita.",
  ],
  ['Cifratura AES a Riposo', 'tutte le password e token sono memorizzati cifrati con Fernet AES nel database dedicato delle automazioni.'],
  ['Scoped Secret Whitelist', 'ogni workflow accede unicamente ai secret esplicitamente dichiarati nella propria permission policy.'],
];

/** Credenziali dei servizi esterni usati dalle automazioni. */
export const IntegrationsTab: React.FC<{ onFeedback: Notify }> = ({ onFeedback }) => {
  const actions = useIntegrations(onFeedback);

  return (
    <div className="space-y-6">
      <div className="p-4 rounded-2xl bg-panel border border-border/80 flex items-start justify-between gap-3 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shrink-0 mt-0.5">
            <Key size={18} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-fg">Integrazioni & Credenziali Servizi</h2>
            <p className="text-xs text-fg-muted mt-0.5 leading-relaxed">
              Configura in sicurezza gli account esterni (posta IMAP per i briefing, GitHub per gli auto-repair, Home Assistant per la
              domotica). Le credenziali sensibili sono cifrate a riposo con crittografia simmetrica AES e non vengono mai esposte in chiaro.
            </p>
          </div>
        </div>
        <button
          onClick={actions.reload}
          disabled={actions.isLoading}
          className="p-2 text-fg-muted hover:text-fg hover:bg-panel-header/60 rounded-xl border border-border transition cursor-pointer shrink-0"
          title="Ricarica integrazioni"
        >
          <RefreshCw size={15} className={actions.isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {INTEGRATION_SPECS.map((spec) => {
          const integration = actions.integrations.find((i) => i.id === spec.id);
          // La key rimonta il form quando il backend restituisce dati nuovi, così i campi riflettono lo stato salvato
          return <IntegrationForm key={`${spec.id}:${integration?.updated_at ?? 'new'}`} spec={spec} integration={integration} actions={actions} />;
        })}

        <div className="p-5 rounded-2xl bg-panel border border-border flex flex-col justify-between space-y-4 shadow-sm">
          <div className="space-y-3">
            <div className="flex items-center gap-2.5 pb-3 border-b border-border/60">
              <div className="w-8 h-8 rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/30 flex items-center justify-center">
                <Shield size={16} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-fg">Policy di Sicurezza e Zero Auto-Send</h3>
                <span className="text-[11px] text-fg-muted">Garanzie operative del runtime Homelab</span>
              </div>
            </div>
            <ul className="space-y-2 text-xs text-fg-muted">
              {GUARANTEES.map(([title, text]) => (
                <li key={title} className="flex items-start gap-2">
                  <Check size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                  <span>
                    <strong>{title}</strong>: {text}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};
