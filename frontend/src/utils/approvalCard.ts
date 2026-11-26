// Stato della scheda di approvazione: perché non si può più decidere (404, 409, 410) e la sua scadenza.
import { ApiError } from '../api/http';

/** Perché la richiesta non si può più decidere: la risposta del backend (404, 409 già risolta, 410) o la scadenza. */
export interface ClosedApproval {
  code: 'not_found' | 'already_resolved' | 'expired';
  /** Per already_resolved: l'azione registrata (approved | denied). */
  action?: string;
  expiresAt?: string | null;
}

/** 404 id sconosciuto, 409 `already_resolved`, 410 scaduta. Un altro 409 (turno in corso) non chiude la scheda. */
export function closedFromError(err: unknown): ClosedApproval | null {
  if (!(err instanceof ApiError)) return null;
  const detail = (err.detail && typeof err.detail === 'object' ? err.detail : {}) as Record<string, unknown>;
  const code = typeof detail.code === 'string' ? detail.code : null;
  if (code === 'already_resolved') {
    return { code, action: typeof detail.action === 'string' ? detail.action : undefined };
  }
  if (code === 'expired' || (!code && err.status === 410)) {
    return { code: 'expired', expiresAt: typeof detail.expires_at === 'string' ? detail.expires_at : null };
  }
  if (code === 'not_found' || (!code && err.status === 404)) return { code: 'not_found' };
  return null;
}

function formatWhen(date: Date, now: Date): string {
  const time = new Intl.DateTimeFormat('it-IT', { hour: '2-digit', minute: '2-digit' }).format(date);
  if (date.toDateString() === now.toDateString()) return `alle ${time}`;
  const day = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'short' }).format(date);
  return `il ${day} alle ${time}`;
}

/** Scadenza da mostrare: "Scade alle 22:38" (o con il giorno, se non è oggi), "Scaduta ..." quando è passata. */
export function formatApprovalDeadline(iso: string, now: Date): { label: string; expired: boolean } | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const expired = date.getTime() <= now.getTime();
  return { label: `${expired ? 'Scaduta' : 'Scade'} ${formatWhen(date, now)}`, expired };
}

const RESOLVED_LABELS: Record<string, string> = { approved: 'approvata', denied: 'rifiutata' };
const ASK_AGAIN = "Chiedi di nuovo all'agente se serve ancora.";

/** Il testo della scheda chiusa: dice quale dei tre casi è. */
export function closedMessage(closed: ClosedApproval, now: Date, fallbackExpiresAt?: string | null): string {
  if (closed.code === 'not_found') return `Richiesta non trovata: il backend non la conosce più. ${ASK_AGAIN}`;
  if (closed.code === 'already_resolved') {
    const label = closed.action ? RESOLVED_LABELS[closed.action] : undefined;
    return `Richiesta già risolta${label ? ` (${label})` : ''}. Non accetta altre decisioni.`;
  }
  const date = new Date(closed.expiresAt || fallbackExpiresAt || '');
  const when = Number.isNaN(date.getTime()) ? '' : ` ${formatWhen(date, now)}`;
  return `Richiesta scaduta${when}: il tool non è stato eseguito. ${ASK_AGAIN}`;
}
