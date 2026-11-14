import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { jsonResponse, mockBackend, sseResponse, type RecordedRequest } from './test/backend';

const THREADS = [
  { thread_id: 'thr-1', title: 'Volo Giappone 2027', last_message: 'Prenotato', checkpoint_count: 2 },
  { thread_id: 'thr-2', title: 'Backup del NAS', last_message: 'Fatto', checkpoint_count: 1 },
];

/** Backend finto: elenco, dettaglio di ogni conversazione con un messaggio riconoscibile, eliminazione e invio. */
function setupBackend(threads = THREADS) {
  return mockBackend(
    {
      'GET /v1/threads': () => jsonResponse(threads),
      'GET /v1/health': () => jsonResponse({ status: 'ok' }),
      'POST /v1/invoke_stream': () =>
        sseResponse([
          { type: 'content', delta: 'Ciao' },
          { type: 'final', response: { mode: 'act', response: 'Ciao a te' } },
          '[DONE]',
        ]),
    },
    [
      [
        /^\/v1\/threads\/[^/]+$/,
        (req) => {
          if (req.method === 'DELETE') return jsonResponse({ status: 'ok' });
          const id = decodeURIComponent(req.path.split('/').pop()!);
          const thread = threads.find((t) => t.thread_id === id);
          // Come il backend: una conversazione sconosciuta ha uno storico vuoto, non un 404
          return jsonResponse({
            thread_id: id,
            title: thread?.title ?? null,
            messages: thread ? [{ id: `u-${id}`, sender: 'user', content: `Messaggio di ${id}`, timestamp: '10:00' }] : [],
          });
        },
      ],
    ],
  );
}

const historyLoads = (requests: RecordedRequest[], threadId: string) =>
  requests.filter((r) => r.method === 'GET' && r.path === `/v1/threads/${encodeURIComponent(threadId)}`).length;

const here = () => window.location.pathname + window.location.search;

/**
 * Voci aggiunte e sostituite da qui in poi. `history.length` non basta: una voce nuova toglie quelle "avanti" lasciate
 * dai test precedenti nella stessa cronologia di jsdom.
 */
const watchHistory = () => ({ push: vi.spyOn(window.history, 'pushState'), replace: vi.spyOn(window.history, 'replaceState') });

/** Indietro o avanti del browser: si aspetta il `popstate` che jsdom manda come il browser. */
const traverse = (delta: number) =>
  act(
    () =>
      new Promise<void>((resolve) => {
        window.addEventListener('popstate', () => resolve(), { once: true });
        window.history.go(delta);
      }),
  );

async function renderAt(url: string) {
  window.history.replaceState(null, '', url);
  const utils = render(<App />);
  await screen.findByRole('navigation', { name: 'Viste' });
  return utils;
}

const viewLink = (name: string) => within(screen.getByRole('navigation', { name: 'Viste' })).getByRole('link', { name });
const threadLink = (name: RegExp) =>
  within(screen.getByRole('list', { name: 'Conversazioni' })).getByRole('link', { name });

beforeEach(() => {
  // jsdom non implementa lo scorrimento della lista dei messaggi
  Element.prototype.scrollIntoView = vi.fn();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    localStorage.clear();
  } catch {
    // Senza storage valgono i default
  }
});
afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});

describe('App: una URL per ogni vista', () => {
  it('/memoria apre la memoria, segnata nella navigazione e nel titolo della scheda', async () => {
    setupBackend();
    await renderAt('/memoria');
    expect(await screen.findByRole('heading', { level: 2, name: 'Memoria' })).toBeTruthy();
    expect(viewLink('Memoria').getAttribute('aria-current')).toBe('page');
    expect(viewLink('Chat').hasAttribute('aria-current')).toBe(false);
    expect(document.title).toBe('Memoria · Main-Agent UI');
    // Niente chat né diagnostica fuori dalla chat
    expect(screen.queryByRole('textbox', { name: 'Messaggio' })).toBeNull();
  });

  it('/metriche e /calendario aprono le loro viste', async () => {
    setupBackend();
    await renderAt('/metriche');
    expect(await screen.findByRole('heading', { level: 2, name: 'Metriche' })).toBeTruthy();
    expect(document.title).toBe('Metriche · Main-Agent UI');
    cleanup();
    await renderAt('/calendario');
    expect(await screen.findByRole('heading', { level: 2, name: 'Calendario' }, { timeout: 5000 })).toBeTruthy();
    expect(document.title).toBe('Calendario · Main-Agent UI');
  });

  it('un percorso sconosciuto torna a / sostituendo la voce', async () => {
    setupBackend();
    window.history.replaceState(null, '', '/non-esiste/davvero?x=1');
    const history = watchHistory();
    await renderAt('/non-esiste/davvero?x=1');
    await waitFor(() => expect(here()).toBe('/'));
    expect(history.push).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Messaggio' })).toBeTruthy();
    expect(document.title).toBe('Nuova conversazione · Main-Agent UI');
  });

  it('scegliere una vista aggiunge una voce; indietro torna alla vista di prima', async () => {
    setupBackend();
    await renderAt('/automazioni');
    const history = watchHistory();
    fireEvent.click(viewLink('Metriche'));
    expect(here()).toBe('/metriche');
    expect(history.push).toHaveBeenCalledTimes(1);
    expect(history.replace).not.toHaveBeenCalled();
    expect(await screen.findByRole('heading', { level: 2, name: 'Metriche' })).toBeTruthy();

    await traverse(-1);
    expect(here()).toBe('/automazioni');
    expect(viewLink('Automazioni').getAttribute('aria-current')).toBe('page');
    expect(document.title).toBe('Automazioni · Main-Agent UI');
  });
});

