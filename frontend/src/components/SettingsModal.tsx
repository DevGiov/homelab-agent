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
  Palette,
  Sparkles,
  Check,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Lock,
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
  listGrantedPermissions,
  revokePermission,
  revokeThreadPermissions,
  type ProviderInfo,
  type MemoryItem,
  type PermissionsListResponse,
} from '../api';
import { useTheme } from '../theme/ThemeContext';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProviderChanged?: () => void;
}

type SettingsTab = 'general' | 'appearance' | 'memory' | 'security';

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, onProviderChanged }) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [apiKey, setLocalApiKey] = useState(getApiKey());
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Theme state from Context
  const { theme, setTheme, isFrosted, setIsFrosted, hasGlow, setHasGlow, themes } = useTheme();

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

  const [permissionsData, setPermissionsData] = useState<PermissionsListResponse>({ always: [], session: {} });
  const [loadingPermissions, setLoadingPermissions] = useState<boolean>(false);
  const [securityMsg, setSecurityMsg] = useState<string | null>(null);

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

  const fetchPermissions = useCallback(async () => {
    setLoadingPermissions(true);
    try {
      const res = await listGrantedPermissions();
      setPermissionsData(res);
    } catch (err) {
      console.warn('Errore caricamento permessi:', err);
    } finally {
      setLoadingPermissions(false);
    }
  }, []);

  const handleRevokePermission = async (id: number) => {
    try {
      await revokePermission(id);
      setSecurityMsg('Permesso permanente revocato con successo.');
      setTimeout(() => setSecurityMsg(null), 3000);
      await fetchPermissions();
    } catch (err: any) {
      console.error('Errore revoca permesso:', err);
    }
  };

  const handleRevokeThreadPermissions = async (threadId: string) => {
    try {
      await revokeThreadPermissions(threadId);
      setSecurityMsg(`Permessi per il thread "${threadId}" revocati.`);
      setTimeout(() => setSecurityMsg(null), 3000);
      await fetchPermissions();
    } catch (err: any) {
      console.error('Errore revoca permessi thread:', err);
    }
  };

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
        if (mList.length > 0) {
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
      <div onClick={onClose} className="absolute inset-0 bg-bg/80 backdrop-blur-md transition-opacity" />

      {/* Modal */}
      <div className="relative glass-panel border border-border rounded-2xl shadow-2xl w-full max-w-lg p-5 space-y-4 text-fg max-h-[90vh] flex flex-col z-10">
        {/* Header & Tabs */}
        <div className="flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-fg">
            <SettingsIcon size={16} className="text-accent" />
            <span className="font-semibold text-sm">Impostazioni & Personalizzazione</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition cursor-pointer"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 bg-panel/80 rounded-xl p-1 border border-border shrink-0">
          <button
            onClick={() => setActiveTab('general')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'general' ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <Cpu size={13} />
            Generale
          </button>
          <button
            onClick={() => setActiveTab('appearance')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'appearance' ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <Palette size={13} />
            Aspetto & Temi
          </button>
          <button
            onClick={() => {
              setActiveTab('memory');
              fetchMemories();
            }}
            className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'memory' ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <Brain size={13} className={activeTab === 'memory' ? 'text-white' : 'text-purple-400'} />
            Memoria ({totalMemories})
          </button>
          <button
            onClick={() => {
              setActiveTab('security');
              fetchPermissions();
            }}
            className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
              activeTab === 'security' ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <Shield size={13} className={activeTab === 'security' ? 'text-white' : 'text-amber-400'} />
            Sicurezza
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-rose-950/70 border border-rose-800/80 rounded-xl p-2.5 text-xs text-rose-200 shrink-0">
            <AlertCircle size={14} className="text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto space-y-4 pr-1 custom-scrollbar">
          {activeTab === 'general' && (
            <>
              {/* API Key */}
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
                  className="w-full bg-input-bg border border-input-border rounded-xl px-3 py-2 text-xs font-mono text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent"
                />
                <p className="text-[10px] text-fg-muted leading-snug">
                  Salvata in localStorage e inviata automaticamente alle chiamate API.
                </p>
              </div>

              <div className="border-t border-border pt-3 space-y-3">
                {/* Provider Selection */}
                <div className="space-y-1.5">
                  <label className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                    <Cpu size={12} className="text-accent" />
                    Provider LLM
                    {loadingProviders && <Loader2 size={12} className="animate-spin text-accent ml-1" />}
                  </label>
                  <select
                    value={selectedProvider}
                    onChange={(e) => handleProviderChange(e.target.value)}
                    disabled={loadingProviders || providers.length === 0}
                    className="w-full bg-input-bg border border-input-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent disabled:opacity-50 capitalize"
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

                {/* Model Selection */}
                <div className="space-y-1.5">
                  <label className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                    <Box size={12} className="text-emerald-400" />
                    Modello di Default
                    {loadingModels && <Loader2 size={12} className="animate-spin text-emerald-400 ml-1" />}
                  </label>
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    disabled={loadingModels || models.length === 0}
                    className="w-full bg-input-bg border border-input-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent disabled:opacity-50 font-mono"
                  >
                    {models.map((m) => (
                      <option key={m} value={m} className="bg-panel text-fg">
                        {m}
                      </option>
                    ))}
                    {models.length === 0 && !loadingModels && (
                      <option value="" className="bg-panel text-fg">Nessun modello trovato</option>
                    )}
                  </select>
                  <p className="text-[10px] text-fg-muted leading-snug">
                    Imposta il modello predefinito usato dall'agente se non sovrascritto in chat.
                  </p>
                </div>
              </div>
            </>
          )}

          {activeTab === 'appearance' && (
            <div className="space-y-4">
              {/* Theme Grid */}
              <div className="space-y-2">
                <label className="text-xs font-medium text-fg flex items-center gap-1.5">
                  <Palette size={13} className="text-accent" />
                  Tema Interfaccia
                </label>
                <div className="grid grid-cols-2 gap-2.5">
                  {themes.map((t) => {
                    const isActive = theme === t.id;
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setTheme(t.id)}
                        className={`flex flex-col gap-2 p-3 rounded-xl text-left transition-all duration-200 cursor-pointer border ${
                          isActive
                            ? 'border-accent bg-accent/10 shadow-md shadow-accent/15 ring-1 ring-accent/50'
                            : 'glass-card border-border/60 hover:border-border hover:bg-panel-header/50'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          {/* 4-Color Swatch Strip */}
                          <div className="flex items-center h-3.5 w-20 rounded-full overflow-hidden border border-border shadow-inner">
                            <span className="h-full flex-1" style={{ backgroundColor: t.swatch[0] }} />
                            <span className="h-full flex-1" style={{ backgroundColor: t.swatch[1] }} />
                            <span className="h-full flex-1" style={{ backgroundColor: t.swatch[2] }} />
                            <span className="h-full flex-1" style={{ backgroundColor: t.swatch[3] }} />
                          </div>
                          {isActive && <Check size={14} className="text-accent shrink-0" />}
                        </div>
                        <div>
                          <div className="text-xs font-semibold text-fg">{t.name}</div>
                          <div className="text-[10px] text-fg-muted line-clamp-1">{t.description}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Glassmorphism & Effects Controls */}
              <div className="space-y-2.5 pt-2 border-t border-border">
                <label className="text-xs font-medium text-fg flex items-center gap-1.5">
                  <Sparkles size={13} className="text-accent" />
                  Effetti Visivi & Glassmorphism
                </label>

                {/* Frosted Glass Switch */}
                <div className="flex items-center justify-between p-3 rounded-xl glass-card border border-border">
                  <div className="flex flex-col pr-4">
                    <span className="text-xs font-medium text-fg">Frosted Glass (Trasparenze)</span>
                    <span className="text-[11px] text-fg-muted">
                      Applica sfocatura dinamica (blur) e trasparenze a pannelli, sidebar, header e modali.
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsFrosted(!isFrosted)}
                    className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer shrink-0 ${
                      isFrosted ? 'bg-accent' : 'bg-border'
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white transition-transform duration-200 absolute top-1 left-1 shadow-sm ${
                        isFrosted ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Ambient Glow Switch */}
                <div className="flex items-center justify-between p-3 rounded-xl glass-card border border-border">
                  <div className="flex flex-col pr-4">
                    <span className="text-xs font-medium text-fg">Ambient Glow (Bagliore di Sfondo)</span>
                    <span className="text-[11px] text-fg-muted">
                      Attiva orbi luminosi fluttuanti coordinati al tema che traspaiono attraverso il vetro.
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setHasGlow(!hasGlow)}
                    className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer shrink-0 ${
                      hasGlow ? 'bg-accent' : 'bg-border'
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white transition-transform duration-200 absolute top-1 left-1 shadow-sm ${
                        hasGlow ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'memory' && (
            /* Memoria Semantica Tab */
            <div className="space-y-3.5">
              <div className="flex items-center justify-between text-xs text-fg-muted">
                <span className="text-[11px]">
                  Fatti estratti e indicizzati nel Vector Store locale:
                </span>
                <button
                  type="button"
                  onClick={fetchMemories}
                  disabled={loadingMemories}
                  className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover disabled:opacity-50 cursor-pointer"
                  title="Ricarica memoria"
                >
                  <RefreshCw size={11} className={loadingMemories ? 'animate-spin' : ''} />
                  Aggiorna
                </button>
              </div>

              {memoryMsg && (
                <div className="bg-panel border border-accent/40 rounded-xl p-2.5 text-xs text-accent">
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
                  className="flex-1 bg-input-bg border border-input-border rounded-xl px-3 py-1.5 text-xs text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent"
                />
                <button
                  type="submit"
                  disabled={!newFactInput.trim() || isAddingFact}
                  className="flex items-center gap-1 px-3 py-1.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition cursor-pointer shadow-md shadow-accent/20"
                >
                  {isAddingFact ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  Aggiungi
                </button>
              </form>

              {/* Filter search bar */}
              <div className="relative flex items-center">
                <Search size={12} className="absolute left-2.5 text-fg-muted" />
                <input
                  type="text"
                  value={filterQuery}
                  onChange={(e) => setFilterQuery(e.target.value)}
                  placeholder="Filtra fatti per parola chiave (es. Debian, IP, LXC)..."
                  className="w-full bg-input-bg border border-input-border rounded-xl pl-7 pr-3 py-1.5 text-xs text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent"
                />
              </div>

              {/* Memory List */}
              <div className="bg-panel border border-border rounded-xl p-2.5 max-h-56 overflow-y-auto space-y-2 custom-scrollbar">
                {loadingMemories && memories.length === 0 ? (
                  <div className="flex items-center justify-center py-6 text-xs text-fg-muted gap-2">
                    <Loader2 size={14} className="animate-spin text-accent" />
                    Caricamento memorie...
                  </div>
                ) : memories.length === 0 ? (
                  <div className="text-center py-6 text-xs text-fg-muted">
                    Nessun fatto memorizzato. L'agente estrae automaticamente preferenze e informazioni durante le chat.
                  </div>
                ) : memories.filter((m) => !filterQuery.trim() || m.content.toLowerCase().includes(filterQuery.toLowerCase())).length === 0 ? (
                  <div className="text-center py-4 text-xs text-fg-muted italic">
                    Nessun fatto corrisponde a "{filterQuery}".
                  </div>
                ) : (
                  memories
                    .filter((m) => !filterQuery.trim() || m.content.toLowerCase().includes(filterQuery.toLowerCase()))
                    .map((mem) => (
                    <div
                      key={mem.id}
                      className="group flex items-start justify-between gap-2 p-2 bg-panel-header/50 hover:bg-panel-header border border-border rounded-lg text-xs transition"
                    >
                      <div className="flex-1 space-y-0.5">
                        <p className="text-fg text-xs leading-relaxed">{mem.content}</p>
                        <div className="flex items-center gap-2 text-[10px] text-fg-muted">
                          {mem.thread_id && <span>Thread: {mem.thread_id}</span>}
                          {mem.created_at && <span>• {new Date(mem.created_at).toLocaleString()}</span>}
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteFact(mem.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-fg-muted hover:text-rose-400 rounded transition cursor-pointer"
                        title="Elimina questo fatto"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))
                )}
              </div>

              {/* Danger Zone */}
              <div className="border-t border-border pt-3">
                {!showClearConfirm ? (
                  <button
                    type="button"
                    onClick={() => setShowClearConfirm(true)}
                    className="w-full flex items-center justify-center gap-1.5 px-3 py-2 bg-rose-950/30 hover:bg-rose-950/60 border border-rose-900/60 text-rose-300 rounded-xl text-xs font-medium transition cursor-pointer"
                  >
                    <Trash2 size={13} className="text-rose-400" />
                    Cancella Tutta la Memoria Semantica
                  </button>
                ) : (
                  <div className="bg-rose-950/85 border border-rose-700/80 rounded-xl p-3 space-y-2 text-xs text-rose-200 backdrop-blur-md">
                    <div className="flex items-center gap-1.5 font-semibold text-rose-300">
                      <AlertTriangle size={14} className="text-rose-400 shrink-0" />
                      Conferma azzeramento memoria
                    </div>
                    <p className="text-[11px] text-rose-200/90 leading-snug">
                      Verranno eliminati tutti i fatti memorizzati nel Vector Store, gli agenti su Letta e i riassunti locali. Questa azione è irreversibile.
                    </p>
                    <div className="flex gap-2 justify-end pt-1">
                      <button
                        type="button"
                        onClick={() => setShowClearConfirm(false)}
                        className="px-2.5 py-1 bg-panel hover:bg-panel-header text-fg-muted hover:text-fg rounded-lg text-xs font-medium cursor-pointer"
                      >
                        Annulla
                      </button>
                      <button
                        type="button"
                        onClick={handleClearAllMemory}
                        disabled={isClearingMemory}
                        className="flex items-center gap-1 px-2.5 py-1 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold disabled:opacity-50 cursor-pointer"
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

          {/* TAB: Security & Tool Permissions */}
          {activeTab === 'security' && (
            <div className="space-y-4 overflow-y-auto pr-1 flex-1">
              {securityMsg && (
                <div className="flex items-center gap-2 bg-emerald-950/70 border border-emerald-800/80 rounded-xl p-2.5 text-xs text-emerald-200">
                  <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
                  <span>{securityMsg}</span>
                </div>
              )}

              {/* Tier 1: Guardrail Automatici */}
              <div className="bg-panel/70 border border-border rounded-xl p-3.5 space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldAlert size={15} className="text-rose-400" />
                    <h4 className="text-xs font-semibold text-fg">
                      Tier 1: Guardrail Deterministici (Automatici)
                    </h4>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                    Attivo & Inviolabile
                  </span>
                </div>
                <p className="text-[11px] text-fg-muted leading-relaxed">
                  Questi comandi distruttivi sono <strong>categoricamente bloccati</strong> prima dell'esecuzione.
                  Nessun prompt, modalità o parametro (incluso <code>confirm=true</code> simulato dal modello) può scavalcare questo blocco.
                </p>
                <div className="grid grid-cols-1 gap-1.5 pt-1 text-[10px] text-fg-muted">
                  <div className="flex items-center gap-1.5 p-1.5 rounded-lg bg-black/30 border border-border/60">
                    <Lock size={11} className="text-rose-400 shrink-0" />
                    <span>Wipe ricorsivo root/sistema (<code>rm -rf /</code>, <code>rm -rf /etc</code>, <code>~</code>, ecc.)</span>
                  </div>
                  <div className="flex items-center gap-1.5 p-1.5 rounded-lg bg-black/30 border border-border/60">
                    <Lock size={11} className="text-rose-400 shrink-0" />
                    <span>Formattazione dischi & firme filesystem (<code>mkfs</code>, <code>wipefs</code>)</span>
                  </div>
                  <div className="flex items-center gap-1.5 p-1.5 rounded-lg bg-black/30 border border-border/60">
                    <Lock size={11} className="text-rose-400 shrink-0" />
                    <span>Scrittura grezza su blocchi disco (<code>dd of=/dev/sd*</code>, <code>&gt; /dev/nvme*</code>)</span>
                  </div>
                  <div className="flex items-center gap-1.5 p-1.5 rounded-lg bg-black/30 border border-border/60">
                    <Lock size={11} className="text-rose-400 shrink-0" />
                    <span>Fork bomb, DoS di sistema e manomissione credenziali (<code>/etc/shadow</code>)</span>
                  </div>
                  <div className="flex items-center gap-1.5 p-1.5 rounded-lg bg-black/30 border border-border/60">
                    <Lock size={11} className="text-rose-400 shrink-0" />
                    <span>Download ed esecuzione arbitraria pipe-to-shell (<code>curl ... | sh</code>, <code>base64 -d | sh</code>)</span>
                  </div>
                </div>
              </div>

              {/* Tier 2: Permessi Accordati */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={15} className="text-emerald-400" />
                    <h4 className="text-xs font-semibold text-fg">
                      Tier 2: Permessi Tool Accordati (Human-in-the-Loop)
                    </h4>
                  </div>
                  <button
                    onClick={fetchPermissions}
                    disabled={loadingPermissions}
                    className="p-1 text-fg-muted hover:text-fg transition rounded cursor-pointer"
                    title="Aggiorna permessi"
                  >
                    <RefreshCw size={12} className={loadingPermissions ? 'animate-spin' : ''} />
                  </button>
                </div>

                {/* Always Permissions List */}
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider">
                    Permessi Permanenti (Always)
                  </div>
                  {loadingPermissions ? (
                    <div className="flex items-center justify-center p-4 text-xs text-fg-muted">
                      <Loader2 size={14} className="animate-spin mr-2" />
                      Caricamento permessi...
                    </div>
                  ) : permissionsData.always.length === 0 ? (
                    <div className="p-3 rounded-xl border border-border bg-panel/40 text-center text-xs text-fg-muted">
                      Nessun permesso permanente memorizzato. I tool ad alto rischio richiederanno sempre autorizzazione.
                    </div>
                  ) : (
                    permissionsData.always.map((perm) => (
                      <div
                        key={perm.id}
                        className="flex items-center justify-between gap-2 p-2.5 rounded-xl border border-border bg-panel/80 hover:border-accent/40 transition"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-emerald-300">
                              {perm.tool_name}
                            </span>
                            {perm.command_prefix && (
                              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/40 border border-border text-fg-muted">
                                prefisso: {perm.command_prefix}
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-fg-muted mt-0.5">
                            Scope: sempre · ID: #{perm.id} {perm.created_by ? `· da: ${perm.created_by}` : ''}
                          </div>
                        </div>
                        <button
                          onClick={() => handleRevokePermission(perm.id)}
                          className="p-1.5 text-rose-400 hover:text-rose-200 hover:bg-rose-950/40 rounded-lg transition cursor-pointer"
                          title="Revoca permesso permanente"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    ))
                  )}
                </div>

                {/* Session / Thread Permissions List */}
                {Object.keys(permissionsData.session).length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-border">
                    <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider">
                      Permessi di Sessione (Questa Chat)
                    </div>
                    {Object.entries(permissionsData.session).map(([tId, tools]) => (
                      <div
                        key={tId}
                        className="flex items-center justify-between gap-2 p-2.5 rounded-xl border border-sky-500/20 bg-sky-950/10"
                      >
                        <div className="min-w-0">
                          <div className="text-[11px] font-mono font-medium text-sky-300 truncate">
                            Thread: {tId}
                          </div>
                          <div className="text-[10px] text-fg-muted mt-0.5">
                            Tool consentiti: {tools.join(', ')}
                          </div>
                        </div>
                        <button
                          onClick={() => handleRevokeThreadPermissions(tId)}
                          className="p-1.5 text-rose-400 hover:text-rose-200 hover:bg-rose-950/40 rounded-lg transition cursor-pointer"
                          title="Revoca permessi per questo thread"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    ))}
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
            className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition cursor-pointer disabled:opacity-50 shrink-0 ${
              saved
                ? 'bg-emerald-600/30 border border-emerald-500/50 text-emerald-300'
                : 'bg-accent hover:bg-accent-hover text-white shadow-lg shadow-accent/25'
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
