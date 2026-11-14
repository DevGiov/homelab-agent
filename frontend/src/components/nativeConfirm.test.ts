import { describe, expect, it } from 'vitest';

// Le conferme passano dal dialogo dell'app (`useConfirm` + `ConfirmDialog`): il `confirm()` del browser può essere
// soppresso senza avvisi, non segue il tema e porta il focus dove vuole. `confirm({ message })` è quello dell'app.
const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const NATIVE = /\bwindow\.confirm\b|(?<![\w.])confirm\(\s*[`'"]/;

describe('conferme', () => {
  it('nessun confirm() nativo nel codice', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    const found = Object.entries(sources).flatMap(([file, text]) =>
      text
        .split('\n')
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => NATIVE.test(line) && !line.trim().startsWith('*') && !line.trim().startsWith('//'))
        .map(({ line, i }) => `${file}:${i + 1}: ${line.trim()}`),
    );
    expect(found).toEqual([]);
  });
});
