import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { navigate, useRoute } from './useRoute';

/** Indietro o avanti come li fa il browser: la URL cambia, poi arriva `popstate`. */
const traverse = (url: string) =>
  act(() => {
    window.history.replaceState(null, '', url);
    window.dispatchEvent(new PopStateEvent('popstate'));
  });

describe('useRoute', () => {
  beforeEach(() => window.history.replaceState(null, '', '/'));
  afterEach(() => window.history.replaceState(null, '', '/'));

  it('legge la rotta dalla URL', () => {
    window.history.replaceState(null, '', '/c/thr-1');
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ view: 'chat', threadId: 'thr-1' });
  });

  it('la navigazione aggiunge una voce, la correzione la sostituisce', () => {
    const push = vi.spyOn(window.history, 'pushState');
    const replace = vi.spyOn(window.history, 'replaceState');
    const { result } = renderHook(() => useRoute());

    act(() => navigate({ view: 'memory' }));
    expect(result.current).toEqual({ view: 'memory' });
    expect(window.location.pathname).toBe('/memoria');
    expect(push).toHaveBeenCalledTimes(1);
    expect(replace).not.toHaveBeenCalled();

    act(() => navigate({ view: 'chat', threadId: 'thr-2' }, { replace: true }));
    expect(result.current).toEqual({ view: 'chat', threadId: 'thr-2' });
    expect(window.location.pathname).toBe('/c/thr-2');
    expect(push).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it('verso la URL corrente non aggiunge voci', () => {
    window.history.replaceState(null, '', '/metriche');
    const push = vi.spyOn(window.history, 'pushState');
    const { result } = renderHook(() => useRoute());
    const before = result.current;
    act(() => navigate({ view: 'metrics' }));
    expect(push).not.toHaveBeenCalled();
    // Stessa URL, stesso oggetto: chi dipende dalla rotta non si riesegue
    expect(result.current).toBe(before);
  });

  it('segue indietro e avanti del browser', () => {
    const { result } = renderHook(() => useRoute());
    traverse('/calendario?evento=evt-1');
    expect(result.current).toEqual({ view: 'calendar', eventUid: 'evt-1' });
    traverse('/');
    expect(result.current).toEqual({ view: 'chat', threadId: null });
  });

  it('una URL sconosciuta torna alla pagina iniziale sostituendo la voce', async () => {
    window.history.replaceState(null, '', '/non-esiste?x=1');
    const push = vi.spyOn(window.history, 'pushState');
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ view: 'chat', threadId: null });
    await waitFor(() => expect(window.location.pathname + window.location.search).toBe('/'));
    expect(push).not.toHaveBeenCalled();
  });

  it('una URL scritta in un’altra forma diventa quella canonica', async () => {
    window.history.replaceState(null, '', '/memoria/');
    renderHook(() => useRoute());
    await waitFor(() => expect(window.location.pathname).toBe('/memoria'));
  });

  it('più componenti vedono la stessa rotta', () => {
    const a = renderHook(() => useRoute());
    const b = renderHook(() => useRoute());
    act(() => navigate({ view: 'automations' }));
    expect(a.result.current).toEqual({ view: 'automations' });
    expect(b.result.current).toEqual({ view: 'automations' });
  });
});
