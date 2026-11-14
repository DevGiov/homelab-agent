import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { jsonResponse, mockBackend } from './test/backend';

describe('App: landmark della pagina', () => {
  beforeEach(() => {
    // jsdom non implementa lo scorrimento della lista dei messaggi
    Element.prototype.scrollIntoView = vi.fn();
    mockBackend({
      'GET /v1/threads': () => jsonResponse([]),
      'GET /v1/health': () => jsonResponse({ status: 'ok' }),
    });
  });
  afterEach(cleanup);

  it('ha un solo main, la navigazione delle viste e le due barre laterali con un nome', async () => {
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });

    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(container.querySelectorAll('main')).toHaveLength(1);
    expect(screen.getByRole('complementary', { name: 'Barra laterale' })).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'Diagnostica' })).toBeTruthy();
    // La chat sta nel main, le barre laterali fuori
    const main = screen.getByRole('main');
    expect(main.querySelector('textarea')).toBeTruthy();
    expect(main.querySelector('aside')).toBeNull();
    expect(screen.getByRole('region', { name: 'Messaggi' })).toBeTruthy();
  });

  it('dà un titolo alla vista corrente sotto quello dell’app', async () => {
    render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    expect(screen.getByRole('heading', { level: 1, name: 'Main-Agent UI' })).toBeTruthy();
    expect(screen.getAllByRole('heading', { level: 2 }).length).toBeGreaterThan(0);
  });
});

/** matchMedia finto con una larghezza che il test può cambiare, avvisando chi ascolta come fa il browser. */
function stubViewport(initial: number) {
  let width = initial;
  const listeners = new Set<() => void>();
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() {
      return width >= Number(/min-width: (\d+)px/.exec(query)?.[1] ?? 0);
    },
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }));
  return (next: number) =>
    act(() => {
      width = next;
      listeners.forEach((fn) => fn());
    });
}

describe('App: cassetti laterali su schermi piccoli', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    try {
      localStorage.clear();
    } catch {
      // Senza storage valgono i default
    }
    mockBackend({
      'GET /v1/threads': () => jsonResponse([]),
      'GET /v1/health': () => jsonResponse({ status: 'ok' }),
    });
  });
  afterEach(cleanup);

  // Il contenitore che scorre dentro e fuori dallo schermo
  const drawers = (container: HTMLElement) => ({
    sidebar: container.querySelector('aside[aria-label="Barra laterale"]')!.parentElement!,
    toolLog: container.querySelector('aside[aria-label="Diagnostica"]')!.parentElement!,
  });

  it('a 390 px i cassetti chiusi sono inert, il contenuto principale no', async () => {
    stubViewport(390);
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    const { sidebar, toolLog } = drawers(container);
    expect(sidebar.hasAttribute('inert')).toBe(true);
    expect(toolLog.hasAttribute('inert')).toBe(true);
    expect(container.querySelector('main')!.closest('[inert]')).toBeNull();
  });

  it('da 768 px in su le barre laterali restano interattive', async () => {
    stubViewport(1440);
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    const { sidebar, toolLog } = drawers(container);
    expect(sidebar.hasAttribute('inert')).toBe(false);
    expect(toolLog.hasAttribute('inert')).toBe(false);
  });

  it('aperto, il cassetto prende il focus; Escape lo chiude e il focus torna al pulsante del menu', async () => {
    stubViewport(390);
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    const { sidebar } = drawers(container);
    const menu = screen.getByTitle('Apri barra laterale conversazioni');
    act(() => menu.focus());
    fireEvent.click(menu);

    expect(sidebar.hasAttribute('inert')).toBe(false);
    expect(sidebar.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(sidebar.hasAttribute('inert')).toBe(true);
    expect(document.activeElement).toBe(menu);
  });

  it('il cassetto della diagnostica si apre e si chiude allo stesso modo', async () => {
    stubViewport(390);
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    const { toolLog } = drawers(container);
    const open = screen.getByRole('button', { name: 'Apri Diagnostica' });
    act(() => open.focus());
    fireEvent.click(open);
    expect(toolLog.hasAttribute('inert')).toBe(false);
    expect(toolLog.contains(document.activeElement)).toBe(true);

    fireEvent.click(screen.getByTitle('Chiudi diagnostica'));
    expect(toolLog.hasAttribute('inert')).toBe(true);
    expect(document.activeElement).toBe(open);
  });

  it('cambiando larghezza inert segue lo schermo e i cassetti aperti si chiudono', async () => {
    const resize = stubViewport(390);
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    const { sidebar, toolLog } = drawers(container);
    fireEvent.click(screen.getByTitle('Apri barra laterale conversazioni'));
    expect(sidebar.hasAttribute('inert')).toBe(false);

    resize(1024);
    expect(sidebar.hasAttribute('inert')).toBe(false);
    expect(toolLog.hasAttribute('inert')).toBe(false);

    resize(390);
    await waitFor(() => expect(sidebar.hasAttribute('inert')).toBe(true));
    expect(toolLog.hasAttribute('inert')).toBe(true);
  });
});

describe('App: finestra delle impostazioni', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    mockBackend({
      'GET /v1/threads': () => jsonResponse([]),
      'GET /v1/health': () => jsonResponse({ status: 'ok' }),
    });
  });
  afterEach(cleanup);

  it('si apre col focus dentro, lo tiene dentro e Escape lo restituisce al pulsante', async () => {
    render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    const opener = screen.getAllByTitle('Impostazioni (API key, Temi, Memorie)')[0];
    act(() => opener.focus());
    fireEvent.click(opener);

    const dialog = await screen.findByRole('dialog', { name: 'Impostazioni & Personalizzazione' });
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true });
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Impostazioni & Personalizzazione' })).toBeNull());
    expect(document.activeElement).toBe(opener);
  });
});
