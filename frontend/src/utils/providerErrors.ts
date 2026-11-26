import { ApiError } from '../api/http';
import { formatApiError } from './error';

/** I 409 dell'API dei provider (PROVIDERS_DESIGN.md, 5.8.6), come messaggi per l'utente. */
export const PROVIDER_ERROR_MESSAGES: Record<string, string> = {
  reserved_name: 'Questo nome è riservato: scegline un altro.',
  name_taken: 'Esiste già un provider con questo nome.',
  env_provider: 'Un provider definito dal .env non si elimina: si disattiva, oppure si usa «Ripristina il .env».',
  fallback_provider: 'È il provider di ripiego: scegline un altro tra le impostazioni in fondo alla scheda prima di disattivarlo o eliminarlo.',
  confirm_required: 'Alzare il livello richiede una conferma esplicita.',
  no_secret_key: 'Senza API_SECRET_KEY le credenziali non si possono salvare: imposta API_SECRET_KEY nel .env e ricrea il backend.',
  provider_disabled: 'Il provider è disattivato: attivalo per usarlo.',
  kind_change: 'Il tipo di un provider non si cambia: crea un altro provider.',
  default_provider: 'È il provider predefinito: scegline un altro tra le impostazioni in fondo alla scheda prima di disattivarlo, eliminarlo o lasciarlo incompleto.',
  not_env_provider: 'Questo provider è stato aggiunto dalla UI: non ha un .env a cui tornare.',
};

/** Messaggio per un errore dell'API dei provider: i codici noti hanno un testo chiaro, il resto passa com'è. */
export function providerErrorMessage(err: unknown, fallback = 'Operazione non riuscita'): string {
  if (err instanceof ApiError) {
    if (err.status === 409 && err.detail && typeof err.detail === 'object') {
      const code = (err.detail as { code?: unknown }).code;
      if (typeof code === 'string' && PROVIDER_ERROR_MESSAGES[code]) return PROVIDER_ERROR_MESSAGES[code];
    }
    if (err.status === 404) return 'Provider non trovato: aggiorna la scheda.';
  }
  return formatApiError(err, fallback);
}
