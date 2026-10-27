import React, { useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { CalendarEventItem } from '../../api/calendar';
import { useCalendarData } from '../../hooks/useCalendarData';
import { useCalendarNavigation } from '../../hooks/useCalendarNavigation';
import { groupByDate, toMonthKey } from '../../utils/calendarDates';
import { AgendaView } from './AgendaView';
import { CalendarManageModal } from './manage/CalendarManageModal';
import { CalendarSidebar } from './CalendarSidebar';
import { CalendarToolbar } from './CalendarToolbar';
import { EventModal } from './EventModal';
import { MonthView } from './MonthView';
import { WeekView } from './WeekView';

interface CalendarViewProps {
  /** Evento da aprire all'ingresso (link `#event-<uid>` dalla chat). */
  initialEventUid?: string | null;
  onClearInitialEvent?: () => void;
  onOpenMobileSidebar?: () => void;
}

type EventEditor = { event: CalendarEventItem | null; date?: string } | null;

export const CalendarView: React.FC<CalendarViewProps> = ({ initialEventUid, onClearInitialEvent, onOpenMobileSidebar }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isManageOpen, setIsManageOpen] = useState(false);
  const [editor, setEditor] = useState<EventEditor>(null);
  const data = useCalendarData(searchQuery);

  const filteredEvents = useMemo(
    () =>
      data.events.filter(
        (ev) =>
          (data.visibleCalendarIds.size === 0 || data.visibleCalendarIds.has(ev.calendar_id)) &&
          (category === 'all' || ev.category === category)
      ),
    [data.events, data.visibleCalendarIds, category]
  );
  const sortedEvents = useMemo(
    () => [...filteredEvents].sort((a, b) => new Date(a.dtstart).getTime() - new Date(b.dtstart).getTime()),
    [filteredEvents]
  );
  const presentMonths = useMemo(
    () => Array.from(new Set(sortedEvents.filter((ev) => ev.dtstart).map((ev) => toMonthKey(new Date(ev.dtstart))))).sort(),
    [sortedEvents]
  );
  const eventsByDate = useMemo(() => groupByDate(filteredEvents), [filteredEvents]);
  const navigation = useCalendarNavigation(presentMonths);
  const { setCurrentDate } = navigation;

  // Apertura dell'evento richiesto dalla chat appena gli eventi sono caricati
  useEffect(() => {
    if (!initialEventUid) return;
    const target = data.events.find((e) => e.uid === initialEventUid || e.id === initialEventUid);
    if (!target) return;
    setEditor({ event: target });
    if (target.dtstart) setCurrentDate(new Date(target.dtstart));
    onClearInitialEvent?.();
  }, [initialEventUid, data.events, onClearInitialEvent, setCurrentDate]);

  const newEvent = (date?: string) => setEditor({ event: null, date });
  const openEvent = (event: CalendarEventItem) => setEditor({ event });

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-background relative">
      <CalendarToolbar
        navigation={navigation}
        isSyncing={data.isSyncing}
        isSidebarOpen={isSidebarOpen}
        onSync={data.sync}
        onManageCalendars={() => setIsManageOpen(true)}
        onNewEvent={() => newEvent()}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        onOpenMobileSidebar={onOpenMobileSidebar}
      />

      {data.syncMessage && (
        <div className="px-5 py-2 bg-accent/10 border-b border-accent/25 text-xs text-accent flex items-center justify-between">
          <span>{data.syncMessage}</span>
          <button onClick={data.dismissSyncMessage} className="text-fg-muted hover:text-fg">
            ✕
          </button>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden relative">
        <CalendarSidebar
          calendars={data.calendars}
          visibleCalendarIds={data.visibleCalendarIds}
          onToggleCalendar={data.toggleCalendar}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          category={category}
          onCategoryChange={setCategory}
          totalEvents={data.events.length}
          filteredEvents={filteredEvents.length}
          onManageCalendars={() => setIsManageOpen(true)}
          isMobileOpen={isSidebarOpen}
          onCloseMobile={() => setIsSidebarOpen(false)}
        />

        <main className="flex-1 overflow-y-auto p-2 sm:p-6 flex flex-col min-w-0">
          {data.isLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex items-center gap-2 text-fg-muted text-sm">
                <RefreshCw size={18} className="animate-spin text-accent" />
                <span>Caricamento eventi...</span>
              </div>
            </div>
          ) : navigation.viewMode === 'month' ? (
            <MonthView
              currentDate={navigation.currentDate}
              eventsByDate={eventsByDate}
              onNewEvent={newEvent}
              onOpenEvent={openEvent}
            />
          ) : navigation.viewMode === 'week' ? (
            <WeekView
              currentDate={navigation.currentDate}
              eventsByDate={eventsByDate}
              onNewEvent={newEvent}
              onOpenEvent={openEvent}
            />
          ) : (
            <AgendaView
              events={sortedEvents}
              containerRef={navigation.agendaRefs.container}
              todayMarkerRef={navigation.agendaRefs.todayMarker}
              onNewEvent={() => newEvent()}
              onOpenEvent={openEvent}
            />
          )}
        </main>
      </div>

      <EventModal
        isOpen={editor !== null}
        onClose={() => setEditor(null)}
        onSave={data.reload}
        calendars={data.calendars}
        eventToEdit={editor?.event ?? null}
        defaultDate={editor?.date}
      />

      {isManageOpen && (
        <CalendarManageModal calendars={data.calendars} onClose={() => setIsManageOpen(false)} onCalendarsUpdated={data.reload} />
      )}
    </div>
  );
};
