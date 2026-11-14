import { describe, expect, it } from 'vitest';
import { THEME_LIST } from './themes';
import type { ThemeColors } from './types';

// Rapporto di contrasto WCAG 2 tra due colori esadecimali #rrggbb
const luminance = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const SURFACES: Array<keyof ThemeColors> = ['bg', 'bgSecondary', 'panel', 'panelHeader', 'agentBubble', 'inputBg'];

describe.each(THEME_LIST)('tema $id: contrasto del testo almeno 4.5:1', ({ colors }) => {
  it.each(SURFACES)('testo e testo attenuato su %s', (surface) => {
    expect(contrast(colors.fg, colors[surface])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(colors.fgMuted, colors[surface])).toBeGreaterThanOrEqual(4.5);
  });

  it("testo sopra l'accento pieno, anche al passaggio del mouse", () => {
    expect(contrast(colors.accentContrast, colors.accent)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(colors.accentContrast, colors.accentHover)).toBeGreaterThanOrEqual(4.5);
  });

  it("testo nel fumetto dell'utente", () => {
    expect(contrast(colors.userBubbleText, colors.userBubble)).toBeGreaterThanOrEqual(4.5);
  });
});
