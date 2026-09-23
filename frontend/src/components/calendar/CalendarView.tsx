import React, { useState, useEffect, useMemo } from 'react';
import {
  Calendar as CalIcon,
  ChevronLeft,
  ChevronRight,
  Plus,
  RefreshCw,
  Search,
  Filter,
  Clock,
  MapPin,
  Check,
  CalendarDays,
  ExternalLink,
} from 'lucide-react';
import type { CalendarItem, CalendarEventItem } from '../../api/calendarApi';
import { calendarApi } from '../../api/calendarApi';
import { EventModal } from './EventModal';

interface CalendarViewProps {
  initialEventUid?: string | null;
  onClearInitialEvent?: () => void;
}

export const CalendarView: React.FC<CalendarViewProps> = ({
  initialEventUid,
  onClearInitialEvent,
}) => {
  const [calendars, setCalendars] = useState<CalendarItem[]>([]);
  const [events, setEvents] = useState<CalendarEventItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  // Navigazione temporale
  const [currentDate, setCurrentDate] = useState<Date>(new Date());
  const [viewMode, setViewMode] = useState<'month' | 'week' | 'agenda'>('month');

  // Filtri
  const [visibleCalendarIds, setVisibleCalendarIds] = useState<Set<string>>(new Set());
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Modale Evento
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [eventToEdit, setEventToEdit] = useState<CalendarEventItem | null>(null);
  const [selectedDateForNew, setSelectedDateForNew] = useState<string | undefined>(undefined);

  // Caricamento iniziale calendari
  const loadCalendars = async () => {
    try {
      const cals = await calendarApi.getCalendars();
      setCalendars(cals);
      setVisibleCalendarIds(new Set(cals.map(c => c.id)));
    } catch (err) {
      console.error('Errore caricamento calendari:', err);
    }
  };

  // Caricamento eventi
  const loadEvents = async () => {
    setIsLoading(true);
    try {
      const evs = await calendarApi.getEvents({
        query: searchQuery.trim() || undefined,
      });
      setEvents(evs);
    } catch (err) {
      console.error('Errore caricamento eventi:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadCalendars();
  }, []);

  useEffect(() => {
    loadEvents();
  }, [searchQuery]);

  // Se c'è un initialEventUid passato (da chat markdown anchor), aprilo
  useEffect(() => {
    if (!initialEventUid || events.length === 0) return;
    const target = events.find(e => e.uid === initialEventUid || e.id === initialEventUid);
    if (target) {
      setEventToEdit(target);
      setIsModalOpen(true);
      if (target.dtstart) {
        setCurrentDate(new Date(target.dtstart));
      }
      if (onClearInitialEvent) onClearInitialEvent();
    }
  }, [initialEventUid, events, onClearInitialEvent]);

  // Sincronizzazione remota
  const handleSync = async () => {
    setIsSyncing(true);
    setSyncMessage(null);
    try {
      const res = await calendarApi.syncCalendars();
      setSyncMessage(`Sincronizzazione completata: ${res.result?.total_synced || 0} feed processati.`);
      await loadEvents();
      await loadCalendars();
    } catch (err: any) {
      setSyncMessage(`Errore sync: ${err.message || 'Server non raggiungibile'}`);
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSyncMessage(null), 5000);
    }
  };

  // Toggle visibilità singolo calendario
  const toggleCalendarVisibility = (calId: string) => {
    setVisibleCalendarIds(prev => {
      const next = new Set(prev);
      if (next.has(calId)) next.delete(calId);
      else next.add(calId);
      return next;
    });
  };

  // Navigazione
  const handlePrev = () => {
    if (viewMode === 'month') {
      setCurrentDate(prev => new Date(prev.getFullYear(), prev.getMonth() - 1, 1));
    } else if (viewMode === 'week') {
      setCurrentDate(prev => new Date(prev.getTime() - 7 * 24 * 60 * 60 * 1000));
    } else {
      setCurrentDate(prev => new Date(prev.getTime() - 30 * 24 * 60 * 60 * 1000));
    }
  };

  const handleNext = () => {
    if (viewMode === 'month') {
      setCurrentDate(prev => new Date(prev.getFullYear(), prev.getMonth() + 1, 1));
    } else if (viewMode === 'week') {
      setCurrentDate(prev => new Date(prev.getTime() + 7 * 24 * 60 * 60 * 1000));
    } else {
      setCurrentDate(prev => new Date(prev.getTime() + 30 * 24 * 60 * 60 * 1000));
    }
  };

  const handleToday = () => {
    setCurrentDate(new Date());
  };

  // Filtraggio eventi visibili
  const filteredEvents = useMemo(() => {
    return events.filter(ev => {
      if (visibleCalendarIds.size > 0 && !visibleCalendarIds.has(ev.calendar_id)) {
        return false;
      }
      if (selectedCategory !== 'all' && ev.category !== selectedCategory) {
        return false;
      }
      return true;
    });
  }, [events, visibleCalendarIds, selectedCategory]);

  // Helper date
  const monthNames = [
    'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
    'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre'
  ];
  const dayNamesShort = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];

  // Calcolo griglia mese
  const monthDays = useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    const firstDayOfMonth = new Date(year, month, 1);
    const lastDayOfMonth = new Date(year, month + 1, 0);

    // Giorno della settimana dell'1 del mese (0 = Domenica, trasformiamo in 0 = Lunedì)
    let startDayOfWeek = firstDayOfMonth.getDay() - 1;
    if (startDayOfWeek === -1) startDayOfWeek = 6;

    const daysInMonth = lastDayOfMonth.getDate();

    // Giorni mese precedente per riempire l'inizio
    const prevMonthLastDay = new Date(year, month, 0).getDate();
    const days: Array<{
      dateStr: string;
      dayNumber: number;
      isCurrentMonth: boolean;
      isToday: boolean;
    }> = [];

    const todayStr = new Date().toISOString().substring(0, 10);

    for (let i = startDayOfWeek - 1; i >= 0; i--) {
      const dNum = prevMonthLastDay - i;
      const prevM = month === 0 ? 11 : month - 1;
      const prevY = month === 0 ? year - 1 : year;
      const dateStr = `${prevY}-${String(prevM + 1).padStart(2, '0')}-${String(dNum).padStart(2, '0')}`;
      days.push({
        dateStr,
        dayNumber: dNum,
        isCurrentMonth: false,
        isToday: dateStr === todayStr,
      });
    }

    for (let i = 1; i <= daysInMonth; i++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
      days.push({
        dateStr,
        dayNumber: i,
        isCurrentMonth: true,
        isToday: dateStr === todayStr,
      });
    }

    // Riempimento fine griglia a multiplo di 7
    const remaining = (7 - (days.length % 7)) % 7;
    for (let i = 1; i <= remaining; i++) {
      const nextM = month === 11 ? 0 : month + 1;
      const nextY = month === 11 ? year + 1 : year;
      const dateStr = `${nextY}-${String(nextM + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
      days.push({
        dateStr,
        dayNumber: i,
        isCurrentMonth: false,
        isToday: dateStr === todayStr,
      });
    }

    return days;
  }, [currentDate]);

  // Mappa data -> lista eventi del giorno
  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEventItem[]>();
    for (const ev of filteredEvents) {
      const d = ev.dtstart.substring(0, 10);
      if (!map.has(d)) map.set(d, []);
      map.get(d)!.push(ev);
    }
    return map;
  }, [filteredEvents]);

  // Click su giorno per creare evento
  const handleDayClick = (dateStr: string) => {
    setSelectedDateForNew(dateStr);
    setEventToEdit(null);
    setIsModalOpen(true);
  };

  // Click su evento per modificare
  const handleEventClick = (e: React.MouseEvent, ev: CalendarEventItem) => {
    e.stopPropagation();
    setEventToEdit(ev);
    setIsModalOpen(true);
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-background relative">
      {/* Top Navbar / Control Header */}
      <header className="px-5 py-3 border-b border-border/70 glass-panel bg-panel/70 flex flex-wrap items-center justify-between gap-3 shrink-0">
        {/* Sinistra: Navigazione Data */}
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="flex items-center gap-1 bg-input/60 border border-border/60 rounded-xl p-1 shadow-inner">
            <button
              onClick={handlePrev}
              className="p-1.5 hover:bg-panel-hover text-fg-muted hover:text-fg rounded-lg transition cursor-pointer"
              title="Precedente"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={handleToday}
              className="px-2.5 py-1 text-xs font-medium text-fg hover:bg-panel-hover rounded-lg transition cursor-pointer"
            >
              Oggi
            </button>
            <button
              onClick={handleNext}
              className="p-1.5 hover:bg-panel-hover text-fg-muted hover:text-fg rounded-lg transition cursor-pointer"
              title="Successivo"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <h2 className="text-base sm:text-lg font-semibold text-fg tracking-tight min-w-[160px]">
            {monthNames[currentDate.getMonth()]} {currentDate.getFullYear()}
          </h2>
        </div>

        {/* Centro/Destra: View Mode Toggle & Azioni */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Selettore Viste (Mese / Settimana / Agenda) */}
          <div className="flex items-center bg-input/60 border border-border/60 rounded-xl p-1 text-xs shadow-inner">
            <button
              onClick={() => setViewMode('month')}
              className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer ${
                viewMode === 'month'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-fg-muted hover:text-fg'
              }`}
            >
              Mese
            </button>
            <button
              onClick={() => setViewMode('week')}
              className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer ${
                viewMode === 'week'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-fg-muted hover:text-fg'
              }`}
            >
              Settimana
            </button>
            <button
              onClick={() => setViewMode('agenda')}
              className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer ${
                viewMode === 'agenda'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-fg-muted hover:text-fg'
              }`}
            >
              Agenda
            </button>
          </div>

          {/* Sync Button */}
          <button
            onClick={handleSync}
            disabled={isSyncing}
            className="p-2 bg-input/60 hover:bg-panel-hover text-fg-muted hover:text-fg border border-border/60 rounded-xl transition cursor-pointer disabled:opacity-50"
            title="Sincronizza calendari esterni"
          >
            <RefreshCw size={15} className={isSyncing ? 'animate-spin text-accent' : ''} />
          </button>

          {/* Nuovo Evento */}
          <button
            onClick={() => {
              setSelectedDateForNew(undefined);
              setEventToEdit(null);
              setIsModalOpen(true);
            }}
            className="px-3.5 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm shadow-accent/20 transition cursor-pointer"
          >
            <Plus size={15} />
            <span className="hidden sm:inline">Nuovo Evento</span>
          </button>

          {/* Toggle Sidebar Filtri su Mobile */}
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="p-2 md:hidden bg-input/60 text-fg-muted hover:text-fg border border-border/60 rounded-xl transition"
            title="Filtri"
          >
            <Filter size={15} />
          </button>
        </div>
      </header>

      {/* Sync Message Alert */}
      {syncMessage && (
        <div className="px-5 py-2 bg-accent/10 border-b border-accent/25 text-xs text-accent flex items-center justify-between">
          <span>{syncMessage}</span>
          <button onClick={() => setSyncMessage(null)} className="text-fg-muted hover:text-fg">
            ✕
          </button>
        </div>
      )}

      {/* Main Content Area: Sidebar + Grid */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar Filtri & Calendari */}
        <aside
          className={`${
            isSidebarOpen ? 'w-64 border-r' : 'w-0 border-r-0'
          } border-border/60 glass-panel bg-panel/40 flex flex-col shrink-0 transition-all duration-300 overflow-hidden`}
        >
          <div className="p-4 space-y-5 overflow-y-auto flex-1">
            {/* Ricerca Rapida */}
            <div>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-2.5 text-fg-muted" />
                <input
                  type="text"
                  placeholder="Cerca eventi..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 bg-input border border-border/60 rounded-xl text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent transition"
                />
              </div>
            </div>

            {/* Lista Calendari */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-fg-muted tracking-wider uppercase">
                  I Miei Calendari
                </span>
                <span className="text-[10px] text-fg-muted bg-panel px-1.5 py-0.5 rounded-full border border-border/50">
                  {calendars.length}
                </span>
              </div>

              <div className="space-y-1.5">
                {calendars.map(c => {
                  const isChecked = visibleCalendarIds.has(c.id);
                  return (
                    <div
                      key={c.id}
                      onClick={() => toggleCalendarVisibility(c.id)}
                      className={`px-2.5 py-1.5 rounded-xl border flex items-center justify-between text-xs cursor-pointer transition select-none ${
                        isChecked
                          ? 'bg-panel-hover/50 border-border/70 text-fg'
                          : 'bg-transparent border-transparent text-fg-muted/60 hover:bg-panel-hover/30'
                      }`}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0 shadow-sm"
                          style={{ backgroundColor: c.color || '#3b82f6' }}
                        />
                        <span className="truncate font-medium">{c.name}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {c.event_count !== undefined && (
                          <span className="text-[10px] text-fg-muted">{c.event_count}</span>
                        )}
                        <div
                          className={`w-3.5 h-3.5 rounded flex items-center justify-center border transition ${
                            isChecked
                              ? 'bg-accent border-accent text-white'
                              : 'border-border/80 bg-input'
                          }`}
                        >
                          {isChecked && <Check size={10} strokeWidth={3} />}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Filtro Categorie */}
            <div>
              <span className="text-[11px] font-semibold text-fg-muted tracking-wider uppercase block mb-2">
                Categorie
              </span>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { id: 'all', label: 'Tutte' },
                  { id: 'meeting', label: 'Meeting' },
                  { id: 'personal', label: 'Personale' },
                  { id: 'homelab', label: 'Homelab' },
                  { id: 'flight', label: 'Viaggi' },
                  { id: 'reminder', label: 'Promemoria' },
                ].map(cat => (
                  <button
                    key={cat.id}
                    onClick={() => setSelectedCategory(cat.id)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition cursor-pointer border ${
                      selectedCategory === cat.id
                        ? 'bg-accent/15 border-accent/40 text-accent font-semibold'
                        : 'bg-input/40 border-border/40 text-fg-muted hover:text-fg hover:bg-panel-hover'
                    }`}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Quick Summary Card */}
            <div className="p-3 bg-panel-header/40 border border-border/50 rounded-xl space-y-1.5 text-xs">
              <div className="flex items-center justify-between text-fg-muted">
                <span>Eventi totali</span>
                <span className="font-semibold text-fg">{events.length}</span>
              </div>
              <div className="flex items-center justify-between text-fg-muted">
                <span>Eventi filtrati</span>
                <span className="font-semibold text-accent">{filteredEvents.length}</span>
              </div>
            </div>
          </div>
        </aside>

        {/* Vista Principale Calendario */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col">
          {isLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex items-center gap-2 text-fg-muted text-sm">
                <RefreshCw size={18} className="animate-spin text-accent" />
                <span>Caricamento eventi...</span>
              </div>
            </div>
          ) : viewMode === 'month' ? (
            /* --- GRIGLIA MESE --- */
            <div className="flex-1 flex flex-col glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30">
              {/* Header Giorni della Settimana */}
              <div className="grid grid-cols-7 border-b border-border/60 bg-panel-header/60 text-center py-2.5 text-xs font-semibold text-fg-muted">
                {dayNamesShort.map((d, i) => (
                  <div key={d} className={i >= 5 ? 'text-fg-muted/60' : ''}>
                    {d}
                  </div>
                ))}
              </div>

              {/* Griglia Giorni */}
              <div className="grid grid-cols-7 flex-1 auto-rows-fr divide-x divide-y divide-border/40 bg-panel/10">
                {monthDays.map(day => {
                  const dayEvents = eventsByDate.get(day.dateStr) || [];
                  return (
                    <div
                      key={day.dateStr}
                      onClick={() => handleDayClick(day.dateStr)}
                      className={`min-h-[100px] p-1.5 sm:p-2 flex flex-col transition cursor-pointer hover:bg-panel-hover/40 relative group ${
                        !day.isCurrentMonth ? 'opacity-35 bg-background/20' : ''
                      } ${day.isToday ? 'bg-accent/5' : ''}`}
                    >
                      {/* Intestazione Cella Giorno */}
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className={`text-xs font-medium w-6 h-6 flex items-center justify-center rounded-full transition ${
                            day.isToday
                              ? 'bg-accent text-white font-bold shadow-sm shadow-accent/40'
                              : 'text-fg-muted group-hover:text-fg'
                          }`}
                        >
                          {day.dayNumber}
                        </span>

                        <button
                          onClick={e => {
                            e.stopPropagation();
                            handleDayClick(day.dateStr);
                          }}
                          className="opacity-0 group-hover:opacity-100 p-0.5 text-fg-muted hover:text-accent rounded transition"
                          title="Aggiungi evento qui"
                        >
                          <Plus size={13} />
                        </button>
                      </div>

                      {/* Lista Pillole Eventi */}
                      <div className="space-y-1 flex-1 overflow-y-auto max-h-[110px] pr-0.5">
                        {dayEvents.map(ev => {
                          const calColor = ev.calendar_color || '#3b82f6';
                          const timeStr = ev.all_day
                            ? 'Tutto il giorno'
                            : ev.dtstart.substring(11, 16);

                          return (
                            <div
                              key={ev.uid || ev.id}
                              onClick={e => handleEventClick(e, ev)}
                              className="px-2 py-1 rounded-md text-[11px] leading-tight font-medium truncate flex items-center gap-1.5 transition shadow-sm hover:scale-[1.01]"
                              style={{
                                backgroundColor: `${calColor}20`,
                                borderLeft: `3px solid ${calColor}`,
                                color: 'var(--fg)',
                              }}
                              title={`${timeStr} - ${ev.summary}${ev.location ? ` @ ${ev.location}` : ''}`}
                            >
                              <span
                                className="w-1.5 h-1.5 rounded-full shrink-0"
                                style={{ backgroundColor: calColor }}
                              />
                              <span className="text-[10px] text-fg-muted shrink-0 font-mono">
                                {ev.all_day ? 'ALL' : timeStr}
                              </span>
                              <span className="truncate">{ev.summary}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : viewMode === 'week' ? (
            /* --- VISTA SETTIMANA --- */
            <div className="flex-1 flex flex-col glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30">
              <div className="p-4 border-b border-border/60 bg-panel-header/60 flex items-center justify-between">
                <span className="text-xs font-semibold text-fg-muted uppercase">Vista Settimanale</span>
                <span className="text-xs text-fg-muted">Dettaglio orario appuntamenti</span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {/* 7 Giorni della settimana corrente */}
                {Array.from({ length: 7 }).map((_, idx) => {
                  const curr = new Date(currentDate);
                  const first = curr.getDate() - (curr.getDay() === 0 ? 6 : curr.getDay() - 1);
                  const dayDate = new Date(curr.setDate(first + idx));
                  const dateStr = dayDate.toISOString().substring(0, 10);
                  const dayEvents = eventsByDate.get(dateStr) || [];
                  const isToday = dateStr === new Date().toISOString().substring(0, 10);

                  return (
                    <div
                      key={dateStr}
                      onClick={() => handleDayClick(dateStr)}
                      className={`p-3 rounded-xl border transition cursor-pointer hover:border-accent/40 ${
                        isToday
                          ? 'bg-accent/10 border-accent/30'
                          : 'bg-panel/40 border-border/50'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-lg ${isToday ? 'bg-accent text-white' : 'bg-input text-fg'}`}>
                            {dayNamesShort[idx]} {dayDate.getDate()} {monthNames[dayDate.getMonth()].substring(0, 3)}
                          </span>
                          {isToday && <span className="text-[10px] text-accent font-semibold uppercase tracking-wider">Oggi</span>}
                        </div>
                        <span className="text-xs text-fg-muted">{dayEvents.length} eventi</span>
                      </div>

                      {dayEvents.length === 0 ? (
                        <p className="text-xs text-fg-muted/50 italic py-1">Nessun impegno pianificato</p>
                      ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                          {dayEvents.map(ev => (
                            <div
                              key={ev.uid || ev.id}
                              onClick={e => handleEventClick(e, ev)}
                              className="p-2.5 rounded-xl border border-border/60 bg-panel hover:bg-panel-hover flex items-start justify-between gap-2 shadow-sm transition"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ev.calendar_color || '#3b82f6' }} />
                                  <span className="text-xs font-semibold text-fg truncate">{ev.summary}</span>
                                </div>
                                <div className="text-[11px] text-fg-muted flex items-center gap-2">
                                  <span className="flex items-center gap-1">
                                    <Clock size={11} />
                                    {ev.all_day ? 'Tutto il giorno' : `${ev.dtstart.substring(11, 16)} - ${ev.dtend.substring(11, 16)}`}
                                  </span>
                                  {ev.location && (
                                    <span className="truncate flex items-center gap-0.5">
                                      <MapPin size={11} /> {ev.location}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            /* --- VISTA AGENDA --- */
            <div className="flex-1 glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30 flex flex-col">
              <div className="p-4 border-b border-border/60 bg-panel-header/60 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CalendarDays size={16} className="text-accent" />
                  <span className="text-xs font-semibold text-fg uppercase">Agenda Cronologica</span>
                </div>
                <span className="text-xs text-fg-muted">Tutti gli eventi in ordine temporale</span>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {filteredEvents.length === 0 ? (
                  <div className="py-12 text-center text-fg-muted text-sm space-y-2">
                    <p>Nessun evento trovato nei calendari selezionati.</p>
                    <button
                      onClick={() => setIsModalOpen(true)}
                      className="px-3.5 py-1.5 bg-accent/20 hover:bg-accent/30 text-accent rounded-xl text-xs font-medium inline-flex items-center gap-1.5 transition"
                    >
                      <Plus size={14} /> Crea il tuo primo evento
                    </button>
                  </div>
                ) : (
                  filteredEvents.map(ev => {
                    const dateObj = new Date(ev.dtstart);
                    const formattedDate = `${dateObj.getDate()} ${monthNames[dateObj.getMonth()]} ${dateObj.getFullYear()}`;
                    const timeRange = ev.all_day
                      ? 'Tutto il giorno'
                      : `${ev.dtstart.substring(11, 16)} → ${ev.dtend.substring(11, 16)}`;

                    return (
                      <div
                        key={ev.uid || ev.id}
                        onClick={e => handleEventClick(e, ev)}
                        className="p-3.5 rounded-xl border border-border/60 bg-panel hover:bg-panel-hover flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm transition cursor-pointer group"
                      >
                        <div className="flex items-start gap-3 min-w-0">
                          <div
                            className="w-3.5 h-3.5 rounded-full shrink-0 mt-1 shadow-sm"
                            style={{ backgroundColor: ev.calendar_color || '#3b82f6' }}
                          />
                          <div className="space-y-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h4 className="font-semibold text-sm text-fg truncate group-hover:text-accent transition">
                                {ev.summary}
                              </h4>
                              {ev.category && (
                                <span className="px-2 py-0.5 rounded-md bg-input text-[10px] text-fg-muted font-medium border border-border/50 uppercase">
                                  {ev.category}
                                </span>
                              )}
                              {ev.importance === 'high' || ev.importance === 'critical' ? (
                                <span className="px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-400 text-[10px] font-medium border border-rose-500/30">
                                  {ev.importance}
                                </span>
                              ) : null}
                            </div>

                            <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
                              <span className="flex items-center gap-1">
                                <CalIcon size={12} /> {formattedDate}
                              </span>
                              <span className="flex items-center gap-1 font-mono text-[11px]">
                                <Clock size={12} /> {timeRange}
                              </span>
                              {ev.location && (
                                <span className="flex items-center gap-1 truncate max-w-[200px]">
                                  <MapPin size={12} /> {ev.location}
                                </span>
                              )}
                            </div>

                            {ev.description && (
                              <p className="text-xs text-fg-muted/80 line-clamp-1">
                                {ev.description}
                              </p>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                          {ev.location && (ev.location.startsWith('http://') || ev.location.startsWith('https://')) && (
                            <a
                              href={ev.location}
                              target="_blank"
                              rel="noreferrer"
                              onClick={e => e.stopPropagation()}
                              className="px-2.5 py-1 bg-accent/15 hover:bg-accent/25 text-accent rounded-lg text-xs font-medium flex items-center gap-1 transition"
                            >
                              <span>Partecipa</span>
                              <ExternalLink size={12} />
                            </a>
                          )}
                          <span className="text-xs text-fg-muted opacity-0 group-hover:opacity-100 transition">
                            Modifica →
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Modale Creazione / Modifica Evento */}
      <EventModal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setEventToEdit(null);
          setSelectedDateForNew(undefined);
        }}
        onSave={() => {
          loadEvents();
          loadCalendars();
        }}
        calendars={calendars}
        eventToEdit={eventToEdit}
        defaultDate={selectedDateForNew}
      />
    </div>
  );
};
