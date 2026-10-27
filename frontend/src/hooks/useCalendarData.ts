import { useCallback, useEffect, useState } from 'react';
import { calendarApi, type CalendarEventItem, type CalendarItem } from '../api/calendar';
import { formatApiError } from '../utils/error';

/** Calendari ed eventi (filtrati per testo dal backend), con visibilità per calendario e sync remota. */
export function useCalendarData(searchQuery: string) {
  const [calendars, setCalendars] = useState<CalendarItem[]>([]);
  const [events, setEvents] = useState<CalendarEventItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [visibleCalendarIds, setVisibleCalendarIds] = useState<Set<string>>(new Set());

  const loadCalendars = useCallback(async () => {
    try {
      const cals = await calendarApi.getCalendars();
      setCalendars(cals);
      setVisibleCalendarIds(new Set(cals.map((c) => c.id)));
    } catch (err) {
      console.error('Errore caricamento calendari:', err);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    setIsLoading(true);
    try {
      setEvents(await calendarApi.getEvents({ query: searchQuery.trim() || undefined }));
    } catch (err) {
      console.error('Errore caricamento eventi:', err);
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery]);

  useEffect(() => {
    loadCalendars();
  }, [loadCalendars]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  const reload = useCallback(() => Promise.all([loadEvents(), loadCalendars()]), [loadEvents, loadCalendars]);

  const sync = async () => {
    setIsSyncing(true);
    setSyncMessage(null);
    try {
      const res = await calendarApi.syncCalendars();
      setSyncMessage(`Sincronizzazione completata: ${res.result?.total_synced || 0} feed processati.`);
      await reload();
    } catch (err) {
      setSyncMessage(`Errore sync: ${formatApiError(err, 'Server non raggiungibile')}`);
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSyncMessage(null), 5000);
    }
  };

  const toggleCalendar = (calendarId: string) =>
    setVisibleCalendarIds((prev) => {
      const next = new Set(prev);
      if (next.has(calendarId)) next.delete(calendarId);
      else next.add(calendarId);
      return next;
    });

  return {
    calendars,
    events,
    isLoading,
    isSyncing,
    syncMessage,
    dismissSyncMessage: () => setSyncMessage(null),
    visibleCalendarIds,
    toggleCalendar,
    reload,
    sync,
  };
}
