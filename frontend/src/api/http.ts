// Client HTTP comune su fetch: base URL, API key, timeout ed errori del backend come ApiError.

export const API_BASE: string = import.meta.env.VITE_API_BASE || '/v1';

const REQUEST_TIMEOUT_MS = 120_000;
const API_KEY_STORAGE = 'main_agent_api_key';

// Chiave iniettata a runtime da /config.json (generato dall'entrypoint Docker)
let configApiKey = '';

/**
 * Carica la API key da /config.json (servito da nginx a runtime).
 * Va chiamata una volta all'avvio, prima del primo render; in dev senza Docker il file non esiste.
 */
export async function initApiConfig(): Promise<void> {
  try {
    const res = await fetch('/config.json', { cache: 'no-store' });
    if (res.ok) {
      const cfg = await res.json();
      if (cfg.apiKey) configApiKey = cfg.apiKey;
    }
  } catch {
    // In dev (Vite) /config.json non esiste
  }
}

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE) || configApiKey;
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key.trim());
}

export function authHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const key = getApiKey();
  return key ? { ...headers, 'X-API-Key': key } : { ...headers };
}

/** Errore del backend: `message` è già il dettaglio leggibile (FastAPI `detail`, compresi i 422 di Pydantic). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Testo leggibile da un `detail` di FastAPI: stringa, oggetto o lista di errori di validazione `{ loc, msg }`. */
export function formatDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null;

  if (Array.isArray(detail)) {
    const formatted = detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const loc = Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : '';
        const msg = item.msg || item.message || JSON.stringify(item);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean)
      .join('; ');
    return formatted || null;
  }

  if (detail && typeof detail === 'object') {
    const obj = detail as Record<string, unknown>;
    const text = obj.msg ?? obj.message ?? obj.error;
    return text ? String(text) : JSON.stringify(detail);
  }

  return null;
}

export async function errorFromResponse(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => '');
  let detail: unknown = null;
  try {
    detail = JSON.parse(text)?.detail ?? null;
  } catch {
    // corpo non JSON (es. pagina di errore di nginx)
  }

  let message = formatDetail(detail);
  if (!message && res.status === 413) {
    message = 'Richiesta troppo grande per il server (HTTP 413). Riduci la risoluzione delle immagini o invia meno file.';
  }
  if (!message && text && text.length < 300 && !text.trimStart().startsWith('<')) message = text;
  return new ApiError(res.status, detail, message || `HTTP ${res.status}`);
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

/** URL del backend; i parametri `null`/`undefined` vengono omessi. */
export function apiUrl(path: string, params?: QueryParams): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }
  const qs = query.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

async function request<T>(method: string, path: string, body?: unknown, params?: QueryParams): Promise<T> {
  const headers = authHeaders();
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body != null) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(apiUrl(path, params), {
      method,
      headers,
      body: payload,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      throw new ApiError(0, null, `Nessuna risposta dal backend entro ${REQUEST_TIMEOUT_MS / 1000} s`);
    }
    throw new ApiError(0, null, 'Backend non raggiungibile');
  }

  if (!res.ok) throw await errorFromResponse(res);
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const http = {
  get: <T>(path: string, params?: QueryParams) => request<T>('GET', path, undefined, params),
  delete: <T = void>(path: string, params?: QueryParams) => request<T>('DELETE', path, undefined, params),
  post: <T = void>(path: string, body?: unknown, params?: QueryParams) => request<T>('POST', path, body, params),
  put: <T = void>(path: string, body?: unknown, params?: QueryParams) => request<T>('PUT', path, body, params),
  patch: <T = void>(path: string, body?: unknown, params?: QueryParams) => request<T>('PATCH', path, body, params),
};
