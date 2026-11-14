import { describe, expect, it } from 'vitest';
import resolveConfig from 'tailwindcss/resolveConfig';
import tailwindConfig from '../../tailwind.config.js';

// Un breakpoint che la configurazione non definisce (`xs:inline`) non genera CSS: l'elemento resta nascosto a ogni
// larghezza senza errori. Per i componenti che stanno in colonne di larghezza variabile servono le container query (`@md:`).
const screens = Object.keys(resolveConfig(tailwindConfig).theme.screens as Record<string, unknown>);
const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const SCREEN_LIKE = /^(?:max-)?(xs|sm|md|lg|xl|\dxl)$/;

describe('breakpoint usati nel codice', () => {
  it('esistono tutti nella configurazione di Tailwind', () => {
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
