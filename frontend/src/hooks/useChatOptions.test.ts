import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useChatOptions } from './useChatOptions';

const LOCAL = { provider: 'llamacpp', model: 'Qwen3.6-35B' };
const CLOUD = { provider: 'bedrock', model: 'anthropic.claude-sonnet' };
const OTHER = { provider: 'ollama', model: 'llama3' };

describe('useChatOptions: modello come coppia (provider, modello)', () => {
  it('una conversazione nuova parte dal predefinito del catalogo, o da nessuna scelta se non è arrivato', () => {
    expect(renderHook(() => useChatOptions(null, LOCAL)).result.current.selection).toEqual(LOCAL);
    const empty = renderHook(() => useChatOptions(null, null)).result.current;
    expect(empty.selection).toBeNull();
    expect(empty.toSendOptions()).toMatchObject({ provider: undefined, model: undefined });
  });

  it('segue il predefinito quando arriva dal catalogo', () => {
    const { result, rerender } = renderHook(({ def }) => useChatOptions(null, def), {
      initialProps: { def: null as typeof LOCAL | null },
    });
    rerender({ def: LOCAL });
    expect(result.current.selection).toEqual(LOCAL);
    expect(result.current.toSendOptions()).toMatchObject({ provider: 'llamacpp', model: 'Qwen3.6-35B' });
  });

  it('una conversazione aperta ripristina il suo provider e il suo modello, non il predefinito', () => {
    const { result } = renderHook(() => useChatOptions('t1', LOCAL, CLOUD));
    expect(result.current.selection).toEqual(CLOUD);
    expect(result.current.toSendOptions()).toMatchObject({ provider: 'bedrock', model: 'anthropic.claude-sonnet' });
  });

  it('una conversazione senza modello salvato usa il predefinito', () => {
    expect(renderHook(() => useChatOptions('t1', LOCAL, null)).result.current.selection).toEqual(LOCAL);
  });

  it('la scelta dell\'utente vale sul modello salvato, e si perde aprendo un altro thread', () => {
    const { result, rerender } = renderHook(({ thread, saved }) => useChatOptions(thread, LOCAL, saved), {
      initialProps: { thread: 't1' as string | null, saved: CLOUD as typeof CLOUD | null },
    });
    act(() => result.current.setSelection(OTHER));
    expect(result.current.selection).toEqual(OTHER);
    rerender({ thread: 't2', saved: null });
    expect(result.current.selection).toEqual(LOCAL);
  });

  it('tiene la scelta quando il primo messaggio crea il thread della chat nuova', () => {
    const { result, rerender } = renderHook(({ thread }) => useChatOptions(thread, LOCAL), {
      initialProps: { thread: null as string | null },
    });
    act(() => result.current.setSelection(CLOUD));
    rerender({ thread: 'nuovo-thread' });
    expect(result.current.selection).toEqual(CLOUD);
  });

  it('una chat nuova non eredita il modello salvato del thread che si lascia', () => {
    const { result, rerender } = renderHook(({ thread, saved }) => useChatOptions(thread, LOCAL, saved), {
      initialProps: { thread: 't1' as string | null, saved: CLOUD as typeof CLOUD | null },
    });
    rerender({ thread: null, saved: null });
    expect(result.current.selection).toEqual(LOCAL);
  });
});

describe('useChatOptions: ricerca web', () => {
  it('si sceglie direttamente e resta tra le sessioni', () => {
    localStorage.clear();
    const { result } = renderHook(() => useChatOptions('t1'));
    expect(result.current.webSearch).toBe('auto');
    act(() => result.current.setWebSearch('off'));
    expect(result.current.toSendOptions().webSearch).toBe('off');
    expect(renderHook(() => useChatOptions('t2')).result.current.webSearch).toBe('off');
    localStorage.clear();
  });
});
