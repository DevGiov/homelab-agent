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

// Stringhe di classi nel codice (tra apici, virgolette o backtick), escluse quelle dei test
const SOURCES = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const CLASS_STRINGS = Object.entries(SOURCES).flatMap(([file, text]) =>
  [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)].map((m) => ({ file: file.replace('../', 'src/'), classes: m[0].slice(1, -1) })),
);

/** I token di una stringa di classi, senza la punteggiatura dei template (`${cond ? 'a' : 'b'}`). */
const tokensOf = (classes: string) => classes.split(/[\s'"`{}()?,;]+/).filter(Boolean);

interface StateClasses {
  /** Variante dello stato: '' per quello normale, `hover:`, `group-hover:`… */
  variant: string;
  text: string;
  fill: string;
}

/**
 * Testo e fondo di ogni stato di una stringa di classi: in uno stato vale il token con la sua variante, altrimenti quello
 * senza variante (`bg-accent/15 hover:bg-accent/25 text-accent` dà text-accent su /15 e, al passaggio del mouse, su /25).
 * Lo stato disattivato non conta: i controlli disattivati non hanno requisiti di contrasto.
 */
function statesOf(classes: string, isText: (utility: string) => boolean, isFill: (utility: string) => boolean): StateClasses[] {
  const tokens = tokensOf(classes).map((token) => ({ variant: token.slice(0, token.lastIndexOf(':') + 1), utility: token.slice(token.lastIndexOf(':') + 1) }));
  const texts = tokens.filter((t) => isText(t.utility));
  const fills = tokens.filter((t) => isFill(t.utility));
  const variants = new Set([...texts, ...fills].map((t) => t.variant).filter((v) => !v.includes('disabled:')));
  return [...variants].flatMap((variant) => {
    const text = texts.find((t) => t.variant === variant) ?? texts.find((t) => t.variant === '');
    const fill = fills.find((t) => t.variant === variant) ?? fills.find((t) => t.variant === '');
    return text && fill ? [{ variant, text: text.utility, fill: fill.utility }] : [];
  });
}

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

describe("testo d'accento", () => {
  it("text-accent usa il testo d'accento del tema; fondi, bordi e anelli restano sull'accento", () => {
    expect(tailwindConfig.theme.extend.textColor.accent).toEqual({ DEFAULT: expect.stringContaining('var(--accent-text)') });
    expect(tailwindConfig.theme.extend.colors.accent).toMatchObject({ DEFAULT: expect.stringContaining('var(--accent)') });
  });

  // Le opacità delle tinte dell'accento dietro a `text-accent` nel codice, in ogni stato
  const tints = new Set(
    CLASS_STRINGS.flatMap(({ classes }) =>
      statesOf(classes, (u) => u === 'text-accent', (u) => /^bg-accent\/\d+$/.test(u)).map((s) => Number(s.fill.split('/')[1])),
    ),
  );

  it('le tinte dietro al testo si trovano nel codice', () => {
    expect([...tints]).toEqual(expect.arrayContaining([10, 15, 20, 25]));
  });

  describe.each(THEME_LIST)('tema $id', ({ colors }) => {
    it.each(SURFACES)('almeno 4.5:1 su %s e sulle tinte dell\'accento sopra di essa', (surface) => {
      for (const opacity of [0, ...tints]) {
        const background = over(colors.accent, colors[surface], opacity / 100);
        expect(contrast(colors.accentText, background), `/${opacity}`).toBeGreaterThanOrEqual(4.5);
      }
    });

    it('almeno 4.5:1 sul pannello al passaggio del mouse (bg-panel-hover)', () => {
      expect(contrast(colors.accentText, over(colors.fg, colors.panel, 0.08))).toBeGreaterThanOrEqual(4.5);
    });
  });
});

describe('classi di colore del tema', () => {
  const colors = tailwindConfig.theme.extend.colors;
  const roots = Object.keys(colors).sort((a, b) => b.length - a.length);
  const UTILITY = new RegExp(
    `^(?:text|bg|border(?:-[xytrbl])?|ring(?:-offset)?|outline|fill|stroke|divide|from|via|to|shadow|decoration|caret|accent)-(${roots.join('|')})(.*?)(?:\\/\\d+)?$`,
  );
  // Una classe con un nome di colore inesistente (`text-userBubbleText`) non genera CSS: il testo eredita il colore del
  // contenitore senza errori, ed è così che il fumetto dell'utente ha usato `fg` invece del suo colore
  const unknown = CLASS_STRINGS.flatMap(({ file, classes }) =>
    tokensOf(classes)
      .map((token) => ({ token, match: UTILITY.exec(token.split(':').pop() ?? '') }))
      .filter(({ match }) => {
        if (!match) return false;
        const [, root, rest] = match;
        const value = colors[root];
        if (rest === '') return typeof value !== 'string' && !('DEFAULT' in value);
        return !rest.startsWith('-') || typeof value === 'string' || !(rest.slice(1) in value);
      })
      .map(({ token }) => `${file}: ${token}`),
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
