import React, { useEffect, useState } from 'react';
import { Loader2, Pencil, UserRound } from 'lucide-react';
import { PROFILE_MAX_CHARS, getProfile, updateProfile } from '../../api/memory';
import type { Notify } from '../../hooks/useFeedback';

/** Profilo dell'utente: testo libero che l'agente legge all'inizio di ogni turno, in tutte le modalità. */
export const ProfileCard: React.FC<{ notify: Notify }> = ({ notify }) => {
  const [content, setContent] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    getProfile()
      .then((p) => setContent(p.content))
      .catch(() => setContent(''));
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const saved = await updateProfile(draft);
      setContent(saved.content);
      setIsEditing(false);
      notify('success', 'Profilo salvato');
    } catch (err) {
      notify('error', `Profilo non salvato: ${err instanceof Error ? err.message : err}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="rounded-xl border border-border bg-panel/60 p-3 space-y-2" aria-label="Profilo dell'utente">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-xs font-semibold text-fg">
          <UserRound size={13} className="text-accent" /> Profilo
        </h2>
        {!isEditing && content !== null && (
          <button
            onClick={() => {
              setDraft(content);
              setIsEditing(true);
            }}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer"
          >
            <Pencil size={11} /> Modifica
          </button>
        )}
      </div>
      {isEditing ? (
        <form onSubmit={save} className="space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={5}
            maxLength={PROFILE_MAX_CHARS}
            placeholder={"Chi sei e come lavori: nome, lingua, preferenze, convenzioni dell'homelab (es. 'Uso Debian 12 per i nuovi container')"}
            className="w-full resize-y leading-relaxed bg-input-bg border border-input-border rounded-lg px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent"
            aria-label="Testo del profilo"
            autoFocus
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-fg-muted">
              {draft.length}/{PROFILE_MAX_CHARS}
            </span>
            <div className="flex gap-1.5">
              <button type="button" onClick={() => setIsEditing(false)} className="px-3 py-1 rounded-lg text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
                Annulla
              </button>
              <button type="submit" disabled={isSaving} className="px-3 py-1 rounded-lg bg-accent text-white text-xs font-semibold disabled:opacity-40 flex items-center gap-1 cursor-pointer">
                {isSaving && <Loader2 size={12} className="animate-spin" />}
                Salva
              </button>
            </div>
          </div>
        </form>
      ) : content ? (
        <p className="text-xs text-fg whitespace-pre-wrap leading-relaxed">{content}</p>
      ) : (
        <p className="text-[11px] text-fg-muted">
          {content === null ? 'Caricamento…' : "Nessun profilo. Quello che scrivi qui l'agente lo legge a ogni turno, in tutte le modalità."}
        </p>
      )}
    </section>
  );
};
