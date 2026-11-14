import { describe, expect, it } from 'vitest';
import defaultTheme from 'tailwindcss/theme.css?raw';
import indexCss from '../index.css?raw';

// Un breakpoint che il tema non definisce (`xs:inline`) non genera CSS: l'elemento resta nascosto a ogni
// larghezza senza errori. Per i componenti che stanno in colonne di larghezza variabile servono le container query (`@md:`).
// I breakpoint sono le variabili `--breakpoint-*`: quelle predefinite di Tailwind (theme.css) e le eventuali di index.css
const screens = [...new Set([...(defaultTheme + indexCss).matchAll(/--breakpoint-(\w+):/g)].map((m) => m[1]))];
const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const SCREEN_LIKE = /^(?:max-)?(xs|sm|md|lg|xl|\dxl)$/;

describe('breakpoint usati nel codice', () => {
  it('esistono tutti nel tema di Tailwind', () => {
    expect(screens).toEqual(expect.arrayContaining(['sm', 'md', 'lg', 'xl']));
    const unknown = Object.entries(sources).flatMap(([file, text]) =>
      [...text.matchAll(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g)]
        .flatMap((m) => m[0].slice(1, -1).split(/[\s'"`{}()?,;]+/))
        .filter((token) => token.split(':').slice(0, -1).some((v) => SCREEN_LIKE.test(v) && !screens.includes(v.replace(/^max-/, ''))))
        .map((token) => `${file.replace(/^\.\//, 'src/components/').replace(/^\.\.\//, 'src/')}: ${token}`),
    );
    expect(unknown).toEqual([]);
  });
});
