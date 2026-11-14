import { act, cleanup, render } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { CODE_COLORS, codeVariables } from './codeColors';
import { ThemeProvider } from './ThemeContext';
import type { ThemeId } from './types';
import { useTheme } from './useTheme';

let setTheme: (id: ThemeId) => void = () => {};
const Probe: React.FC = () => {
  setTheme = useTheme().setTheme;
  return null;
};

const codeVariablesOnRoot = () =>
  Object.fromEntries(codeVariables(CODE_COLORS.dark).map(([name]) => [name, document.documentElement.style.getPropertyValue(name)]));

describe('ThemeProvider, blocchi di codice', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('imposta la tavolozza scura nei temi scuri e quella chiara nel tema chiaro, anche cambiando tema', () => {
    localStorage.setItem('homelab-agent-theme', 'cyberpunk');
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(codeVariablesOnRoot()).toEqual(Object.fromEntries(codeVariables(CODE_COLORS.dark)));

    act(() => setTheme('light'));
    expect(codeVariablesOnRoot()).toEqual(Object.fromEntries(codeVariables(CODE_COLORS.light)));
    expect(document.documentElement.style.getPropertyValue('--code-addition-fg')).toBe(CODE_COLORS.light.additionFg);
  });
});
