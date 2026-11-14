import { describe, expect, it } from 'vitest';
import { documentTitle, formatRoute, HOME, isPlainClick, parseRoute, viewRoute, type Route } from './route';

describe('formatRoute e parseRoute', () => {
  const table: Array<[Route, string]> = [
    [{ view: 'chat', threadId: null }, '/'],
    [{ view: 'chat', threadId: 'thread_1731580000000' }, '/c/thread_1731580000000'],
    [{ view: 'automations' }, '/automazioni'],
    [{ view: 'calendar', eventUid: null }, '/calendario'],
    [{ view: 'calendar', eventUid: 'evt-42@esempio.invalid' }, '/calendario?evento=evt-42%40esempio.invalid'],
    [{ view: 'memory' }, '/memoria'],
    [{ view: 'metrics' }, '/metriche'],
  ];

  it.each(table)('%j ↔ %s', (route, url) => {
    expect(formatRoute(route)).toBe(url);
    expect(parseRoute(url)).toEqual(route);
  });

  it('codifica gli id con caratteri strani e li ritrova uguali', () => {
    for (const threadId of ['a/b', 'con spazio', 'cento%', 'domanda?x=1', 'hash#2', 'più è già', 'emoji 🚀', "apice'", 'a+b&c=d']) {
      const url = formatRoute({ view: 'chat', threadId });
      expect(url.startsWith('/c/')).toBe(true);
      // Un solo segmento dopo /c/, niente query né frammento
      expect(url.slice(3)).not.toMatch(/[/?#\s]/);
      expect(parseRoute(url)).toEqual({ view: 'chat', threadId });
    }
    const eventUid = 'uid con spazi & simboli=?#/';
    expect(parseRoute(formatRoute({ view: 'calendar', eventUid }))).toEqual({ view: 'calendar', eventUid });
  });

  it('legge la forma che il browser dà al percorso: caratteri non ASCII già codificati', () => {
    expect(parseRoute('/c/pi%C3%B9')).toEqual({ view: 'chat', threadId: 'più' });
    expect(parseRoute('/c/a:b')).toEqual({ view: 'chat', threadId: 'a:b' });
    expect(formatRoute({ view: 'chat', threadId: 'a:b' })).toBe('/c/a%3Ab');
  });

  it('i percorsi sconosciuti sono la pagina iniziale', () => {
    for (const url of ['/sconosciuto', '/c', '/c/', '/c/a/b', '//memoria', '/Memoria', '/memoria/extra', '/c/%E0%A4%A', '/chat']) {
      expect(parseRoute(url)).toEqual(HOME);
    }
  });

  it('tollera una barra finale e ignora query e frammento dove non servono', () => {
    expect(parseRoute('/memoria/')).toEqual({ view: 'memory' });
    expect(parseRoute('/c/abc/')).toEqual({ view: 'chat', threadId: 'abc' });
    expect(parseRoute('/metriche?x=1#sezione')).toEqual({ view: 'metrics' });
    expect(parseRoute('/calendario?altro=1')).toEqual({ view: 'calendar', eventUid: null });
    expect(parseRoute('/calendario?evento=')).toEqual({ view: 'calendar', eventUid: null });
    expect(parseRoute('/calendario?evento=abc#x')).toEqual({ view: 'calendar', eventUid: 'abc' });
  });

  it('un id vuoto non diventa un percorso', () => {
    expect(formatRoute({ view: 'chat', threadId: '' })).toBe('/');
    expect(formatRoute({ view: 'calendar', eventUid: '' })).toBe('/calendario');
  });

  it("l'ingresso di ogni vista", () => {
    expect(viewRoute('chat')).toEqual(HOME);
    expect(viewRoute('calendar')).toEqual({ view: 'calendar', eventUid: null });
    expect(viewRoute('memory')).toEqual({ view: 'memory' });
  });
});

describe('documentTitle', () => {
  it('nomina il posto prima dell’app', () => {
    expect(documentTitle({ view: 'chat', threadId: 'thr-1' }, 'Volo Giappone 2027')).toBe('Volo Giappone 2027 · Main-Agent UI');
    expect(documentTitle({ view: 'chat', threadId: 'thr-1' })).toBe('Conversazione · Main-Agent UI');
    expect(documentTitle(HOME, 'titolo vecchio')).toBe('Nuova conversazione · Main-Agent UI');
    expect(documentTitle({ view: 'memory' })).toBe('Memoria · Main-Agent UI');
    expect(documentTitle({ view: 'calendar', eventUid: 'x' })).toBe('Calendario · Main-Agent UI');
    expect(documentTitle({ view: 'automations' })).toBe('Automazioni · Main-Agent UI');
    expect(documentTitle({ view: 'metrics' })).toBe('Metriche · Main-Agent UI');
  });
});

describe('isPlainClick', () => {
  const click = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, defaultPrevented: false };

  it('il clic sinistro senza modificatori resta nella pagina', () => {
    expect(isPlainClick(click)).toBe(true);
  });

  it('nuova scheda, nuova finestra, tasto centrale e clic già gestiti restano al browser', () => {
    expect(isPlainClick({ ...click, ctrlKey: true })).toBe(false);
    expect(isPlainClick({ ...click, metaKey: true })).toBe(false);
    expect(isPlainClick({ ...click, shiftKey: true })).toBe(false);
    expect(isPlainClick({ ...click, altKey: true })).toBe(false);
    expect(isPlainClick({ ...click, button: 1 })).toBe(false);
    expect(isPlainClick({ ...click, defaultPrevented: true })).toBe(false);
  });
});
