import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarEventItem } from '../api/calendar';
import { buildMonthGrid, groupByDate, groupByMonth, mondayOf, toDateKey, weekDays, weekRangeTitle } from './calendarDates';

const event = (dtstart: string, summary = dtstart) => ({ dtstart, dtend: dtstart, summary }) as CalendarEventItem;

afterEach(() => vi.useRealTimers());

describe('buildMonthGrid', () => {
  it('parte dal lunedì e copre settimane intere', () => {
    const days = buildMonthGrid(new Date(2026, 9, 15)); // ottobre 2026: l'1 è giovedì
    expect(days[0].dateStr).toBe('2026-09-28');
    expect(days.at(-1)?.dateStr).toBe('2026-11-01');
    expect(days).toHaveLength(35);
    expect(days.filter((d) => d.isCurrentMonth)).toHaveLength(31);
  });

  it('non aggiunge righe nei mesi con il cambio dell\'ora legale', () => {
    // marzo 2026 (ora legale dal 29) e febbraio 2026 (inizia di domenica e finisce di sabato: 5 settimane)
    expect(buildMonthGrid(new Date(2026, 2, 1))).toHaveLength(42);
    expect(buildMonthGrid(new Date(2026, 1, 1))).toHaveLength(35);
    expect(buildMonthGrid(new Date(2026, 9, 1)).every((d, i, all) => i === 0 || d.dateStr > all[i - 1].dateStr)).toBe(true);
  });

  it('marca oggi in data locale anche poco dopo mezzanotte', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 27, 0, 30)); // in UTC sarebbe ancora il 26
    const today = buildMonthGrid(new Date(2026, 9, 1)).filter((d) => d.isToday);
    expect(today.map((d) => d.dateStr)).toEqual(['2026-10-27']);
  });
});

describe('settimana', () => {
  it('il lunedì della settimana di una domenica è quello precedente', () => {
    expect(toDateKey(mondayOf(new Date(2026, 9, 25)))).toBe('2026-10-19');
    expect(weekDays(new Date(2026, 9, 25)).map(toDateKey)).toEqual([
      '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24', '2026-10-25',
    ]);
  });

  it.each([
    [new Date(2026, 8, 16), '14 - 20 Settembre 2026'],
    [new Date(2026, 8, 30), '28 Settembre - 4 Ottobre 2026'],
    [new Date(2026, 11, 30), '28 Dicembre 2026 - 3 Gennaio 2027'],
  ])('titolo della settimana del %s', (date, title) => {
    expect(weekRangeTitle(date)).toBe(title);
  });
});

describe('raggruppamenti', () => {
  it('per giorno, dalla data di inizio', () => {
    const map = groupByDate([event('2026-10-27T10:00:00'), event('2026-10-27T18:00:00'), event('2026-10-28T09:00:00')]);
    expect(map.get('2026-10-27')).toHaveLength(2);
    expect(map.get('2026-10-28')).toHaveLength(1);
  });

  it('per mese, mantenendo l\'ordine degli eventi', () => {
    const groups = groupByMonth([event('2026-09-30T10:00:00', 'a'), event('2026-10-01T10:00:00', 'b'), event('2026-10-20T10:00:00', 'c')]);
    expect(groups.map((g) => [g.monthKey, g.events.map((e) => e.summary)])).toEqual([
      ['2026-09', ['a']],
      ['2026-10', ['b', 'c']],
    ]);
  });
});
