import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, KeyRound, X, Save, CheckCircle2, Cpu, Box, Loader2, AlertCircle } from 'lucide-react';
import { getApiKey, setApiKey, getProviders, getProviderModels, setDefaultProvider, type ProviderInfo } from '../api';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProviderChanged?: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, onProviderChanged }) => {
  const [apiKey, setLocalApiKey] = useState(getApiKey());
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Provider & Model state
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>('');
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [loadingProviders, setLoadingProviders] = useState<boolean>(false);
  const [loadingModels, setLoadingModels] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);

  useEffect(() => {
    if (!isOpen) return;

    setLocalApiKey(getApiKey());
    setError(null);
    setLoadingProviders(true);

    getProviders()
      .then((data) => {
        setProviders(data.providers);
        const activeProv = data.active_provider || (data.providers[0] ? data.providers[0].name : '');
        setSelectedProvider(activeProv);
        setSelectedModel(data.active_model || '');

        if (activeProv) {
          setLoadingModels(true);
          getProviderModels(activeProv)
            .then((mList) => {
              setModels(mList);
              if (!data.active_model && mList.length > 0) {
                setSelectedModel(mList[0]);
              }
            })
            .catch((err) => {
              console.warn('Errore recupero modelli:', err);
            })
            .finally(() => setLoadingModels(false));
        }
      })
      .catch((err) => {
        console.warn('Errore recupero providers:', err);
        setError('Impossibile caricare la lista dei provider LLM dal backend.');
      })
      .finally(() => setLoadingProviders(false));
  }, [isOpen]);

  const handleProviderChange = (newProvider: string) => {
    setSelectedProvider(newProvider);
    setLoadingModels(true);
    getProviderModels(newProvider)
      .then((mList) => {
        setModels(mList);
        const provObj = providers.find((p) => p.name === newProvider);
        const defaultForProv = provObj?.default_model;
        if (defaultForProv && mList.includes(defaultForProv)) {
          setSelectedModel(defaultForProv);
        } else if (mList.length > 0) {
          setSelectedModel(mList[0]);
        } else {
          setSelectedModel('');
        }
      })
      .catch((err) => {
        console.warn('Errore recupero modelli per provider:', err);
        setModels([]);
      })
      .finally(() => setLoadingModels(false));
  };

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      setApiKey(apiKey);

      if (selectedProvider) {
        await setDefaultProvider(selectedProvider, selectedModel || undefined);
        if (onProviderChanged) {
          onProviderChanged();
        }
      }

      setSaved(true);
      setTimeout(() => {
        setSaved(false);
        onClose();
      }, 800);
    } catch (err: any) {
      console.error('Errore salvataggio impostazioni:', err);
      setError(err?.response?.data?.detail || err?.message || 'Errore salvataggio impostazioni');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-md p-5 space-y-4 text-slate-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-slate-200">
            <SettingsIcon size={16} className="text-blue-400" />
            <span className="font-semibold text-sm">Impostazioni</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-500 hover:text-white hover:bg-slate-800 rounded transition"
          >
            <X size={16} />
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-rose-950/70 border border-rose-800/80 rounded-lg p-2.5 text-xs text-rose-200">
            <AlertCircle size={14} className="text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* API Key */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
            <KeyRound size={12} className="text-amber-400" />
            API Key (header X-API-Key)
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setLocalApiKey(e.target.value)}
            placeholder="Inserisci la chiave API del backend..."
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500/60"
          />
          <p className="text-[10px] text-slate-500 leading-snug">
            Salvata in localStorage e inviata automaticamente alle chiamate API.
          </p>
        </div>

        <div className="border-t border-slate-800 pt-3 space-y-3">
          {/* Provider Selection */}
          <div className="space-y-1.5">
            <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
              <Cpu size={12} className="text-blue-400" />
              Provider LLM
              {loadingProviders && <Loader2 size={12} className="animate-spin text-blue-400 ml-1" />}
            </label>
            <select
              value={selectedProvider}
              onChange={(e) => handleProviderChange(e.target.value)}
              disabled={loadingProviders || providers.length === 0}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500/60 disabled:opacity-50 capitalize"
            >
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} {p.healthy ? '● (online)' : '○ (offline)'}
                </option>
              ))}
              {providers.length === 0 && !loadingProviders && (
                <option value="">Nessun provider disponibile</option>
              )}
            </select>
          </div>

          {/* Model Selection */}
          <div className="space-y-1.5">
            <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
              <Box size={12} className="text-emerald-400" />
              Modello di Default
              {loadingModels && <Loader2 size={12} className="animate-spin text-emerald-400 ml-1" />}
            </label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={loadingModels || models.length === 0}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500/60 disabled:opacity-50 font-mono"
            >
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              {models.length === 0 && !loadingModels && (
                <option value="">Nessun modello trovato</option>
              )}
            </select>
            <p className="text-[10px] text-slate-500 leading-snug">
              Imposta il modello predefinito usato dall'agente se non sovrascritto in chat.
            </p>
          </div>
        </div>

        {/* Save */}
        <button
          onClick={handleSave}
          disabled={saving}
          className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-50 ${
            saved
              ? 'bg-emerald-600/30 border border-emerald-500/50 text-emerald-300'
              : 'bg-blue-600 hover:bg-blue-500 text-white'
          }`}
        >
          {saved ? (
            <>
              <CheckCircle2 size={13} />
              Salvato!
            </>
          ) : saving ? (
            <>
              <Loader2 size={13} className="animate-spin" />
              Salvataggio...
            </>
          ) : (
            <>
              <Save size={13} />
              Salva impostazioni
            </>
          )}
        </button>
      </div>
    </div>
  );
};
