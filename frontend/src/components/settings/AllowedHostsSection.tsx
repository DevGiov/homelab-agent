import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Globe, Loader2, Plus, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import {
  addAllowedHost,
  listAllowedHosts,
  removeAllowedHost,
  restoreDefaultHosts,
  type AllowedHost,
  type HostOrigin,
} from '../../api/security';
import { ConfirmDialog, type ConfirmRequest } from '../ConfirmDialog';
import { formatApiError } from '../../utils/error';

const ORIGIN_LABELS: Record<HostOrigin, string> = {
  default: 'predefinito',
  user: 'aggiunto da te',
  approval: 'da un\'approvazione',
};

const ORIGIN_BADGES: Record<HostOrigin, string> = {
  default: 'bg-bg/60 border-border text-fg-muted',
  user: 'bg-accent/15 border-accent/30 text-accent',
  approval: 'bg-sky-500/15 border-sky-500/30 text-sky-300',
};

export const AllowedHostsSection: React.FC = () => {
  const [hosts, setHosts] = useState<AllowedHost[]>([]);
  const [defaults, setDefaults] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [newHost, setNewHost] = useState('');
  const [newNote, setNewNote] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState<ConfirmRequest | null>(null);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAllowedHosts();
      setHosts(data.hosts || []);
      setDefaults(data.defaults || []);
    } catch (err) {
      console.warn('Errore caricamento host ammessi:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedHost = newHost.trim();
    if (!trimmedHost) return;

    setIsSubmitting(true);
    setAddError(null);
    try {
      const added = await addAllowedHost(trimmedHost, newNote.trim());
      setHosts((prev) => {
        const idx = prev.findIndex((h) => h.host === added.host);
        if (idx >= 0) {
          const copy = [...prev];
          copy[idx] = added;
          return copy;
        }
        return [...prev, added];
      });
      setNewHost('');
      setNewNote('');
      flash(`Host "${added.host}" aggiunto agli ammessi.`);
    } catch (err) {
      setAddError(formatApiError(err, 'Errore durante l\'aggiunta dell\'host'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemove = async (hostToRemove: string) => {
    try {
      await removeAllowedHost(hostToRemove);
      setHosts((prev) => prev.filter((h) => h.host !== hostToRemove));
      flash(`Host "${hostToRemove}" rimosso dagli ammessi.`);
    } catch (err) {
      console.error('Errore rimozione host:', err);
    }
  };

  const hasMissingDefaults = defaults.some((d) => !hosts.some((h) => h.host === d));

  return (
    <div className="bg-panel/70 border border-border rounded-xl p-3.5 space-y-3">
      {message && (
        <div className="flex items-center gap-2 bg-emerald-950/70 border border-emerald-800/80 rounded-xl p-2.5 text-xs text-emerald-200">
          <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe size={15} className="text-accent" />
          <h4 className="text-xs font-semibold text-fg">Host ammessi per le richieste web</h4>
        </div>
        <div className="flex items-center gap-1.5">
          {hasMissingDefaults && (
            <button
              onClick={() =>
                setConfirmRestore({
                  message: 'Ripristinare gli host predefiniti mancanti nella configurazione?',
                  confirmLabel: 'Ripristina',
                })
              }
              className="px-2 py-1 text-[11px] rounded-lg border border-border bg-bg/60 text-fg-muted hover:text-fg hover:border-accent/40 transition cursor-pointer flex items-center gap-1.5"
              title="Ripristina gli host predefiniti mancanti"
            >
              <RotateCcw size={11} />
              <span>Ripristina predefiniti</span>
            </button>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="p-1 text-fg-muted hover:text-fg transition rounded cursor-pointer"
            title="Aggiorna host ammessi"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <p className="text-[11px] text-fg-muted leading-relaxed">
        I tool <code>http_get</code> e <code>inspect_image</code> possono contattare direttamente gli host in questa lista senza chiedere conferma.
        Un host pubblico fuori lista richiede l'approvazione dell'utente, mentre un host della rete locale fuori lista viene bloccato categoricamente.
        Il formato <code>*.dominio</code> include sia il dominio che tutti i suoi sottodomini.
        L'indirizzo web può comunque contenere dati o parametri della conversazione: inserisci solo servizi di cui ti fidi.
      </p>

      {/* Elenco host */}
      <div className="space-y-2">
        {loading ? (
          <div className="flex items-center justify-center p-4 text-xs text-fg-muted">
            <Loader2 size={14} className="animate-spin mr-2 text-accent" />
            Caricamento host ammessi...
          </div>
        ) : hosts.length === 0 ? (
          <div className="p-3 rounded-xl border border-border bg-panel/40 text-center text-xs text-fg-muted">
            Nessun host ammesso configurato. Le richieste web verso host pubblici richiederanno sempre approvazione.
          </div>
        ) : (
          <div className="space-y-1.5 max-h-72 overflow-y-auto pr-0.5">
            {hosts.map((item) => (
              <div
                key={item.host}
                className="flex items-center justify-between gap-2 p-2.5 rounded-xl border border-border bg-panel/80 hover:border-accent/40 transition"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs font-semibold text-fg">{item.host}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${
                        ORIGIN_BADGES[item.origin] || 'bg-bg/60 border-border text-fg-muted'
                      }`}
                    >
                      {ORIGIN_LABELS[item.origin] || item.origin}
                    </span>
                  </div>
                  {item.note && (
                    <div className="text-[11px] text-fg-muted mt-0.5 truncate">{item.note}</div>
                  )}
                </div>
                <button
                  onClick={() => handleRemove(item.host)}
                  className="p-1.5 text-rose-400 hover:text-rose-200 hover:bg-rose-950/40 rounded-lg transition cursor-pointer shrink-0"
                  title="Rimuovi host dagli ammessi"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modulo per aggiungere host e nota */}
      <form onSubmit={handleAdd} className="space-y-2 pt-2 border-t border-border/60">
        <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider">Aggiungi host</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div>
            <input
              type="text"
              placeholder="Host (es. api.example.com o *.example.com)"
              value={newHost}
              onChange={(e) => {
                setNewHost(e.target.value);
                setAddError(null);
              }}
              className="w-full bg-bg/60 border border-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <input
              type="text"
              placeholder="Nota opzionale"
              value={newNote}
              onChange={(e) => setNewNote(e.target.value)}
              className="w-full bg-bg/60 border border-border rounded-lg px-2.5 py-1.5 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent"
            />
          </div>
        </div>

        {addError && (
          <div className="text-[11px] text-rose-400 flex items-center gap-1.5">
            <AlertTriangle size={12} className="shrink-0" />
            <span>{addError}</span>
          </div>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={isSubmitting || !newHost.trim()}
            className="px-3 py-1.5 rounded-lg bg-accent text-accent-contrast font-semibold text-xs hover:bg-accent/90 disabled:opacity-50 transition cursor-pointer flex items-center gap-1.5"
          >
            {isSubmitting ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            <span>Aggiungi host</span>
          </button>
        </div>
      </form>

      <ConfirmDialog
        request={confirmRestore}
        onAnswer={async (confirmed) => {
          setConfirmRestore(null);
          if (!confirmed) return;
          try {
            const res = await restoreDefaultHosts();
            setHosts(res.hosts);
            flash(
              res.added === 1
                ? 'Ripristinato 1 host predefinito.'
                : `Ripristinati ${res.added} host predefiniti.`
            );
          } catch (err) {
            flash(formatApiError(err, 'Errore durante il ripristino dei predefiniti'));
          }
        }}
      />
    </div>
  );
};
