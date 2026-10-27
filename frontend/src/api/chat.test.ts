import { describe, expect, it, vi } from 'vitest';
import { chunkedStream, jsonResponse, mockBackend, sseBody, sseResponse } from '../test/backend';
import { attachToThreadStream, sendStreamMessage, type StreamHandlers } from './chat';
import { ApiError } from './http';

const handlers = () =>
  ({
    onReasoning: vi.fn(),
    onContent: vi.fn(),
    onFinal: vi.fn(),
    onRetrieval: vi.fn(),
    onMetrics: vi.fn(),
    onSync: vi.fn(),
  }) satisfies StreamHandlers;

const final = { type: 'final', response: { thread_id: 't1', mode: 'chat', response: 'Ciao!' } };

describe('sendStreamMessage', () => {
  it('invia la richiesta e smista ogni tipo di evento al proprio handler', async () => {
    const { requests } = mockBackend({
      'POST /v1/invoke_stream': () =>
        sseResponse([
          { type: 'sync', content: 'parziale', is_paused: false },
          { type: 'reasoning', delta: 'penso' },
          { type: 'retrieval', event: 'web_prefetch.started', data: { query: 'q' } },
          { type: 'content', delta: 'Ciao' },
          { type: 'metrics', metrics: { tok_per_s: 40 } },
          final,
          '[DONE]',
        ]),
    });
    const h = handlers();
    await sendStreamMessage({ input: 'ciao', thread_id: 't1', execute: true }, h);

    expect(requests[0].body).toEqual({ input: 'ciao', thread_id: 't1', execute: true });
    expect(h.onSync).toHaveBeenCalledWith(expect.objectContaining({ content: 'parziale' }));
    expect(h.onReasoning).toHaveBeenCalledWith('penso');
    expect(h.onRetrieval).toHaveBeenCalledWith('web_prefetch.started', { query: 'q' });
    expect(h.onContent).toHaveBeenCalledWith('Ciao');
    expect(h.onMetrics).toHaveBeenCalledWith({ tok_per_s: 40 });
    expect(h.onFinal).toHaveBeenCalledWith(final.response);
  });

  it('rispetta l\'ordine dei delta anche con eventi spezzati tra chunk', async () => {
    const body = sseBody([{ type: 'content', delta: 'a' }, { type: 'content', delta: 'b' }, { type: 'content', delta: 'c' }]);
    mockBackend({ 'POST /v1/invoke_stream': () => new Response(chunkedStream([body.slice(0, 20), body.slice(20, 50), body.slice(50)])) });
    const h = handlers();
    await sendStreamMessage({ input: 'x' }, h);
    expect(h.onContent.mock.calls.map(([d]) => d)).toEqual(['a', 'b', 'c']);
  });

  it('fallisce con il messaggio di un evento `error` e non elabora oltre', async () => {
    mockBackend({ 'POST /v1/invoke_stream': () => sseResponse([{ type: 'content', delta: 'pa' }, { type: 'error', error: 'LLM non disponibile' }, final]) });
    const h = handlers();
    await expect(sendStreamMessage({ input: 'x' }, h)).rejects.toThrow('LLM non disponibile');
    expect(h.onFinal).not.toHaveBeenCalled();
  });

  it('fallisce con ApiError su errore HTTP', async () => {
    mockBackend({ 'POST /v1/invoke_stream': () => jsonResponse({ detail: 'Modello non trovato' }, 400) });
    const err = await sendStreamMessage({ input: 'x' }, handlers()).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe('Modello non trovato');
  });

  it('si chiude senza errore se la richiesta viene annullata', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')));
    await expect(sendStreamMessage({ input: 'x' }, handlers(), new AbortController().signal)).resolves.toBeUndefined();
  });
});

describe('attachToThreadStream', () => {
  it('riceve lo snapshot iniziale e poi i delta del turno in corso', async () => {
    const { requests } = mockBackend({
      'GET /v1/threads/thread%201/stream': () => sseResponse([{ type: 'sync', content: 'già scritto' }, { type: 'content', delta: ' e altro' }, final]),
    });
    const h = handlers();
    await attachToThreadStream('thread 1', h);
    expect(requests[0].path).toBe('/v1/threads/thread%201/stream');
    expect(h.onSync).toHaveBeenCalledWith(expect.objectContaining({ content: 'già scritto' }));
    expect(h.onContent).toHaveBeenCalledWith(' e altro');
    expect(h.onFinal).toHaveBeenCalledOnce();
  });

  it('termina subito se il turno è già concluso (solo [DONE])', async () => {
    mockBackend({ 'GET /v1/threads/t1/stream': () => sseResponse(['[DONE]']) });
    const h = handlers();
    await attachToThreadStream('t1', h);
    expect(Object.values(h).every((fn) => fn.mock.calls.length === 0)).toBe(true);
  });
});
