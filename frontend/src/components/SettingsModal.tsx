import React, { useState, useEffect, useCallback } from 'react';
import {
  Settings as SettingsIcon,
  KeyRound,
  X,
  Save,
  CheckCircle2,
  Cpu,
  Box,
  Loader2,
  AlertCircle,
  Brain,
  Trash2,
  Plus,
  RefreshCw,
  AlertTriangle,
  Search,
} from 'lucide-react';
import {
  getApiKey,
  setApiKey,
  getProviders,
  getProviderModels,
  setDefaultProvider,
  getMemories,
  addMemory,
  deleteMemory,
  clearAllMemory,
  type ProviderInfo,
  type MemoryItem,
} from '../api';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProviderChanged?: () => void;
}

type SettingsTab = 'general' | 'memory';

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, onProviderChanged }) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
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

  // Memory Management state
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [totalMemories, setTotalMemories] = useState<number>(0);
  const [loadingMemories, setLoadingMemories] = useState<boolean>(false);
  const [newFactInput, setNewFactInput] = useState<string>('');
  const [filterQuery, setFilterQuery] = useState<string>('');
  const [isAddingFact, setIsAddingFact] = useState<boolean>(false);
  const [showClearConfirm, setShowClearConfirm] = useState<boolean>(false);
  const [isClearingMemory, setIsClearingMemory] = useState<boolean>(false);
  const [memoryMsg, setMemoryMsg] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    setLoadingMemories(true);
    try {
      const res = await getMemories('fact');
      setMemories(res.memories);
      setTotalMemories(res.total);
    } catch (err) {
      console.warn('Errore caricamento memorie:', err);
    } finally {
      setLoadingMemories(false);
    }
  }, []);

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

    fetchMemories();
  }, [isOpen, fetchMemories]);

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

  const handleAddFact = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFactInput.trim() || isAddingFact) return;
    setIsAddingFact(true);
    setMemoryMsg(null);
    try {
      await addMemory(newFactInput.trim(), 'fact');
      setNewFactInput('');
      setMemoryMsg('Fatto aggiunto con successo');
      await fetchMemories();
    } catch (err: any) {
      setMemoryMsg(`Errore aggiunta fatto: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsAddingFact(false);
      setTimeout(() => setMemoryMsg(null), 4000);
    }
  };

  const handleDeleteFact = async (id: number) => {
    try {
      await deleteMemory(id);
      await fetchMemories();
    } catch (err: any) {
      console.warn(`Errore eliminazione fatto ${id}:`, err);
    }
  };

  const handleClearAllMemory = async () => {
    setIsClearingMemory(true);
    setMemoryMsg(null);
    try {
      const res = await clearAllMemory();
      setMemoryMsg(res.message);
      setShowClearConfirm(false);
      await fetchMemories();
    } catch (err: any) {
      setMemoryMsg(`Errore cancellazione memoria: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setIsClearingMemory(false);
      setTimeout(() => setMemoryMsg(null), 5000);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-lg p-5 space-y-4 text-slate-200 max-h-[90vh] flex flex-col">
        {/* Header & Tabs */}
        <div className="flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-slate-200">
            <SettingsIcon size={16} className="text-blue-400" />
            <span className="font-semibold text-sm">Impostazioni & Memoria</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-500 hover:text-white hover:bg-slate-800 rounded transition"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 bg-slate-950 rounded-lg p-1 border border-slate-800 shrink-0">
          <button
            onClick={() => setActiveTab('general')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer ${
              activeTab === 'general' ? 'bg-slate-800 text-slate-100 shadow-sm' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Cpu size={13} />
            Generale & Modelli
          </button>
          <button
            onClick={() => {
              setActiveTab('memory');
              fetchMemories();
            }}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer ${
              activeTab === 'memory' ? 'bg-slate-800 text-purple-300 shadow-sm' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Brain size={13} className="text-purple-400" />
            Memoria Semantica ({totalMemories})
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-rose-950/70 border border-rose-800/80 rounded-lg p-2.5 text-xs text-rose-200 shrink-0">
            <AlertCircle size={14} className="text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {activeTab === 'general' ? (
            <>
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
            </>
          ) : (
            /* Memoria Semantica Tab */
            <div className="space-y-3.5">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span className="text-[11px]">
                  Fatti estratti e indicizzati nel Vector Store locale:
                </span>
                <button
                  type="button"
                  onClick={fetchMemories}
                  disabled={loadingMemories}
                  className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 disabled:opacity-50"
                  title="Ricarica memoria"
                >
                  <RefreshCw size={11} className={loadingMemories ? 'animate-spin' : ''} />
                  Aggiorna
                </button>
              </div>

              {memoryMsg && (
                <div className="bg-slate-950 border border-purple-800/60 rounded-lg p-2 text-xs text-purple-300">
                  {memoryMsg}
                </div>
              )}

              {/* Add manual fact form */}
              <form onSubmit={handleAddFact} className="flex gap-2">
                <input
                  type="text"
                  value={newFactInput}
                  onChange={(e) => setNewFactInput(e.target.value)}
                  placeholder="Insegna un fatto all'agente (es. 'Preferisco Debian 12')..."
                  className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-purple-500"
                />
                <button
                  type="submit"
                  disabled={!newFactInput.trim() || isAddingFact}
                  className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white rounded-lg text-xs font-semibold transition"
                >
                  {isAddingFact ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  Aggiungi
                </button>
              </form>

              {/* Filter search bar */}
              <div className="relative flex items-center">
                <Search size={12} className="absolute left-2.5 text-slate-500" />
                <input
                  type="text"
                  value={filterQuery}
                  onChange={(e) => setFilterQuery(e.target.value)}
                  placeholder="Filtra fatti per parola chiave (es. Debian, IP, LXC)..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-7 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-purple-500"
                />
              </div>

              {/* Memory List */}
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-2.5 max-h-56 overflow-y-auto space-y-2">
                {loadingMemories && memories.length === 0 ? (
                  <div className="flex items-center justify-center py-6 text-xs text-slate-500 gap-2">
                    <Loader2 size={14} className="animate-spin text-purple-400" />
                    Caricamento memorie...
                  </div>
                ) : memories.length === 0 ? (
                  <div className="text-center py-6 text-xs text-slate-500">
                    Nessun fatto memorizzato. L'agente estrae automaticamente preferenze e informazioni durante le chat.
                  </div>
                ) : memories.filter((m) => !filterQuery.trim() || m.content.toLowerCase().includes(filterQuery.toLowerCase())).length === 0 ? (
                  <div className="text-center py-4 text-xs text-slate-500 italic">
                    Nessun fatto corrisponde a "{filterQuery}".
                  </div>
                ) : (
                  memories
                    .filter((m) => !filterQuery.trim() || m.content.toLowerCase().includes(filterQuery.toLowerCase()))
                    .map((mem) => (
                    <div
                      key={mem.id}
                      className="group flex items-start justify-between gap-2 p-2 bg-slate-900/80 hover:bg-slate-900 border border-slate-800/80 rounded-lg text-xs transition"
                    >
                      <div className="flex-1 space-y-0.5">
                        <p className="text-slate-200 text-xs leading-relaxed">{mem.content}</p>
                        <div className="flex items-center gap-2 text-[10px] text-slate-500">
                          {mem.thread_id && <span>Thread: {mem.thread_id}</span>}
                          {mem.created_at && <span>• {new Date(mem.created_at).toLocaleString()}</span>}
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteFact(mem.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-400 rounded transition"
                        title="Elimina questo fatto"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))
                )}
              </div>

              {/* Danger Zone */}
              <div className="border-t border-slate-800/80 pt-3">
                {!showClearConfirm ? (
                  <button
                    type="button"
                    onClick={() => setShowClearConfirm(true)}
                    className="w-full flex items-center justify-center gap-1.5 px-3 py-2 bg-rose-950/30 hover:bg-rose-950/60 border border-rose-900/60 text-rose-300 rounded-lg text-xs font-medium transition cursor-pointer"
                  >
                    <Trash2 size={13} className="text-rose-400" />
                    Cancella Tutta la Memoria Semantica
                  </button>
                ) : (
                  <div className="bg-rose-950/80 border border-rose-700/80 rounded-xl p-3 space-y-2 text-xs text-rose-200">
                    <div className="flex items-center gap-1.5 font-semibold text-rose-300">
                      <AlertTriangle size={14} className="text-rose-400 shrink-0" />
                      Conferma azzeramento memoria
                    </div>
                    <p className="text-[11px] text-rose-200/90 leading-snug">
                      Verranno eliminati tutti i fatti memorizzati nel Vector Store, gli agenti su Letta (CT 102) e i riassunti locali. Questa azione è irreversibile.
                    </p>
                    <div className="flex gap-2 justify-end pt-1">
                      <button
                        type="button"
                        onClick={() => setShowClearConfirm(false)}
                        className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium"
                      >
                        Annulla
                      </button>
                      <button
                        type="button"
                        onClick={handleClearAllMemory}
                        disabled={isClearingMemory}
                        className="flex items-center gap-1 px-2.5 py-1 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold disabled:opacity-50"
                      >
                        {isClearingMemory && <Loader2 size={11} className="animate-spin" />}
                        Sì, cancella tutto
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Save button only on general tab */}
        {activeTab === 'general' && (
          <button
            onClick={handleSave}
            disabled={saving}
            className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-50 shrink-0 ${
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
        )}
      </div>
    </div>
  );
};
