import { describe, expect, it } from 'vitest';
import indexCss from './index.css?raw';

// Classi di Tailwind 3 che in Tailwind 4 non esistono più o hanno un altro significato: scritte per abitudine, non genererebbero
// il risultato di prima (o non genererebbero nulla), senza errori. Qui sotto, cosa usare al loro posto.
const SOURCES = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const TOKENS = Object.entries(SOURCES).flatMap(([file, text]) =>
  [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)].flatMap((m) =>
    m[0]
      .slice(1, -1)
      .split(/[\s'"`{}()?,;]+/)
      .filter(Boolean)
      .map((token) => ({ file: file.replace('./', 'src/'), token, utility: token.split(':').pop() ?? '' })),
  ),
);

const offenders = (pattern: RegExp) => [...new Set(TOKENS.filter(({ utility }) => pattern.test(utility)).map(({ file, token }) => `${file}: ${token}`))];

describe('classi di Tailwind 3 da non usare in Tailwind 4', () => {
  it('space-x/y e divide-x/y: stack-x/y e stack-divide-x/y (index.css), con le regole di prima', () => {
    expect(offenders(/^-?space-[xy]-|^divide-/)).toEqual([]);
    expect(indexCss).toContain('@utility stack-y-*');
    expect(indexCss).toContain('@utility stack-divide-y');
  });

  it('ombre, angoli e sfocature: shadow-xs, rounded-sm… hanno i nomi nuovi', () => {
    // Senza suffisso (`shadow`, `rounded`) sono le taglie di Tailwind 3 rinominate: si scrive la taglia (`shadow-sm`,
    // `rounded-sm`), e `drop-shadow-soft` per l'ombra dell'icona. `shadow-sm` di 3 è `shadow-xs`, `rounded-sm` è `rounded-xs`
    expect(offenders(/^(shadow|rounded|drop-shadow|backdrop-blur)$/)).toEqual([]);
  });

  it('gradienti: bg-linear-to-*/srgb, che interpola come Tailwind 3 (bg-gradient-to-* in 4 interpola in oklab)', () => {
    expect(offenders(/^bg-gradient-to-/)).toEqual([]);
  });

  it('utility rimosse: outline-none, flex-shrink/grow, overflow-ellipsis, bg-opacity-*, decoration-slice', () => {
    expect(offenders(/^(outline-none|flex-shrink|flex-grow|overflow-ellipsis|decoration-slice|decoration-clone|(bg|text|border|ring|divide|placeholder)-opacity-)/)).toEqual([]);
  });

  it('modificatore importante in fondo (`x!`), non davanti (`!x`)', () => {
    expect(offenders(/^![a-z][\w-]*(\/\d+)?$/)).toEqual([]);
  });

  it('valori con variabili CSS: bg-(--x), non bg-[--x]', () => {
    expect(offenders(/\[--[\w-]+\]/)).toEqual([]);
  });
});
