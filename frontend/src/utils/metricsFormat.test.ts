import { describe, expect, it } from 'vitest';
import { formatCompact, formatDuration, formatPct, formatRate, niceScale } from './metricsFormat';

describe('metricsFormat', () => {
  it('formatta le durate per ordine di grandezza', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(850)).toBe('850 ms');
    expect(formatDuration(4200)).toBe('4,2 s');
    expect(formatDuration(190_000)).toBe('3 min 10 s');
    expect(formatDuration(120_000)).toBe('2 min');
  });

  it('compatta i numeri grandi e lascia i piccoli', () => {
    expect(formatCompact(950)).toBe('950');
    expect(formatCompact(1284)).toMatch(/^1,3\s?K$/i);
    expect(formatRate(null)).toBe('—');
    expect(formatRate(42.25)).toBe('42,3 tok/s');
    expect(formatRate(1834.4)).toBe('1834 tok/s');
    expect(formatPct(99.5)).toBe('99,5%');
  });

  it('sceglie tick a passo pulito che coprono il massimo', () => {
    expect(niceScale(0)).toEqual([0, 1]);
    expect(niceScale(7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceScale(9300)).toEqual([0, 2500, 5000, 7500, 10000]);
    expect(niceScale(0.8)).toEqual([0, 0.2, 0.4, 0.6, 0.8]);
  });
});