describe('App: una URL per ogni conversazione', () => {
  it('/c/<id> carica quella conversazione una volta sola', async () => {
    const { requests } = setupBackend();
    await renderAt('/c/thr-1');
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();
    expect(threadLink(/^Volo Giappone 2027/).getAttribute('aria-current')).toBe('true');
    await waitFor(() => expect(document.title).toBe('Volo Giappone 2027 · Main-Agent UI'));
    expect(historyLoads(requests, 'thr-1')).toBe(1);
  });

  it('scegliere una conversazione aggiunge /c/<id> e la carica una volta sola', async () => {
    const { requests } = setupBackend();
    await renderAt('/');
    const history = watchHistory();
    fireEvent.click(threadLink(/^Backup del NAS/));
    expect(here()).toBe('/c/thr-2');
    expect(history.push).toHaveBeenCalledTimes(1);
    expect(history.replace).not.toHaveBeenCalled();
    expect(await screen.findByText('Messaggio di thr-2')).toBeTruthy();
    expect(historyLoads(requests, 'thr-2')).toBe(1);
    expect(document.title).toBe('Backup del NAS · Main-Agent UI');
  });

  it('indietro e avanti tra vista, conversazione e vista ritrovano posto e storico senza ricaricarlo', async () => {
    const { requests } = setupBackend();
    await renderAt('/memoria');
    fireEvent.click(threadLink(/^Volo Giappone 2027/));
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();
    fireEvent.click(viewLink('Metriche'));
    expect(await screen.findByRole('heading', { level: 2, name: 'Metriche' })).toBeTruthy();

    await traverse(-1);
    expect(here()).toBe('/c/thr-1');
    expect(screen.getByText('Messaggio di thr-1')).toBeTruthy();
    await traverse(-1);
    expect(here()).toBe('/memoria');
    expect(await screen.findByRole('heading', { level: 2, name: 'Memoria' })).toBeTruthy();
    await traverse(1);
    expect(here()).toBe('/c/thr-1');
    expect(screen.getByText('Messaggio di thr-1')).toBeTruthy();
    expect(historyLoads(requests, 'thr-1')).toBe(1);
  });

  it('dalle altre viste il link "Chat" riporta all’ultima conversazione', async () => {
    const { requests } = setupBackend();
    await renderAt('/c/thr-2');
    expect(await screen.findByText('Messaggio di thr-2')).toBeTruthy();
    fireEvent.click(viewLink('Memoria'));
    expect(viewLink('Chat').getAttribute('href')).toBe('/c/thr-2');
    fireEvent.click(viewLink('Chat'));
    expect(here()).toBe('/c/thr-2');
    expect(screen.getByText('Messaggio di thr-2')).toBeTruthy();
    expect(historyLoads(requests, 'thr-2')).toBe(1);
  });

  it('"Nuova conversazione" porta a / come voce nuova', async () => {
    setupBackend();
    await renderAt('/c/thr-1');
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();
    const history = watchHistory();
    fireEvent.click(screen.getByRole('button', { name: 'Nuova conversazione' }));
    expect(here()).toBe('/');
    expect(history.push).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Messaggio di thr-1')).toBeNull();
    expect(document.title).toBe('Nuova conversazione · Main-Agent UI');
  });

  it('al primo messaggio la conversazione nuova prende il suo id al posto di /', async () => {
    const { requests } = setupBackend();
    await renderAt('/');
    const history = watchHistory();
    const input = screen.getByRole('textbox', { name: 'Messaggio' });
    fireEvent.change(input, { target: { value: 'Prenota un volo di prova' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(here()).toMatch(/^\/c\/thread_\d+$/));
    expect(history.push).not.toHaveBeenCalled();
    expect(history.replace).toHaveBeenCalledTimes(1);
    const threadId = decodeURIComponent(here().slice(3));
    expect(await screen.findByText('Ciao a te')).toBeTruthy();
    // Lo storico della conversazione appena nata non si carica: i messaggi sono già quelli in streaming
    expect(historyLoads(requests, threadId)).toBe(0);
    expect(screen.getByText('Prenota un volo di prova')).toBeTruthy();
  });

  it('una conversazione che non esiste torna a / senza lasciare la voce', async () => {
    const { requests } = setupBackend();
    window.history.replaceState(null, '', '/c/inesistente');
    const history = watchHistory();
    await renderAt('/c/inesistente');
    await waitFor(() => expect(here()).toBe('/'));
    expect(history.push).not.toHaveBeenCalled();
    expect(historyLoads(requests, 'inesistente')).toBeLessThanOrEqual(1);
    expect(screen.getByRole('textbox', { name: 'Messaggio' })).toBeTruthy();
    expect(document.title).toBe('Nuova conversazione · Main-Agent UI');
  });

  it('eliminando la conversazione aperta la URL torna a /', async () => {
    setupBackend();
    await renderAt('/c/thr-1');
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();
    const history = watchHistory();
    fireEvent.click(screen.getByRole('button', { name: 'Elimina la conversazione Volo Giappone 2027' }));
    await waitFor(() => expect(here()).toBe('/'));
    expect(history.push).not.toHaveBeenCalled();
    expect(history.replace).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Messaggio di thr-1')).toBeNull();
  });

  it('tornando indietro a una conversazione eliminata la URL torna a /', async () => {
    setupBackend();
    await renderAt('/c/thr-1');
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();
    fireEvent.click(threadLink(/^Backup del NAS/));
    expect(await screen.findByText('Messaggio di thr-2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Elimina la conversazione Volo Giappone 2027' }));
    await waitFor(() => expect(screen.queryByRole('link', { name: /^Volo Giappone 2027/ })).toBeNull());

    await traverse(-1);
    await waitFor(() => expect(here()).toBe('/'));
    expect(screen.queryByText('Messaggio di thr-1')).toBeNull();
  });

  it('eliminare tutto da un’altra vista non lascia una conversazione da riaprire', async () => {
    setupBackend();
    mockDeleteAll();
    await renderAt('/c/thr-1');
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();
    fireEvent.click(viewLink('Memoria'));
    fireEvent.click(screen.getByTitle('Elimina tutte le conversazioni'));
    fireEvent.click(screen.getByRole('button', { name: 'Elimina tutte' }));
    await waitFor(() => expect(viewLink('Chat').getAttribute('href')).toBe('/'));
    expect(here()).toBe('/memoria');
  });
});

/** DELETE /v1/threads sopra il backend corrente (mockBackend risponde 404 alle rotte senza handler). */
function mockDeleteAll() {
  const inner = globalThis.fetch;
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) =>
    init?.method === 'DELETE' && new URL(String(input), 'http://localhost').pathname === '/v1/threads'
      ? Promise.resolve(jsonResponse({ status: 'ok' }))
      : inner(input, init),
  );
}

