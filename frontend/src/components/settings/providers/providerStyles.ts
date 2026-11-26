import type { ProviderSecret } from '../../../api/providers';

export const inputClass = 'w-full bg-input-bg border border-input-border rounded-lg px-2.5 py-1.5 text-xs text-fg focus:border-accent disabled:opacity-50';
export const labelClass = 'block text-xs font-medium text-fg-muted';

/** Come si dice a parole lo stato di una credenziale: mai il suo valore. */
export function secretStatus(secret: ProviderSecret | undefined): string {
  if (!secret?.set) return 'non impostata';
  return secret.source === 'env' ? 'impostata (da .env)' : 'impostata dalla UI';
}
