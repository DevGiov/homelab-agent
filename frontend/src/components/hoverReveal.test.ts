import { describe, expect, it } from 'vitest';

// Elementi nascosti finché il mouse non passa sopra (`opacity-0 group-hover:opacity-100` e simili): col Tab devono
// comparire quando ricevono il focus, e su telefoni e tablet, dove il passaggio del mouse non esiste, devono restare
// visibili (`can-hover:opacity-0` li nasconde solo sui dispositivi col mouse). Fanno eccezione al secondo punto le
// sovrimpressioni decorative (`pointer-events-none`), che non sono controlli.
const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const classStrings = Object.entries(sources).flatMap(([file, text]) =>
  [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)].map((m) => ({
    file: file.replace(/^\.\//, 'src/components/').replace(/^\.\.\//, 'src/'),
    tokens: m[0].slice(1, -1).split(/[\s'"`{}()?,;]+/).filter(Boolean),
  })),
);

const HOVER_REVEAL = /^(?:[\w-]+:)*(?:group-hover(?:\/[\w-]+)?|peer-hover(?:\/[\w-]+)?|hover):(?:opacity-100|visible)$/;
const FOCUS_REVEAL = /^(?:focus|focus-visible|focus-within|group-focus(?:-visible|-within)?(?:\/[\w-]+)?):(?:opacity-100|visible)$/;
const HIDDEN = new Set(['opacity-0', 'invisible']);

const revealed = classStrings.filter(({ tokens }) => tokens.some((t) => HOVER_REVEAL.test(t)) && tokens.some((t) => HIDDEN.has(t.split(':').pop() ?? '')));

describe('controlli che compaiono al passaggio del mouse', () => {
  it('il controllo trova i casi nel codice', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(revealed.length).toBeGreaterThanOrEqual(6);
  });

  it('compaiono anche quando ricevono il focus da tastiera', () => {
    const missing = revealed.filter(({ tokens }) => !tokens.some((t) => FOCUS_REVEAL.test(t)));
    expect(missing.map(({ file, tokens }) => `${file}: ${tokens.join(' ')}`)).toEqual([]);
  });

  it('sui dispositivi senza mouse restano visibili (can-hover:opacity-0), tranne le sovrimpressioni decorative', () => {
    const touchHidden = revealed.filter(
      ({ tokens }) => !tokens.includes('pointer-events-none') && tokens.some((t) => HIDDEN.has(t)) && !tokens.some((t) => /^can-hover:(opacity-0|invisible)$/.test(t)),
    );
    expect(touchHidden.map(({ file, tokens }) => `${file}: ${tokens.join(' ')}`)).toEqual([]);
  });
});
