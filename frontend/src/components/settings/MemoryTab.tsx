import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { addMemory, clearAllMemory, deleteMemory, getMemories, type MemoryItem } from '../../api/memory';
import { formatApiError } from '../../utils/error';

/** Fatti della memoria semantica: elenco filtrabile, aggiunta manuale e azzeramento. */
export const MemoryTab: React.FC<{ onTotalChange: (total: number) => void }> = ({ onTotalChange }) => {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [newFact, setNewFact] = useState('');
  const [filter, setFilter] = useState('');
  const [isAdding, setIsAdding] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getMemories('fact');
      setMemories(res.memories);
      onTotalChange(res.total);
    } catch (err) {
      console.warn('Errore caricamento memorie:', err);
    } finally {
      setLoading(false);
    }
  }, [onTotalChange]);

  useEffect(() => {
    load();
  }, [load]);

  const flash = (text: string, ms: number) => {
    setMessage(text);
    setTimeout(() => setMessage(null), ms);
  };

  const addFact = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFact.trim() || isAdding) return;
    setIsAdding(true);
    try {
      await addMemory(newFact.trim(), 'fact');
      setNewFact('');
      flash('Fatto aggiunto con successo', 4000);
      await load();
    } catch (err) {
      flash(`Errore aggiunta fatto: ${formatApiError(err)}`, 4000);
    } finally {
      setIsAdding(false);
    }
  };

  const removeFact = async (id: number) => {
    try {
      await deleteMemory(id);
      await load();
    } catch (err) {
      console.warn(`Errore eliminazione fatto ${id}:`, err);
    }
  };

  const clearAll = async () => {
    setIsClearing(true);
    try {
      const res = await clearAllMemory();
      flash(res.message, 5000);
      setConfirmClear(false);
      await load();
    } catch (err) {
      flash(`Errore cancellazione memoria: ${formatApiError(err)}`, 5000);
    } finally {
      setIsClearing(false);
    }
  };

  const query = filter.trim().toLowerCase();
  const visible = query ? memories.filter((m) => m.content.toLowerCase().includes(query)) : memories;

  return (
    <div className="space-y-3.5">
      <div className="flex items-center justify-between text-xs text-fg-muted">
        <span className="text-[11px]">Fatti estratti e indicizzati nel Vector Store locale:</span>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover disabled:opacity-50 cursor-pointer"
          title="Ricarica memoria"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          Aggiorna
        </button>
      </div>

      {message && <div className="bg-panel border border-accent/40 rounded-xl p-2.5 text-xs text-accent">{message}</div>}

      <form onSubmit={addFact} className="flex gap-2">
        <input
          type="text"
          value={newFact}
          onChange={(e) => setNewFact(e.target.value)}
          placeholder="Insegna un fatto all'agente (es. 'Preferisco Debian 12')..."
          className="flex-1 bg-input-bg border border-input-border rounded-xl px-3 py-1.5 text-xs text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={!newFact.trim() || isAdding}
          className="flex items-center gap-1 px-3 py-1.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition cursor-pointer shadow-md shadow-accent/20"
        >
          {isAdding ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
          Aggiungi
        </button>
      </form>

      <div className="relative flex items-center">
        <Search size={12} className="absolute left-2.5 text-fg-muted" />
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filtra fatti per parola chiave (es. Debian, IP, LXC)..."
          className="w-full bg-input-bg border border-input-border rounded-xl pl-7 pr-3 py-1.5 text-xs text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent"
        />
      </div>

      <div className="bg-panel border border-border rounded-xl p-2.5 max-h-56 overflow-y-auto space-y-2 custom-scrollbar">
        {loading && memories.length === 0 ? (
          <div className="flex items-center justify-center py-6 text-xs text-fg-muted gap-2">
            <Loader2 size={14} className="animate-spin text-accent" />
            Caricamento memorie...
          </div>
        ) : memories.length === 0 ? (
          <div className="text-center py-6 text-xs text-fg-muted">
            Nessun fatto memorizzato. L'agente estrae automaticamente preferenze e informazioni durante le chat.
          </div>
        ) : visible.length === 0 ? (
          <div className="text-center py-4 text-xs text-fg-muted italic">Nessun fatto corrisponde a "{filter}".</div>
        ) : (
          visible.map((mem) => (
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
                onClick={() => removeFact(mem.id)}
                className="opacity-0 group-hover:opacity-100 p-1 text-fg-muted hover:text-rose-400 rounded transition cursor-pointer"
                title="Elimina questo fatto"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="border-t border-border pt-3">
        {!confirmClear ? (
          <button
            type="button"
            onClick={() => setConfirmClear(true)}
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
              Verranno eliminati tutti i fatti memorizzati nel Vector Store, gli agenti su Letta e i riassunti locali. Questa azione è
              irreversibile.
            </p>
            <div className="flex gap-2 justify-end pt-1">
              <button
                type="button"
                onClick={() => setConfirmClear(false)}
                className="px-2.5 py-1 bg-panel hover:bg-panel-header text-fg-muted hover:text-fg rounded-lg text-xs font-medium cursor-pointer"
              >
                Annulla
              </button>
              <button
                type="button"
                onClick={clearAll}
                disabled={isClearing}
                className="flex items-center gap-1 px-2.5 py-1 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold disabled:opacity-50 cursor-pointer"
              >
                {isClearing && <Loader2 size={11} className="animate-spin" />}
                Sì, cancella tutto
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
