import React, { useCallback, useEffect, useId, useState } from 'react';
import { Loader2, Plus, RefreshCw } from 'lucide-react';
import {
  getModelCatalog,
  getProviderCosts,
  getProviders,
  setProviderSettings,
  TOTAL_SCOPE,
  type ModelCatalogResponse,
  type ProviderCosts,
  type ProvidersResponse,
} from '../../../api/providers';
import { useConfirm } from '../../../hooks/useConfirm';
import { useFeedback } from '../../../hooks/useFeedback';
import { formatApiError } from '../../../utils/error';
import { providerErrorMessage } from '../../../utils/providerErrors';
import { ConfirmDialog } from '../../ConfirmDialog';
import { AddProviderForm } from './AddProviderForm';
import { SpendCeiling } from './CostsSection';
import { inputClass } from './providerStyles';
import { ProviderCard } from './ProviderCard';

/**
 * Provider di modelli: elenco con stato, modulo e credenziali di ognuno, livello dei dati, prezzi e tetti; in fondo
 * l'aggiunta di un provider, il tetto complessivo, il provider predefinito e quello di ripiego. Le modifiche valgono subito.
 */
export const ProvidersTab: React.FC = () => {
  const selectsId = useId();
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [costs, setCosts] = useState<ProviderCosts | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const { feedback, notify } = useFeedback();
  const { confirm, dialog } = useConfirm();

  const load = useCallback(async () => {
    try {
      const [providers, spend, models] = await Promise.all([
        getProviders(),
        getProviderCosts().catch((err) => {
          console.warn('Costi non caricati:', err);
          return null;
        }),
        getModelCatalog().catch((err) => {
          console.warn('Catalogo dei modelli non caricato:', err);
          return null;
        }),
      ]);
      setData(providers);
      setCosts(spend);
      setCatalog(models);
    } catch (err) {
      notify('error', `Provider non caricati: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    load();
  }, [load]);

  const changeSettings = async (change: { default_provider?: string; fallback_provider?: string }) => {
    try {
      await setProviderSettings(change);
      notify('success', 'Impostazioni salvate.');
      await load();
    } catch (err) {
      notify('error', providerErrorMessage(err));
    }
  };

  const providers = data?.providers ?? [];
  // Il ripiego deve poter ricevere dati privati ed essere attivo (5.8.3)
  const fallbackChoices = providers.filter((p) => p.enabled && p.clearance.effective === 'private');
  const defaultChoices = providers.filter((p) => p.enabled && p.configured);

  const withCurrent = <T extends { name: string }>(choices: T[], current: string | undefined, all: T[]) =>
    current && !choices.some((p) => p.name === current) ? [...choices, ...all.filter((p) => p.name === current)] : choices;

  return (
    <div className="stack-y-3">
      <ConfirmDialog {...dialog} />
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-fg-muted leading-relaxed">
          Provider di modelli. I valori vengono dal <code>.env</code> finché non li cambi qui; «torna al .env» toglie il valore della UI. Le
          credenziali si scrivono e non si rileggono. Le modifiche valgono subito, senza riavvio.
        </p>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            load();
          }}
          disabled={loading}
          aria-label="Ricarica i provider"
          className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover shrink-0 cursor-pointer"
          title="Ricarica i provider"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
        </button>
      </div>

      {feedback && (
        <div
          role={feedback.type === 'error' ? 'alert' : 'status'}
          className={`p-2 rounded-lg text-xs border ${
            feedback.type === 'success' ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300' : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
          }`}
        >
          {feedback.text}
        </div>
      )}

      {loading && !data && (
        <p className="flex items-center gap-2 text-xs text-fg-muted">
          <Loader2 size={13} className="animate-spin" aria-hidden="true" /> Caricamento dei provider...
        </p>
      )}

      {data && (
        <>
          <div className="stack-y-2">
            {providers.map((provider) => (
              <ProviderCard
                key={provider.name}
                provider={provider}
                canStoreSecrets={data.can_store_secrets}
                costs={costs}
                catalogModels={catalog?.providers.find((p) => p.name === provider.name)?.models.map((m) => m.id) ?? []}
                confirm={confirm}
                onChanged={load}
              />
            ))}
          </div>

          {adding ? (
            <AddProviderForm canStoreSecrets={data.can_store_secrets} onCreated={load} onCancel={() => setAdding(false)} />
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-fg hover:bg-panel-hover text-xs font-semibold cursor-pointer"
            >
              <Plus size={13} aria-hidden="true" /> Aggiungi provider
            </button>
          )}

          <div className="bg-panel/70 border border-border rounded-xl p-3.5 stack-y-3" role="group" aria-label="Impostazioni generali dei provider">
            <h3 className="text-xs font-semibold text-fg">Impostazioni generali</h3>
            <SpendCeiling scope={TOTAL_SCOPE} label="Tetto mensile totale ($)" costs={costs} onChanged={load} notify={notify} />

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="stack-y-1">
                <label htmlFor={`${selectsId}-default`} className="block text-xs font-medium text-fg-muted">
                  Provider predefinito
                </label>
                <select
                  id={`${selectsId}-default`}
                  value={data.default_provider}
                  onChange={(e) => changeSettings({ default_provider: e.target.value })}
                  className={`${inputClass} cursor-pointer`}
                >
                  {withCurrent(defaultChoices, data.default_provider, providers).map((p) => (
                    <option key={p.name} value={p.name} className="bg-panel text-fg">
                      {p.display_name}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-fg-muted">Lo usa una richiesta senza provider e il lavoro in background.</p>
              </div>
              <div className="stack-y-1">
                <label htmlFor={`${selectsId}-fallback`} className="block text-xs font-medium text-fg-muted">
                  Provider di ripiego
                </label>
                <select
                  id={`${selectsId}-fallback`}
                  value={data.fallback_provider}
                  onChange={(e) => changeSettings({ fallback_provider: e.target.value })}
                  className={`${inputClass} cursor-pointer`}
                >
                  {withCurrent(fallbackChoices, data.fallback_provider, providers).map((p) => (
                    <option key={p.name} value={p.name} className="bg-panel text-fg">
                      {p.display_name}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-fg-muted">
                  Riceve le chiamate rimandate per l'etichetta dei dati o per il tetto. Deve essere attivo e ricevere dati privati.
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
