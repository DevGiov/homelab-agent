import React, { useEffect, useState } from 'react';
import { AlertCircle, Box, CheckCircle2, Cpu, KeyRound, Loader2, Save } from 'lucide-react';
import { getApiKey, setApiKey } from '../../api/http';
import { getProviderModels, getProviders, setDefaultProvider, type ProviderInfo } from '../../api/providers';
import { formatApiError } from '../../utils/error';

const fieldClass =
  'w-full bg-input-bg border border-input-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent disabled:opacity-50';

/** API key, provider e modello di default; il salvataggio chiude il modale. */
export const GeneralTab: React.FC<{ onSaved: () => void }> = ({ onSaved }) => {
  const [apiKey, setLocalApiKey] = useState(getApiKey());
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [provider, setProvider] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [loadingProviders, setLoadingProviders] = useState(true);
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Modelli del provider; `preferred` resta selezionato se il provider lo offre, altrimenti il primo. */
  const loadModels = async (providerName: string, preferred?: string) => {
    setLoadingModels(true);
    try {
      const list = await getProviderModels(providerName);
      setModels(list);
      setModel(preferred || list[0] || '');
    } catch (err) {
      console.warn('Errore recupero modelli:', err);
      setModels([]);
    } finally {
      setLoadingModels(false);
    }
  };

  useEffect(() => {
    getProviders()
      .then((data) => {
        setProviders(data.providers);
        const active = data.active_provider || data.providers[0]?.name || '';
        setProvider(active);
        setModel(data.active_model || '');
        if (active) loadModels(active, data.active_model);
      })
      .catch((err) => {
        console.warn('Errore recupero providers:', err);
        setError('Impossibile caricare la lista dei provider LLM dal backend.');
      })
      .finally(() => setLoadingProviders(false));
  }, []);

  const changeProvider = (name: string) => {
    setProvider(name);
    loadModels(name);
  };

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      setApiKey(apiKey);
      if (provider) await setDefaultProvider(provider, model || undefined);
      setSaved(true);
      setTimeout(onSaved, 800);
    } catch (err) {
      setError(formatApiError(err, 'Errore salvataggio impostazioni'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {error && (
        <div className="flex items-center gap-2 bg-rose-950/70 border border-rose-800/80 rounded-xl p-2.5 text-xs text-rose-200">
          <AlertCircle size={14} className="text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
          <KeyRound size={12} className="text-amber-400" />
          API Key (header X-API-Key)
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setLocalApiKey(e.target.value)}
          placeholder="Inserisci la chiave API del backend..."
          className={`${fieldClass} font-mono placeholder:text-fg-muted/50`}
        />
        <p className="text-[10px] text-fg-muted leading-snug">Salvata in localStorage e inviata automaticamente alle chiamate API.</p>
      </div>

      <div className="border-t border-border pt-3 space-y-3">
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
            <Cpu size={12} className="text-accent" />
            Provider LLM
            {loadingProviders && <Loader2 size={12} className="animate-spin text-accent ml-1" />}
          </label>
          <select
            value={provider}
            onChange={(e) => changeProvider(e.target.value)}
            disabled={loadingProviders || providers.length === 0}
            className={`${fieldClass} capitalize`}
          >
            {providers.map((p) => (
              <option key={p.name} value={p.name} className="bg-panel text-fg">
                {p.name} {p.healthy ? '● (online)' : '○ (offline)'}
              </option>
            ))}
            {providers.length === 0 && !loadingProviders && (
              <option value="" className="bg-panel text-fg">Nessun provider disponibile</option>
            )}
          </select>
        </div>

        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
            <Box size={12} className="text-emerald-400" />
            Modello di Default
            {loadingModels && <Loader2 size={12} className="animate-spin text-emerald-400 ml-1" />}
          </label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={loadingModels || models.length === 0}
            className={`${fieldClass} font-mono`}
          >
            {models.map((m) => (
              <option key={m} value={m} className="bg-panel text-fg">
                {m}
              </option>
            ))}
            {models.length === 0 && !loadingModels && <option value="" className="bg-panel text-fg">Nessun modello trovato</option>}
          </select>
          <p className="text-[10px] text-fg-muted leading-snug">Imposta il modello predefinito usato dall'agente se non sovrascritto in chat.</p>
        </div>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition cursor-pointer disabled:opacity-50 ${
          saved ? 'bg-emerald-600/30 border border-emerald-500/50 text-emerald-300' : 'bg-accent hover:bg-accent-hover text-white shadow-lg shadow-accent/25'
        }`}
      >
        {saved ? (
          <>
            <CheckCircle2 size={13} /> Salvato!
          </>
        ) : saving ? (
          <>
            <Loader2 size={13} className="animate-spin" /> Salvataggio...
          </>
        ) : (
          <>
            <Save size={13} /> Salva impostazioni
          </>
        )}
      </button>
    </>
  );
};
