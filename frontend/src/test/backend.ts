// Backend finto per i test: risposte JSON, stream SSE e un router di fetch per percorso.
import { vi } from 'vitest';

const encoder = new TextEncoder();

/** Stream che emette i chunk così come sono, per simulare eventi spezzati tra più letture. */
export function chunkedStream(chunks: Array<string | Uint8Array>): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
}

export const sseBody = (events: Array<object | string>) =>
  events.map((e) => `data: ${typeof e === 'string' ? e : JSON.stringify(e)}\n\n`).join('');

export const sseResponse = (events: Array<object | string>) =>
  new Response(chunkedStream([sseBody(events)]), { headers: { 'Content-Type': 'text/event-stream' } });

export const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

export interface RecordedRequest {
  method: string;
  path: string;
  search: string;
  headers: Headers;
  body: any;
}

type Handler = (req: RecordedRequest, init?: RequestInit) => Response | Promise<Response>;

/**
 * Sostituisce `fetch` con un router: la chiave è `"METODO /percorso"` (match esatto) o una RegExp
 * sul solo percorso. Le richieste senza handler rispondono 404; tutte vengono registrate in `requests`.
 */
export function mockBackend(routes: Record<string, Handler>, patterns: Array<[RegExp, Handler]> = []) {
  const requests: RecordedRequest[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const method = init?.method ?? 'GET';
    const body = init?.body instanceof FormData ? init.body : init?.body ? JSON.parse(String(init.body)) : undefined;
    const req = { method, path: url.pathname, search: url.search, headers: new Headers(init?.headers), body };
    requests.push(req);
    const handler = routes[`${method} ${url.pathname}`] ?? patterns.find(([re]) => re.test(url.pathname))?.[1];
    return handler ? handler(req, init) : jsonResponse({ detail: 'Not Found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { requests, fetchMock };
}
