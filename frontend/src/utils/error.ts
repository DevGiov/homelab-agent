/**
 * Utility per la sanitizzazione e formattazione sicura degli errori API.
 * Garantisce che il valore restituito sia SEMPRE una stringa sicura da renderizzare in JSX,
 * evitando errori fatali di React (es. Minified React error #31 su oggetti o array di dettaglio 422).
 */

export function formatApiError(err: any, fallbackMessage: string = 'Si è verificato un errore'): string {
  if (!err) return fallbackMessage;

  // Se l'errore è già una stringa pura
  if (typeof err === 'string') return err;

  const detail = err?.response?.data?.detail;

  // 1. Caso FastAPI 422 (Array di errori Pydantic: [{ loc, msg, type, input }])
  if (Array.isArray(detail)) {
    const formatted = detail
      .map((item: any) => {
        if (typeof item === 'string') return item;
        if (!item || typeof item !== 'object') return String(item);

        const loc = Array.isArray(item.loc)
          ? item.loc.filter((part: any) => part !== 'body').join('.')
          : '';
        const msg = item.msg || item.message || JSON.stringify(item);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean)
      .join('; ');

    if (formatted) return formatted;
  }

  // 2. Caso dettaglio stringa singola
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }

  // 3. Caso dettaglio oggetto singolo (es. { msg: '...', error: '...' })
  if (detail && typeof detail === 'object') {
    if (detail.msg) return String(detail.msg);
    if (detail.message) return String(detail.message);
    if (detail.error) return String(detail.error);
    try {
      return JSON.stringify(detail);
    } catch {
      // ignore
    }
  }

  // 4. Caso errore axios / JavaScript generico
  if (err.message && typeof err.message === 'string') {
    return err.message;
  }

  return fallbackMessage;
}
