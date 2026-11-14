import type { ThemeDefinition } from './types';

/** Colori dei blocchi di codice (highlight.js): fondo, testo e un colore per gruppo di token. */
export interface CodeColors {
  bg: string;
  fg: string;
  keyword: string;
  title: string;
  constant: string;
  string: string;
  builtin: string;
  comment: string;
  tag: string;
  section: string;
  bullet: string;
  additionFg: string;
  additionBg: string;
  deletionFg: string;
  deletionBg: string;
}

/**
 * Una tavolozza per i temi scuri e una per quelli chiari: il blocco segue la luminosità del tema. Partono da GitHub Dark e
 * GitHub Light; ogni token sta ad almeno 4.5:1 sul fondo del blocco (themes.test.ts). Rispetto agli originali cambiano i
 * titoli di sezione scuri (#1f6feb, 4.1:1) e i commenti chiari (#6e7781, 4.3:1). Il fondo chiaro è più chiaro del fumetto
 * dell'agente del tema chiaro, su cui il blocco sta di solito.
 */
export const CODE_COLORS: Record<'dark' | 'light', CodeColors> = {
  dark: {
    bg: '#0d1117',
    fg: '#c9d1d9',
    keyword: '#ff7b72',
    title: '#d2a8ff',
    constant: '#79c0ff',
    string: '#a5d6ff',
    builtin: '#ffa657',
    comment: '#8b949e',
    tag: '#7ee787',
    section: '#58a6ff',
    bullet: '#f2cc60',
    additionFg: '#aff5b4',
    additionBg: '#033a16',
    deletionFg: '#ffdcd7',
    deletionBg: '#67060c',
  },
  light: {
    bg: '#f8fafc',
    fg: '#24292f',
    keyword: '#cf222e',
    title: '#8250df',
    constant: '#0550ae',
    string: '#0a3069',
    builtin: '#953800',
    comment: '#57606a',
    tag: '#116329',
    section: '#0550ae',
    bullet: '#953800',
    additionFg: '#116329',
    additionBg: '#dafbe1',
    deletionFg: '#82071e',
    deletionBg: '#ffebe9',
  },
};

export const codeColorsFor = (theme: ThemeDefinition): CodeColors => CODE_COLORS[theme.isDark ? 'dark' : 'light'];

/** Le variabili CSS lette dalle regole `.hljs` di index.css: `additionFg` diventa `--code-addition-fg`. */
export const codeVariables = (colors: CodeColors): Array<[string, string]> =>
  Object.entries(colors).map(([key, value]) => [`--code-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`, value]);
