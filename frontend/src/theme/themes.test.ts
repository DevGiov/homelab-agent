import { describe, expect, it } from 'vitest';
import palette from 'tailwindcss/colors';
import tailwindConfig from '../../tailwind.config.js';
import { STATUS_BUTTON, STATUS_FILL } from './statusFill';
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

// Colore `top` con opacità `alpha` sopra `bottom`, come lo compone il browser
const over = (top: string, bottom: string, alpha: number) =>
  '#' +
  [1, 3, 5]
    .map((i) => Math.round(parseInt(top.slice(i, i + 2), 16) * alpha + parseInt(bottom.slice(i, i + 2), 16) * (1 - alpha)))
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('');

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

  it.each(SURFACES)('testo al 80%% di opacità (text-fg/80, la più bassa usata) su %s', (surface) => {
    expect(contrast(over(colors.fg, colors[surface], 0.8), colors[surface])).toBeGreaterThanOrEqual(4.5);
  });
});

// Fondi di stato pieni: la tonalità della palette di Tailwind per una classe `bg-<colore>-<grado>`
const STATUS_HUES = ['emerald', 'green', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose', 'red', 'orange', 'amber', 'yellow', 'lime', 'zinc'] as const;
type Hue = (typeof STATUS_HUES)[number];
const FILL = new RegExp(`^bg-(${STATUS_HUES.join('|')})-(\\d{2,3})(/\\d+)?$`);
const fillsOf = (classes: string) =>
  classes
    .split(/\s+/)
    .map((token) => ({ token, match: FILL.exec(token.split(':').pop() ?? '') }))
    .filter((f) => f.match)
    .map(({ token, match }) => ({
      token,
      hex: palette[match![1] as Hue][Number(match![2]) as 500] as string,
      shade: Number(match![2]),
      translucent: Boolean(match![3]),
    }));

describe('fondi di stato pieni con testo bianco', () => {
  const variants = { ...STATUS_FILL, ...Object.fromEntries(Object.entries(STATUS_BUTTON).map(([k, v]) => [`${k}:pulsante`, v])) };

  it.each(Object.entries(variants))('%s: almeno 4.5:1, anche al passaggio del mouse', (_name, classes) => {
    expect(classes.split(/\s+/)).toContain('text-white');
    const fills = fillsOf(classes);
    expect(fills.length).toBeGreaterThan(0);
    for (const fill of fills) {
      // Opachi e mai 900/950: quelli il plugin dei temi chiari li trasforma in tinte chiare, e il bianco sparirebbe
      expect(fill.translucent, fill.token).toBe(false);
      expect(fill.shade, fill.token).toBeLessThan(900);
      expect(contrast('#ffffff', fill.hex), fill.token).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('i pulsanti scuriscono il loro fondo al passaggio del mouse', () => {
    for (const classes of Object.values(STATUS_BUTTON)) {
      const [base, hover] = fillsOf(classes);
      expect(hover.token.startsWith('hover:')).toBe(true);
      expect(hover.shade).toBeGreaterThan(base.shade);
    }
  });

  // Ogni stringa di classi nel codice con testo bianco sopra un fondo di stato: stesse regole delle varianti condivise
  const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
  const offenders = Object.entries(sources).flatMap(([file, text]) =>
    [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)]
      .map((m) => m[0].slice(1, -1))
      .filter((classes) => classes.split(/\s+/).some((t) => /(^|:)text-white(\/\d+)?$/.test(t)))
      .flatMap((classes) =>
        fillsOf(classes)
          .filter((f) => f.translucent || f.shade >= 900 || contrast('#ffffff', f.hex) < 4.5)
          .map((f) => `${file.replace('../', 'src/')}: ${f.token} in "${classes}"`),
      ),
  );

  it('nel codice nessun testo bianco su fondi di stato chiari, traslucidi o 900/950', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(offenders).toEqual([]);
  });
});

describe('classi di colore del tema', () => {
  const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
  const colors = tailwindConfig.theme.extend.colors;
  const roots = Object.keys(colors).sort((a, b) => b.length - a.length);
  const UTILITY = new RegExp(
    `^(?:text|bg|border(?:-[xytrbl])?|ring(?:-offset)?|outline|fill|stroke|divide|from|via|to|shadow|decoration|caret|accent)-(${roots.join('|')})(.*?)(?:\\/\\d+)?$`,
  );
  // Una classe con un nome di colore inesistente (`text-userBubbleText`) non genera CSS: il testo eredita il colore del
  // contenitore senza errori, ed è così che il fumetto dell'utente ha usato `fg` invece del suo colore
  const unknown = Object.entries(sources).flatMap(([file, text]) =>
    [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)]
      .flatMap((m) => m[0].slice(1, -1).split(/[\s'"`{}()?,;]+/))
      .map((token) => ({ token, match: UTILITY.exec(token.split(':').pop() ?? '') }))
      .filter(({ match }) => {
        if (!match) return false;
        const [, root, rest] = match;
        const value = colors[root];
        if (rest === '') return typeof value !== 'string' && !('DEFAULT' in value);
        return !rest.startsWith('-') || typeof value === 'string' || !(rest.slice(1) in value);
      })
      .map(({ token }) => `${file.replace('../', 'src/')}: ${token}`),
  );

  it('ogni classe di colore del tema usata nel codice esiste nella configurazione di Tailwind', () => {
    expect(roots).toEqual(expect.arrayContaining(['fg', 'accent', 'userBubble']));
    expect(unknown).toEqual([]);
  });
});

describe('testo e icone attenuati', () => {
  const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
  const classStrings = Object.entries(sources).flatMap(([file, text]) =>
    [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)].map((m) => ({ file: file.replace('../', 'src/'), classes: m[0].slice(1, -1) })),
  );

  // Il colore viene da una regola sola in index.css (`::placeholder` col testo attenuato, controllato qui sopra per ogni tema)
  it('i segnaposto non hanno classi di colore per campo', () => {
    expect(classStrings.filter(({ classes }) => /(^|\s)placeholder:text-/.test(classes))).toEqual([]);
  });

  it('il testo di stato non ha opacità: i temi chiari rimappano solo la classe piena', () => {
    const faded = classStrings.filter(({ classes }) => /(^|[\s:])text-[a-z]+-[1-4]00\/\d+/.test(classes));
    expect(faded.map(({ file, classes }) => `${file}: ${classes}`)).toEqual([]);
  });

  it('un controllo a icona non è attenuato: text-fg-muted/NN solo su icone decorative o disattivate', () => {
    const faded = classStrings.filter(
      ({ classes }) => /(^|\s)text-fg-muted\/\d+/.test(classes) && /(^|\s)[\w-]*hover:/.test(classes) && !classes.includes('cursor-not-allowed'),
    );
    expect(faded.map(({ file, classes }) => `${file}: ${classes}`)).toEqual([]);
  });
});
