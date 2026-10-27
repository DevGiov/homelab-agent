import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { useSecurityMode } from './useSecurityMode';

beforeEach(() => localStorage.clear());

describe('useSecurityMode', () => {
  it('parte da "normal" e propaga la modifica a tutti i componenti montati', () => {
    const toolbar = renderHook(() => useSecurityMode());
    const settings = renderHook(() => useSecurityMode());
    expect(toolbar.result.current[0]).toBe('normal');

    act(() => settings.result.current[1]('safest'));

    expect(toolbar.result.current[0]).toBe('safest');
    expect(localStorage.getItem('homelab_security_mode')).toBe('safest');
  });
});