/** matchMedia finto a una larghezza fissa. */
function stubViewport(width: number) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: width >= Number(/min-width: (\d+)px/.exec(query)?.[1] ?? 0),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe('App: cassetti e cronologia su schermi piccoli', () => {
  it('indietro va al posto di prima e chiude il cassetto, senza voci per il cassetto', async () => {
    stubViewport(390);
    setupBackend();
    const { container } = await renderAt('/');
    const sidebar = container.querySelector('aside[aria-label="Barra laterale"]')!.parentElement!;
    const history = watchHistory();

    fireEvent.click(screen.getByTitle('Apri barra laterale conversazioni'));
    expect(sidebar.hasAttribute('inert')).toBe(false);
    // Aprire il cassetto non aggiunge voci: indietro non serve a chiuderlo
    expect(history.push).not.toHaveBeenCalled();
    fireEvent.click(threadLink(/^Volo Giappone 2027/));
    expect(sidebar.hasAttribute('inert')).toBe(true);
    expect(await screen.findByText('Messaggio di thr-1')).toBeTruthy();

    fireEvent.click(screen.getByTitle('Apri barra laterale conversazioni'));
    expect(sidebar.hasAttribute('inert')).toBe(false);
    await traverse(-1);
    expect(here()).toBe('/');
    expect(sidebar.hasAttribute('inert')).toBe(true);
  });
});
