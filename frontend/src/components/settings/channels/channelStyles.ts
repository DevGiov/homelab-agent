import type { SecretStatus } from '../../../api/settings';

/** Stato a parole di una credenziale: mai il suo valore. */
export function tokenStatus(secret: SecretStatus): string {
  if (!secret.set) return 'non impostato';
  return secret.source === 'env' ? 'impostato (da .env)' : 'impostato dalla UI';
}

export const saveButtonClass =
  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-accent-contrast text-xs font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default';
export const secondaryButtonClass =
  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-fg-muted hover:text-fg text-xs cursor-pointer disabled:opacity-50';
