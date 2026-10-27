import React, { useMemo, type RefObject } from 'react';
import { Calendar as CalIcon, CalendarDays, Clock, ExternalLink, MapPin, Plus } from 'lucide-react';
import type { CalendarEventItem } from '../../api/calendar';
import {
  DEFAULT_CALENDAR_COLOR,
  eventEndTime,
  eventStartTime,
  groupByMonth,
  MONTH_NAMES,
} from '../../utils/calendarDates';

interface AgendaViewProps {
  /** Eventi già ordinati per inizio. */
  events: CalendarEventItem[];
  containerRef: RefObject<HTMLDivElement | null>;
  todayMarkerRef: RefObject<HTMLDivElement | null>;
  onNewEvent: () => void;
  onOpenEvent: (event: CalendarEventItem) => void;
}

const TodayMarker: React.FC<{ markerRef: RefObject<HTMLDivElement | null> }> = ({ markerRef }) => {
  const now = new Date();
  return (
    <div
      ref={markerRef}
      id="agenda-today-marker"
      className="my-3 py-2 px-3 rounded-xl bg-accent/15 border border-accent/40 flex items-center justify-between shadow-sm animate-in fade-in duration-300"
    >
      <div className="flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse" />
        <span className="font-bold text-xs text-accent uppercase tracking-wider">
          Oggi — {now.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
        </span>
      </div>
      <span className="text-[10px] text-fg-muted font-mono">
        {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </span>
    </div>
  );
};

const isUrl = (value?: string) => Boolean(value && (value.startsWith('http://') || value.startsWith('https://')));

const AgendaEvent: React.FC<{ event: CalendarEventItem; onOpen: () => void }> = ({ event: ev, onOpen }) => {
  const start = new Date(ev.dtstart);
  const timeRange = ev.all_day ? 'Tutto il giorno' : `${eventStartTime(ev)} → ${eventEndTime(ev)}`;
  const isImportant = ev.importance === 'high' || ev.importance === 'critical';

  return (
    <div
      onClick={onOpen}
      className="p-3.5 rounded-xl border border-border/60 bg-panel hover:bg-panel-hover flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm transition cursor-pointer group"
    >
      <div className="flex items-start gap-3 min-w-0">
        <div
          className="w-3.5 h-3.5 rounded-full shrink-0 mt-1 shadow-sm"
          style={{ backgroundColor: ev.calendar_color || DEFAULT_CALENDAR_COLOR }}
        />
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="font-semibold text-sm text-fg truncate group-hover:text-accent transition">{ev.summary}</h4>
            {ev.category && (
              <span className="px-2 py-0.5 rounded-md bg-input-bg text-[10px] text-fg-muted font-medium border border-input-border uppercase">
                {ev.category}
              </span>
            )}
            {isImportant && (
              <span className="px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-400 text-[10px] font-medium border border-rose-500/30">
                {ev.importance}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
            <span className="flex items-center gap-1">
              <CalIcon size={12} /> {start.getDate()} {MONTH_NAMES[start.getMonth()]} {start.getFullYear()}
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

          {ev.description && <p className="text-xs text-fg-muted/80 line-clamp-1">{ev.description}</p>}
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
        {isUrl(ev.location) && (
          <a
            href={ev.location}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="px-2.5 py-1 bg-accent/15 hover:bg-accent/25 text-accent rounded-lg text-xs font-medium flex items-center gap-1 transition"
          >
            <span>Partecipa</span>
            <ExternalLink size={12} />
          </a>
        )}
        <span className="text-xs text-fg-muted opacity-0 group-hover:opacity-100 transition">Modifica →</span>
      </div>
    </div>
  );
};

/** Lista cronologica raggruppata per mese, con il marcatore "Oggi" prima del primo evento non ancora concluso. */
export const AgendaView: React.FC<AgendaViewProps> = ({ events, containerRef, todayMarkerRef, onNewEvent, onOpenEvent }) => {
  const groups = useMemo(() => groupByMonth(events), [events]);
  const todayIndex = useMemo(() => {
    const now = Date.now();
    const idx = events.findIndex((ev) => new Date(ev.dtend || ev.dtstart).getTime() >= now);
    return idx === -1 ? events.length : idx;
  }, [events]);

  return (
    <div className="flex-1 glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30 flex flex-col">
      <div className="p-4 border-b border-border/60 bg-panel-header/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CalendarDays size={16} className="text-accent" />
          <span className="text-xs font-semibold text-fg uppercase">Agenda Cronologica</span>
        </div>
        <span className="text-xs text-fg-muted">{events.length} eventi totali</span>
      </div>

      <div ref={containerRef} className="flex-1 overflow-y-auto p-4 space-y-6 custom-scrollbar">
        {events.length === 0 ? (
          <div className="py-12 text-center text-fg-muted text-sm space-y-2">
            <p>Nessun evento trovato nei calendari selezionati.</p>
            <button
              onClick={onNewEvent}
              className="px-3.5 py-1.5 bg-accent/20 hover:bg-accent/30 text-accent rounded-xl text-xs font-medium inline-flex items-center gap-1.5 transition"
            >
              <Plus size={14} /> Crea il tuo primo evento
            </button>
          </div>
        ) : (
          <>
            {groups.map((group) => (
              <div key={group.monthKey} id={`agenda-month-${group.monthKey}`} className="space-y-3">
                <div className="pt-3 pb-1.5 border-b border-border/80 flex items-center justify-between sticky top-0 bg-panel/95 backdrop-blur-md z-10">
                  <div className="flex items-center gap-2">
                    <CalendarDays size={15} className="text-accent" />
                    <h3 className="font-bold text-xs sm:text-sm text-fg tracking-wide uppercase">
                      {MONTH_NAMES[group.month.getMonth()]} {group.month.getFullYear()}
                    </h3>
                  </div>
                  <span className="text-[11px] text-fg-muted">
                    {group.events.length} {group.events.length === 1 ? 'evento' : 'eventi'}
                  </span>
                </div>

                <div className="space-y-3">
                  {group.events.map((ev) => {
                    const index = events.indexOf(ev);
                    return (
                      <React.Fragment key={ev.uid || ev.id || index}>
                        {index === todayIndex && <TodayMarker markerRef={todayMarkerRef} />}
                        <AgendaEvent event={ev} onOpen={() => onOpenEvent(ev)} />
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            ))}

            {/* Tutti gli eventi sono nel passato: il marcatore "Oggi" va in fondo */}
            {todayIndex >= events.length && <TodayMarker markerRef={todayMarkerRef} />}
          </>
        )}
      </div>
    </div>
  );
};
