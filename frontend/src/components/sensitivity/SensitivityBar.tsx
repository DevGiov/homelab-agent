import React, { useId, useState } from 'react';
import { AlertTriangle, Lock, X } from 'lucide-react';
import {
  compareLabels,
  describeTag,
  LABEL_CHIPS,
  LABEL_NAMES,
  type SensitivityLevel,
  type SensitivityTag,
} from '../../utils/sensitivity';

const TONES: Record<'internal' | 'private' | 'secret', string> = {
  internal: 'bg-sky-950/60 border-sky-800/50 text-sky-200',
  private: 'bg-amber-950/60 border-amber-800/50 text-amber-200',
  secret: 'bg-rose-950/60 border-rose-800/50 text-rose-200',
};

interface SensitivityBarProps {
  tag: SensitivityTag;
  /** Livello scelto per la conversazione: se quello effettivo è più alto, i dettagli lo spiegano. */
  chosen?: SensitivityLevel;
  /** Nasconde la fascia (resta la chip nell'intestazione). */
  onHide?: () => void;
}

/**
 * Riga sotto l'intestazione quando la conversazione ha dati interni o più riservati: il livello e i motivi su una riga,
 * cosa cambia nei dettagli.
 */
export const SensitivityBar: React.FC<SensitivityBarProps> = ({ tag, chosen, onHide }) => {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  if (tag.label === 'public') return null;
  const { reasons, untrusted } = describeTag(tag);
  const name = LABEL_NAMES[tag.label].toLowerCase();
  const raised = chosen !== undefined && compareLabels(tag.label, chosen) > 0;

  return (
    <div className={`border-b backdrop-blur-md px-3 sm:px-6 text-xs z-20 shrink-0 ${TONES[tag.label]}`} data-testid="sensitivity-bar">
      <div className="flex items-center gap-2 min-h-8 py-1">
        <Lock size={13} className="shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1 truncate">
          <strong>Dati {name}</strong>
          {reasons.length > 0 && <span className="opacity-80"> · {reasons.join(', ')}</span>}
        </p>
        {untrusted.length > 0 && (
          <span className="shrink-0 rounded-full border border-current px-1.5 text-[11px] opacity-80">non attendibile</span>
        )}
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-controls={detailsId}
          className="shrink-0 rounded px-1.5 py-0.5 underline-offset-2 hover:underline cursor-pointer"
        >
          {expanded ? 'Meno' : 'Dettagli'}
        </button>
        {onHide && (
          <button
            type="button"
            onClick={onHide}
            aria-label="Nascondi l'avviso"
            title="Nascondi: resta l'icona nell'intestazione. Ricompare se il livello sale."
            className="shrink-0 rounded p-1 opacity-80 hover:opacity-100 hover:bg-white/10 cursor-pointer"
          >
            <X size={14} aria-hidden="true" />
          </button>
        )}
      </div>
      {expanded && (
        <div id={detailsId} className="pb-2 pl-5 space-y-1 opacity-90">
          {reasons.length > 0 && <p>Perché: {reasons.join('; ')}.</p>}
          {raised && (
            <p>
              Livello scelto per la conversazione: {LABEL_NAMES[chosen].toLowerCase()}. Questi dati lo portano a {name}.
            </p>
          )}
          <p>Ricerca web e servizi esterni chiedono conferma prima di ricevere qualcosa; la ricerca preventiva non parte.</p>
          {untrusted.length > 0 && (
            <p>
              L'ultimo turno ha letto contenuto non attendibile ({untrusted.map((u) => u.replace(/^contenuto non attendibile: /, '')).join('; ')}):
              le autorizzazioni "per questa chat" non valgono per le uscite di dati.
            </p>
          )}
        </div>
      )}
    </div>
  );
};

/** Chip nell'intestazione quando la fascia è nascosta: il livello a colpo d'occhio, e un clic la riapre. */
export const SensitivityHeaderChip: React.FC<{ tag: SensitivityTag; onShow: () => void }> = ({ tag, onShow }) => {
  if (tag.label === 'public') return null;
  const name = LABEL_NAMES[tag.label];
  return (
    <button
      type="button"
      onClick={onShow}
      aria-label={`Dati ${name.toLowerCase()}${tag.untrusted ? ', contenuto non attendibile' : ''}: mostra l'avviso`}
      title="Mostra l'avviso sui dati di questa conversazione"
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium shrink-0 cursor-pointer ${LABEL_CHIPS[tag.label]}`}
      data-testid="sensitivity-header-chip"
    >
      <Lock size={11} aria-hidden="true" />
      {name}
      {tag.untrusted && <AlertTriangle size={10} aria-hidden="true" />}
    </button>
  );
};
