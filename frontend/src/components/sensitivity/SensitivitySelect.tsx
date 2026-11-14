import React from 'react';
import { Lock } from 'lucide-react';
import { LABEL_CHIPS, LABEL_HINTS, LABEL_NAMES, LEVELS, type SensitivityLevel } from '../../utils/sensitivity';

interface SensitivitySelectProps {
  value: SensitivityLevel;
  onChange: (level: SensitivityLevel) => void;
  /** Il valore è il default della sorgente, non una scelta: lo dice accanto al nome. */
  isDefault?: boolean;
  disabled?: boolean;
  label?: string;
}

/** Scelta dell'etichetta di un fatto o di un documento: pubblici, interni, privati. */
export const SensitivitySelect: React.FC<SensitivitySelectProps> = ({ value, onChange, isDefault = false, disabled = false, label = 'Etichetta' }) => (
  <label
    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-xs ${LABEL_CHIPS[value]}`}
    title={`${label}: ${LABEL_HINTS[value]}`}
  >
    <Lock size={9} className="shrink-0" />
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as SensitivityLevel)}
      className="bg-transparent focus:outline-none cursor-pointer disabled:cursor-default"
      aria-label={label}
    >
      {LEVELS.map((l) => (
        <option key={l} value={l} className="bg-panel text-fg">
          {LABEL_NAMES[l]}
          {isDefault && l === value ? ' (predefinito)' : ''}
        </option>
      ))}
    </select>
  </label>
);
