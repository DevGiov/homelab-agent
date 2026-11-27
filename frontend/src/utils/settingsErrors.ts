import { ApiError } from '../api/http';
import { formatApiError } from './error';
import { PROVIDER_ERROR_MESSAGES } from './providerErrors';

/** I 409 dell'API delle impostazioni (RUNTIME_SETTINGS_DESIGN.md, sezione 5), come messaggi per l'utente. */
export const SETTINGS_ERROR_MESSAGES: Record<string, string> = {
  confirm_required: 'Questa modifica allarga chi può comandare l\'agente o i dati che riceve: serve una conferma esplicita.',
  no_secret_key: PROVIDER_ERROR_MESSAGES.no_secret_key,
};

/** Messaggio per un errore dell'API delle impostazioni: i codici noti hanno un testo chiaro, il resto passa com'è. */
export function settingsErrorMessage(err: unknown, fallback = 'Operazione non riuscita'): string {
  if (err instanceof ApiError) {
    if (err.status === 409 && err.detail && typeof err.detail === 'object') {
      const code = (err.detail as { code?: unknown }).code;
      if (typeof code === 'string' && SETTINGS_ERROR_MESSAGES[code]) return SETTINGS_ERROR_MESSAGES[code];
    }
    if (err.status === 404) return 'Sezione non trovata: aggiorna la scheda.';
  }
  return formatApiError(err, fallback);
}
