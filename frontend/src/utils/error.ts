/**
 * Messaggio sicuro da renderizzare in JSX per un errore qualsiasi.
 * Gli ApiError del client HTTP portano già il `detail` del backend formattato nel `message`.
 */
export function formatApiError(err: unknown, fallbackMessage: string = 'Si è verificato un errore'): string {
  if (typeof err === 'string') return err || fallbackMessage;
  if (err instanceof Error && err.message) return err.message;
  return fallbackMessage;
}
