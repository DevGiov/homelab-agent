import React from 'react';
import { RotateCcw } from 'lucide-react';
import type { ChannelSettingsPatch, SettingSource } from '../../../api/settings';
import { SOURCE_LABELS } from '../../../utils/providerKinds';
import { labelClass } from '../providers/providerStyles';

/** Esito di un salvataggio: `false` se l'utente ha annullato la conferma o la chiamata è fallita. */
export type ApplyPatch = (patch: ChannelSettingsPatch, success?: string) => Promise<boolean>;

interface FieldHeadProps {
  /** Il campo che l'etichetta nomina; senza, l'etichetta è solo un titolo (un gruppo di controlli). */
  htmlFor?: string;
  label: string;
  /** Chiave per i test: l'origine del valore sta in `origin-<testKey>`. */
  testKey: string;
  source: SettingSource;
  /** Toglie il valore della UI (manda `null`): il campo torna al `.env`. */
  onReset?: () => void;
  disabled?: boolean;
}

/** Etichetta di un campo con l'origine del suo valore e, se viene dalla UI, il pulsante per tornare al `.env`. */
export const FieldHead: React.FC<FieldHeadProps> = ({ htmlFor, label, testKey, source, onReset, disabled }) => (
  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
    {htmlFor ? (
      <label htmlFor={htmlFor} className={labelClass}>
        {label}
      </label>
    ) : (
      <span className={labelClass}>{label}</span>
    )}
    <span className="text-xs text-fg-muted" data-testid={`origin-${testKey}`}>
      ({SOURCE_LABELS[source]})
    </span>
    {source === 'ui' && onReset && (
      <button
        type="button"
        onClick={onReset}
        disabled={disabled}
        aria-label={`Riporta «${label}» al .env`}
        title="Toglie il valore della UI: il campo torna a quello del .env"
        className="flex items-center gap-1 px-1.5 py-0.5 rounded-md text-xs text-accent-text hover:bg-accent/10 cursor-pointer disabled:opacity-40"
      >
        <RotateCcw size={11} aria-hidden="true" />
        torna al .env
      </button>
    )}
  </div>
);
