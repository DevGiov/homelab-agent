import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useChatOptions } from './useChatOptions';

describe('useChatOptions: modello', () => {
  it('parte dal modello caricato, o da default se nessuno lo è', () => {
    expect(renderHook(() => useChatOptions('t1', 'Qwen3.6-35B')).result.current.model).toBe('Qwen3.6-35B');
    expect(renderHook(() => useChatOptions('t1', null)).result.current.model).toBe('default');
  });

  it('segue il modello caricato quando arriva dal server', () => {
    const { result, rerender } = renderHook(({ loaded }) => useChatOptions('t1', loaded), {
      initialProps: { loaded: null as string | null },
    });
    rerender({ loaded: 'LFM2.5-24B-A2B-Fast' });
    expect(result.current.model).toBe('LFM2.5-24B-A2B-Fast');
    expect(result.current.toSendOptions().model).toBe('LFM2.5-24B-A2B-Fast');
  });

  it('tiene la scelta dell\'utente nel thread e torna al caricato aprendo un altro thread', () => {
    const { result, rerender } = renderHook(({ thread, loaded }) => useChatOptions(thread, loaded), {
      initialProps: { thread: 't1' as string | null, loaded: 'Qwen3.6-35B' as string | null },
    });
    act(() => result.current.setModel('Gemma-4-26B-Q3'));
    rerender({ thread: 't1', loaded: 'Gemma-4-26B-Q3' });
    rerender({ thread: 't1', loaded: 'Qwen3.6-35B' });
    expect(result.current.model).toBe('Gemma-4-26B-Q3');

    rerender({ thread: null, loaded: 'Qwen3.6-35B' });
    expect(result.current.model).toBe('Qwen3.6-35B');
  });

  it('tiene la scelta quando il primo messaggio crea il thread della chat nuova', () => {
    const { result, rerender } = renderHook(({ thread }) => useChatOptions(thread, 'Qwen3.6-35B'), {
      initialProps: { thread: null as string | null },
    });
    act(() => result.current.setModel('Gemma-4-26B-Q3'));
    rerender({ thread: 'nuovo-thread' });
    expect(result.current.model).toBe('Gemma-4-26B-Q3');
  });
});
