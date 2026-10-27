import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FormattedMessage } from '../api/chat';
import { jsonResponse, mockBackend, sseResponse, type RecordedRequest } from '../test/backend';
import { useChat } from './useChat';

const THREAD = 't1';

const finalEvent = (text: string, extra: object = {}) => ({
  type: 'final',
  response: { thread_id: THREAD, mode: 'act', response: text, tool_used: 'list_containers', ...extra },
});

/** Backend con un thread esistente e uno stream che risponde "Risposta N" alla N-esima richiesta. */
function setupBackend(thread: object = { thread_id: THREAD, messages: [] }) {
  let turn = 0;
  return mockBackend(
    {
      [`GET /v1/threads/${THREAD}`]: () => jsonResponse(thread),
      'POST /v1/invoke_stream': () => {
        turn += 1;
        return sseResponse([
          { type: 'reasoning', delta: `ragiono ${turn}` },
          { type: 'content', delta: 'Rispo' },
          { type: 'content', delta: `sta ${turn}` },
          finalEvent(`Risposta ${turn}`),
          '[DONE]',
        ]);
      },
      'POST /v1/chat/stop': () => jsonResponse({ status: 'stopped' }),
    },
    [[/\/messages\/[^/]+\/(version|versions_data)$/, () => jsonResponse({ status: 'ok' })]]
  );
}

async function renderChat() {
  const hook = renderHook(() => useChat(THREAD));
  await waitFor(() => expect(hook.result.current.isLoadingChat).toBe(false));
  return hook;
}

const streamRequests = (requests: RecordedRequest[]) => requests.filter((r) => r.path === '/v1/invoke_stream');
const contents = (messages: FormattedMessage[]) => messages.map((m) => `${m.sender}: ${m.content}`);

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

describe('useChat — invio', () => {
  it('aggiunge prompt e risposta, mantiene il reasoning in streaming e aggiorna la diagnostica', async () => {
    const { requests } = setupBackend();
    const { result } = await renderChat();

    await act(() =>
      result.current.handleSendMessage('elenca i container', {
        mode: 'act',
        execute: true,
        model: 'LFM2.5',
        webSearch: 'off',
        securityMode: 'normal',
        images: [],
      })
    );

    const messages = result.current.currentMessages;
    expect(contents(messages)).toEqual(['user: elenca i container', 'assistant: Risposta 1']);
    expect(messages[1].reasoning_content).toBe('ragiono 1');
    expect(messages[1].tool_used).toBe('list_containers');
    expect(result.current.diagnostics.activeTool).toBe('list_containers');
    expect(result.current.isLoadingChat).toBe(false);
    expect(streamRequests(requests)[0].body).toEqual({
      input: 'elenca i container',
      thread_id: THREAD,
      force_mode: 'act',
      execute: true,
      model: 'LFM2.5',
      web_search: 'off',
      security_mode: 'normal',
    });
  });

  it('crea un thread nuovo e lo notifica se non ce n\'è uno selezionato', async () => {
    setupBackend();
    const onThreadCreated = vi.fn();
    const { result } = renderHook(() => useChat(null, onThreadCreated));
    await act(() => result.current.handleSendMessage('ciao', { execute: true }));
    expect(onThreadCreated).toHaveBeenCalledWith(expect.stringMatching(/^thread_\d+$/));
  });

  it('su evento `error` sostituisce il placeholder con un messaggio di errore', async () => {
    mockBackend({
      [`GET /v1/threads/${THREAD}`]: () => jsonResponse({ thread_id: THREAD, messages: [] }),
      'POST /v1/invoke_stream': () => sseResponse([{ type: 'content', delta: 'parz' }, { type: 'error', error: 'LLM non disponibile' }]),
    });
    const { result } = await renderChat();

    await act(() => result.current.handleSendMessage('ciao', { execute: true }));

    const [, reply] = result.current.currentMessages;
    expect(result.current.currentMessages).toHaveLength(2);
    expect(reply).toMatchObject({ isError: true, content: 'Error: LLM non disponibile' });
    expect(result.current.chatError).toBe('API Error: LLM non disponibile');
    expect(result.current.isLoadingChat).toBe(false);
  });

  it('mostra il dettaglio di un 422 in forma leggibile', async () => {
    mockBackend({
      [`GET /v1/threads/${THREAD}`]: () => jsonResponse({ thread_id: THREAD, messages: [] }),
      'POST /v1/invoke_stream': () => jsonResponse({ detail: [{ loc: ['body', 'input'], msg: 'campo obbligatorio' }] }, 422),
    });
    const { result } = await renderChat();
    await act(() => result.current.handleSendMessage('', { execute: true }));
    expect(result.current.chatError).toBe('API Error: input: campo obbligatorio');
  });
});

