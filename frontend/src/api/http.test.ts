import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { jsonResponse, mockBackend } from '../test/backend';
import { ApiError, apiUrl, formatDetail, getApiKey, http, initApiConfig, setApiKey } from './http';

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

describe('apiUrl', () => {
  it('omette i parametri null e undefined', () => {
    expect(apiUrl('/automations/runs', { automation_id: undefined, status: null, limit: 50, favorite: false })).toBe(
      '/v1/automations/runs?limit=50&favorite=false'
    );
  });

  it('non aggiunge "?" senza parametri', () => {
    expect(apiUrl('/threads')).toBe('/v1/threads');
  });
});

describe('API key', () => {
  it('usa la chiave di /config.json se in localStorage non ce n\'è una', async () => {
    mockBackend({ 'GET /config.json': () => jsonResponse({ apiKey: 'dal-config' }) });
    await initApiConfig();
    expect(getApiKey()).toBe('dal-config');
    setApiKey('  dall-utente  ');
    expect(getApiKey()).toBe('dall-utente');
  });

  it('invia X-API-Key a ogni richiesta', async () => {
    setApiKey('segreta');
    const { requests } = mockBackend({ 'GET /v1/health': () => jsonResponse({ status: 'ok' }) });
    await http.get('/health');
    expect(requests[0].headers.get('X-API-Key')).toBe('segreta');
  });
});

describe('http', () => {
  it('serializza il body JSON e restituisce i dati decodificati', async () => {
    const { requests } = mockBackend({ 'POST /v1/memory': (req) => jsonResponse({ id: 1, ...req.body }, 201) });
    const res = await http.post<{ id: number; content: string }>('/memory', { content: 'fatto' });
    expect(res).toEqual({ id: 1, content: 'fatto' });
    expect(requests[0].headers.get('Content-Type')).toBe('application/json');
  });

  it('lascia al browser il Content-Type dei FormData (boundary multipart)', async () => {
    const { requests } = mockBackend({ 'POST /v1/upload': () => jsonResponse({ ok: true }) });
    const form = new FormData();
    form.append('file', new Blob(['x']), 'x.png');
    await http.post('/upload', form);
    expect(requests[0].headers.has('Content-Type')).toBe(false);
    expect(requests[0].body).toBe(form);
  });

  it('non invia body per null (PATCH di toggle senza payload)', async () => {
    const fetchSpy = mockBackend({ 'PATCH /v1/automations/runs/r1/favorite': () => jsonResponse({}) }).fetchMock;
    await http.patch('/automations/runs/r1/favorite', null, { is_favorite: true });
    expect(fetchSpy.mock.calls[0][1]?.body).toBeUndefined();
    expect(String(fetchSpy.mock.calls[0][0])).toBe('/v1/automations/runs/r1/favorite?is_favorite=true');
  });

  it('restituisce undefined per una risposta vuota (204)', async () => {
    mockBackend({ 'DELETE /v1/permissions/3': () => new Response(null, { status: 204 }) });
    await expect(http.delete('/permissions/3')).resolves.toBeUndefined();
  });

  it('trasforma un 422 di Pydantic in ApiError con messaggio leggibile', async () => {
    mockBackend({
      'POST /v1/automations': () =>
        jsonResponse({ detail: [{ loc: ['body', 'workflow', 'steps'], msg: 'campo obbligatorio' }, { loc: ['body', 'name'], msg: 'troppo corto' }] }, 422),
    });
    const err = await http.post('/automations', {}).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.message).toBe('workflow.steps: campo obbligatorio; name: troppo corto');
  });

  it('usa il detail stringa di FastAPI come messaggio', async () => {
    mockBackend({ 'GET /v1/threads/x': () => jsonResponse({ detail: 'Thread non trovato' }, 404) });
    await expect(http.get('/threads/x')).rejects.toMatchObject({ status: 404, message: 'Thread non trovato' });
  });

  it('spiega il 413 di nginx e ignora la sua pagina HTML', async () => {
    mockBackend({ 'POST /v1/upload': () => new Response('<html><body>413 Request Entity Too Large</body></html>', { status: 413 }) });
    await expect(http.post('/upload', {})).rejects.toThrow(/troppo grande.*413/);
  });

  it('usa un corpo testuale breve se non è JSON', async () => {
    mockBackend({ 'GET /v1/health': () => new Response('Bad Gateway', { status: 502 }) });
    await expect(http.get('/health')).rejects.toMatchObject({ status: 502, message: 'Bad Gateway' });
  });

  it('segnala il backend non raggiungibile come ApiError con status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(http.get('/health')).rejects.toMatchObject({ status: 0, message: 'Backend non raggiungibile' });
  });

  it('segnala il timeout con la durata', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('timeout', 'TimeoutError')));
    await expect(http.get('/health')).rejects.toThrow('Nessuna risposta dal backend entro 120 s');
  });
});

describe('formatDetail', () => {
  it.each([
    ['stringa', '  errore  ', 'errore'],
    ['stringa vuota', '   ', null],
    ['oggetto con msg', { msg: 'm', error: 'e' }, 'm'],
    ['oggetto con error', { error: 'e' }, 'e'],
    ['oggetto senza campi noti', { code: 7 }, '{"code":7}'],
    ['lista vuota', [], null],
    ['assente', undefined, null],
  ])('%s', (_label, detail, expected) => {
    expect(formatDetail(detail)).toBe(expected);
  });
});
