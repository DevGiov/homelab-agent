import React from 'react';
import { Lock } from 'lucide-react';
import { describeTag, LABEL_NAMES, type SensitivityTag } from '../../utils/sensitivity';

/** Fascia sotto l'intestazione quando la conversazione ha dati interni o privati: perché, e cosa cambia. */
export const SensitivityBar: React.FC<{ tag: SensitivityTag }> = ({ tag }) => {
  if (tag.label === 'public') return null;
  const { reasons, untrusted } = describeTag(tag);
  const tone =
    tag.label === 'internal'
      ? 'bg-sky-950/60 border-sky-800/50 text-sky-200'
      : 'bg-amber-950/60 border-amber-800/50 text-amber-200';
  return (
    <div className={`border-b backdrop-blur-md px-3 sm:px-6 py-1.5 flex items-start gap-2 text-[11px] z-20 shrink-0 ${tone}`}
         data-testid="sensitivity-bar">
      <Lock size={13} className="shrink-0 mt-0.5" />
      <div className="min-w-0">
        <strong>Dati {LABEL_NAMES[tag.label].toLowerCase()} in questa conversazione</strong>
        {reasons.length > 0 && <span>: {reasons.join('; ')}</span>}.{' '}
        <span className="opacity-90">
          Ricerca web e servizi esterni chiedono conferma prima di ricevere qualcosa; la ricerca preventiva non parte.
        </span>
        {untrusted.length > 0 && (
          <span className="block opacity-80">
            L'ultimo turno ha letto contenuto non attendibile: le autorizzazioni "per questa chat" non valgono per le uscite di dati.
          </span>
        )}
      </div>
    </div>
  );
};