describe('useChat — versioni', () => {
  it('la rigenerazione aggiunge una versione e la salva sul backend', async () => {
    const { requests } = setupBackend();
    const { result } = await renderChat();
    await act(() => result.current.handleSendMessage('domanda', { execute: true }));
    const assistantId = result.current.currentMessages[1].id;

    await act(() => result.current.handleRegenerateMessage(assistantId));

    const reply = result.current.currentMessages[1];
    expect(reply.content).toBe('Risposta 2');
    expect(reply.versionIndex).toBe(1);
    expect(reply.versions?.map((v) => v.content)).toEqual(['Risposta 1', 'Risposta 2']);
    expect(streamRequests(requests)[1].body.input).toBe('domanda');
    const saved = requests.find((r) => r.path.endsWith(`/messages/${assistantId}/versions_data`));
    expect(saved?.body.version_index).toBe(1);
    expect(saved?.body.versions).toHaveLength(2);
  });

  it('la modifica del prompt rigenera la risposta con il testo nuovo', async () => {
    const { requests } = setupBackend();
    const { result } = await renderChat();
    await act(() => result.current.handleSendMessage('prompt originale', { execute: true }));
    const userId = result.current.currentMessages[0].id;

    await act(() => result.current.handleEditPrompt(userId, { content: 'prompt corretto', mode: 'ask' }));

    expect(streamRequests(requests).map((r) => r.body.input)).toEqual(['prompt originale', 'prompt corretto']);
    expect(streamRequests(requests)[1].body.force_mode).toBe('ask');
    const [prompt, reply] = result.current.currentMessages;
    expect(prompt.versions?.map((v) => v.content)).toEqual(['prompt originale', 'prompt corretto']);
    expect(reply.content).toBe('Risposta 2');
  });

  it('il cambio di versione mostra la versione scelta e lo comunica al backend', async () => {
    const { requests } = setupBackend();
    const { result } = await renderChat();
    await act(() => result.current.handleSendMessage('domanda', { execute: true }));
    const assistantId = result.current.currentMessages[1].id;
    await act(() => result.current.handleRegenerateMessage(assistantId));

    act(() => result.current.handleSwitchVersion(assistantId, 0));

    expect(result.current.currentMessages[1]).toMatchObject({ content: 'Risposta 1', versionIndex: 0 });
    await waitFor(() =>
      expect(requests.find((r) => r.path.endsWith(`/messages/${assistantId}/version`))?.body).toEqual({ version_index: 0 })
    );
  });
});

describe('useChat — turni in corso', () => {
  it('all\'apertura di un thread attivo si riaggancia allo stream', async () => {
    mockBackend({
      [`GET /v1/threads/${THREAD}`]: () =>
        jsonResponse({
          thread_id: THREAD,
          is_active: true,
          messages: [
            { id: 'u1', sender: 'user', content: 'domanda', timestamp: '10:00' },
            { id: 'a1', sender: 'assistant', content: '', timestamp: '10:00' },
          ],
        }),
      [`GET /v1/threads/${THREAD}/stream`]: () =>
        sseResponse([{ type: 'sync', content: 'Già scritto', reasoning_content: 'pensiero' }, { type: 'content', delta: ', poi il resto.' }]),
    });
    const { result } = renderHook(() => useChat(THREAD));

    await waitFor(() => expect(result.current.isLoadingChat).toBe(false));
    expect(result.current.currentMessages[1]).toMatchObject({
      id: 'a1',
      content: 'Già scritto, poi il resto.',
      reasoning_content: 'pensiero',
    });
  });

  it('lo stop annulla la richiesta e lo segnala al backend', async () => {
    const { requests } = mockBackend({
      [`GET /v1/threads/${THREAD}`]: () => jsonResponse({ thread_id: THREAD, messages: [] }),
      'POST /v1/chat/stop': () => jsonResponse({ status: 'stopped' }),
      // Stream che resta aperto finché la richiesta non viene annullata
      'POST /v1/invoke_stream': (_req, init) =>
        new Promise<Response>((_resolve, reject) =>
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        ),
    });
    const { result } = await renderChat();

    let sending: Promise<void> = Promise.resolve();
    act(() => {
      sending = result.current.handleSendMessage('lungo', { execute: true });
    });
    await waitFor(() => expect(result.current.isLoadingChat).toBe(true));

    await act(() => result.current.handleStop());
    await act(() => sending);

    expect(requests.some((r) => r.path === '/v1/chat/stop' && r.body.thread_id === THREAD)).toBe(true);
    expect(result.current.isLoadingChat).toBe(false);
    expect(result.current.chatError).toBeNull();
  });
});
