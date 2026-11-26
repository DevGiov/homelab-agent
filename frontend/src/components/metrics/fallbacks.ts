import type { FallbackCounts } from '../../api/metrics';

const REASON_LABELS: Record<string, string> = {
  label: 'dati non ammessi',
  budget: 'tetto di spesa',
};

/** "2 per tetto di spesa, 1 per dati non ammessi": i motivi per cui le chiamate sono andate al modello locale. */
export function fallbackSummary(fallbacks: FallbackCounts): string {
  return Object.entries(fallbacks)
    .filter(([, n]) => n)
    .map(([reason, n]) => `${n} per ${REASON_LABELS[reason] ?? reason}`)
    .join(', ');
}
