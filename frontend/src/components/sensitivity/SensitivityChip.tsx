import React from 'react';
import { Lock } from 'lucide-react';
import { describeTag, LABEL_CHIPS, LABEL_HINTS, LABEL_NAMES, type SensitivityTag } from '../../utils/sensitivity';

/** Chip dell'etichetta, con i motivi nel tooltip. `always`: mostrato anche per i dati pubblici. */
export const SensitivityChip: React.FC<{ tag?: SensitivityTag | null; always?: boolean; className?: string }> = ({
  tag,
  always = false,
  className = '',
}) => {
  if (!tag?.label || (!always && tag.label === 'public' && !tag.untrusted)) return null;
  const { reasons, untrusted } = describeTag(tag);
  const lines = [`Dati ${LABEL_NAMES[tag.label].toLowerCase()}: ${LABEL_HINTS[tag.label]}`];
  if (reasons.length) lines.push(`Perché: ${reasons.join('; ')}`);
  if (untrusted.length) lines.push(`Ha letto contenuto non attendibile: ${untrusted.map((u) => u.replace(/^contenuto non attendibile: /, '')).join('; ')}`);
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-xs font-medium ${LABEL_CHIPS[tag.label]} ${className}`}
      title={lines.join('\n')}
      data-testid="sensitivity-chip"
    >
      <Lock size={9} className="shrink-0" />
      {LABEL_NAMES[tag.label]}
      {tag.untrusted ? <span>· non attendibile</span> : null}
    </span>
  );
};
