import { describe, expect, it, vi } from 'vitest';
import { scrollBehavior } from './motion';

const stubMotion = (reduce: boolean) =>
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: reduce && query === '(prefers-reduced-motion: reduce)' }));

describe('scrollBehavior', () => {
  it('scorre in modo morbido di default', () => {
    stubMotion(false);
    expect(scrollBehavior()).toBe('smooth');
  });

  it('salta direttamente con il movimento ridotto', () => {
    stubMotion(true);
    expect(scrollBehavior()).toBe('auto');
  });
});
