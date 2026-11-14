import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialDiagnosticsOpen, useDiagnosticsPanel } from './useDiagnosticsPanel';

function screenWidth(px: number) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: px >= Number(/min-width: (\d+)px/.exec(query)?.[1] ?? 0) }));
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('pannello della diagnostica', () => {
  it('senza una scelta salvata è aperto solo sugli schermi larghi', () => {
    screenWidth(1280);
    expect(initialDiagnosticsOpen()).toBe(false);
    screenWidth(1920);
    expect(initialDiagnosticsOpen()).toBe(true);
  });

  it('aprirlo o chiuderlo a mano resta; aprirlo per un messaggio no', () => {
    screenWidth(1280);
    const { result } = renderHook(() => useDiagnosticsPanel());
    act(() => result.current.reveal());
    expect(result.current.open).toBe(true);
    expect(renderHook(() => useDiagnosticsPanel()).result.current.open).toBe(false);

    act(() => result.current.toggle());
    act(() => result.current.toggle());
    expect(result.current.open).toBe(true);
    expect(renderHook(() => useDiagnosticsPanel()).result.current.open).toBe(true);

    screenWidth(1920);
    act(() => result.current.toggle());
    expect(renderHook(() => useDiagnosticsPanel()).result.current.open).toBe(false);
  });

  it('senza storage vale la larghezza dello schermo', () => {
    screenWidth(1920);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloccato'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloccato'); });
    const { result } = renderHook(() => useDiagnosticsPanel());
    expect(result.current.open).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.open).toBe(false);
  });
});
