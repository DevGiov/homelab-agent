import { useCallback, useEffect, useRef, useState } from 'react';
import { monthStartFromKey, toMonthKey } from '../utils/calendarDates';

export type CalendarViewMode = 'month' | 'week' | 'agenda';

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Data corrente e vista del calendario. In agenda la navigazione salta tra i mesi che hanno eventi
 * (`presentMonths`, chiavi `YYYY-MM` ordinate) e scorre la lista fino al mese o al marcatore di oggi.
 */
export function useCalendarNavigation(presentMonths: string[]) {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [viewMode, setViewMode] = useState<CalendarViewMode>('month');
  const agendaContainerRef = useRef<HTMLDivElement>(null);
  const todayMarkerRef = useRef<HTMLDivElement>(null);

  const scrollToMonth = (monthKey: string) => {
    const container = agendaContainerRef.current;
    const target = document.getElementById(`agenda-month-${monthKey}`);
    if (!container || !target) return;
    const offset = target.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
    container.scrollTo({ top: Math.max(0, offset - 8), behavior: 'smooth' });
  };

  /** Centra il marcatore "Oggi" nella lista; false se l'agenda non è montata. */
  const scrollToToday = useCallback(() => {
    const container = agendaContainerRef.current;
    const marker = todayMarkerRef.current;
    if (!container || !marker) return false;
    const markerRect = marker.getBoundingClientRect();
    const top =
      markerRect.top - container.getBoundingClientRect().top + container.scrollTop - container.clientHeight / 2 + markerRect.height / 2;
    container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    return true;
  }, []);

  const jumpToMonth = (monthKey: string | undefined) => {
    if (!monthKey) return;
    setCurrentDate(monthStartFromKey(monthKey));
    scrollToMonth(monthKey);
  };

  const prev = () => {
    if (viewMode === 'month') setCurrentDate((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1));
    else if (viewMode === 'week') setCurrentDate((d) => new Date(d.getTime() - WEEK_MS));
    else jumpToMonth(presentMonths.filter((k) => k < toMonthKey(currentDate)).at(-1) ?? presentMonths[0]);
  };

  const next = () => {
    if (viewMode === 'month') setCurrentDate((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1));
    else if (viewMode === 'week') setCurrentDate((d) => new Date(d.getTime() + WEEK_MS));
    else jumpToMonth(presentMonths.find((k) => k > toMonthKey(currentDate)));
  };

  const today = () => {
    const now = new Date();
    setCurrentDate(now);
    if (viewMode === 'agenda' && !scrollToToday()) scrollToMonth(toMonthKey(now));
  };

  const selectMonth = (monthIdx: number, year: number) => {
    const target = new Date(year, monthIdx, 1);
    setCurrentDate(target);
    if (viewMode !== 'agenda') return;
    // Mese senza eventi: il più vicino precedente, altrimenti il primo disponibile
    const key = toMonthKey(target);
    const jumpKey = presentMonths.includes(key) ? key : presentMonths.filter((k) => k <= key).at(-1) ?? presentMonths[0];
    if (jumpKey) setTimeout(() => scrollToMonth(jumpKey), 50);
  };

  const shiftYear = (delta: number) => setCurrentDate((d) => new Date(d.getFullYear() + delta, d.getMonth(), 1));

  // Entrando in agenda la lista si posiziona su oggi
  useEffect(() => {
    if (viewMode !== 'agenda') return;
    const timer = setTimeout(scrollToToday, 150);
    return () => clearTimeout(timer);
  }, [viewMode, scrollToToday]);

  return {
    currentDate,
    setCurrentDate,
    viewMode,
    setViewMode,
    prev,
    next,
    today,
    selectMonth,
    shiftYear,
    agendaRefs: { container: agendaContainerRef, todayMarker: todayMarkerRef },
  };
}

export type CalendarNavigation = ReturnType<typeof useCalendarNavigation>;
