// Calcoli di data per le viste del calendario (settimana da lunedì, date locali).
import type { CalendarEventItem } from '../api/calendar';

export const MONTH_NAMES = [
  'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
  'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre',
];
export const DAY_NAMES_SHORT = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];
export const DEFAULT_CALENDAR_COLOR = '#3b82f6';

const pad = (n: number) => String(n).padStart(2, '0');

/** `YYYY-MM-DD` nel fuso locale (toISOString userebbe UTC e sbaglierebbe giorno vicino alla mezzanotte). */
export const toDateKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** `YYYY-MM`, chiave dei gruppi mensili dell'agenda. */
export const toMonthKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;

export const monthStartFromKey = (key: string) => {
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m - 1, 1);
};

/** Lunedì della settimana che contiene `date`. */
export function mondayOf(date: Date): Date {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  return monday;
}

export function weekDays(date: Date): Date[] {
  const monday = mondayOf(date);
  return Array.from({ length: 7 }, (_, i) => new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i));
}

/** Titolo dell'intervallo settimanale, es. "14 - 20 Settembre 2026". */
export function weekRangeTitle(date: Date): string {
  const days = weekDays(date);
  const [monday, sunday] = [days[0], days[6]];
  const start = `${monday.getDate()} ${MONTH_NAMES[monday.getMonth()]}`;
  const end = `${sunday.getDate()} ${MONTH_NAMES[sunday.getMonth()]} ${sunday.getFullYear()}`;
  if (monday.getFullYear() !== sunday.getFullYear()) return `${start} ${monday.getFullYear()} - ${end}`;
  if (monday.getMonth() !== sunday.getMonth()) return `${start} - ${end}`;
  return `${monday.getDate()} - ${end}`;
}

export interface MonthGridDay {
  dateStr: string;
  dayNumber: number;
  isCurrentMonth: boolean;
  isToday: boolean;
}

/** Celle della griglia mensile: dal lunedì prima dell'1 alla domenica dopo l'ultimo giorno. */
export function buildMonthGrid(date: Date): MonthGridDay[] {
  const year = date.getFullYear();
  const month = date.getMonth();
  const first = mondayOf(new Date(year, month, 1));
  const last = new Date(year, month + 1, 0);
  // round: con il cambio dell'ora legale la differenza tra due mezzanotti non è un multiplo esatto di 24 h
  const daySpan = Math.round((last.getTime() - first.getTime()) / 86_400_000) + 1;
  const cellCount = Math.ceil(daySpan / 7) * 7;
  const today = toDateKey(new Date());

  return Array.from({ length: cellCount }, (_, i) => {
    const day = new Date(first.getFullYear(), first.getMonth(), first.getDate() + i);
    const dateStr = toDateKey(day);
    return { dateStr, dayNumber: day.getDate(), isCurrentMonth: day.getMonth() === month, isToday: dateStr === today };
  });
}

export function groupByDate(events: CalendarEventItem[]): Map<string, CalendarEventItem[]> {
  const map = new Map<string, CalendarEventItem[]>();
  for (const ev of events) {
    const key = ev.dtstart.substring(0, 10);
    map.set(key, [...(map.get(key) ?? []), ev]);
  }
  return map;
}

export interface AgendaMonth {
  monthKey: string;
  month: Date;
  events: CalendarEventItem[];
}

/** Eventi già ordinati raggruppati per mese. */
export function groupByMonth(sortedEvents: CalendarEventItem[]): AgendaMonth[] {
  const groups: AgendaMonth[] = [];
  for (const ev of sortedEvents) {
    if (!ev.dtstart) continue;
    const start = new Date(ev.dtstart);
    const monthKey = toMonthKey(start);
    if (groups.at(-1)?.monthKey !== monthKey) {
      groups.push({ monthKey, month: new Date(start.getFullYear(), start.getMonth(), 1), events: [] });
    }
    groups.at(-1)!.events.push(ev);
  }
  return groups;
}

export const eventStartTime = (ev: CalendarEventItem) => ev.dtstart.substring(11, 16);
export const eventEndTime = (ev: CalendarEventItem) => ev.dtend.substring(11, 16);
