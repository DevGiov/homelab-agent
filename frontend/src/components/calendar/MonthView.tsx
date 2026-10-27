import React, { useMemo, useState } from 'react';
import { Plus, X } from 'lucide-react';
import type { CalendarEventItem } from '../../api/calendar';
import { buildMonthGrid, DAY_NAMES_SHORT, DEFAULT_CALENDAR_COLOR, eventStartTime } from '../../utils/calendarDates';

interface MonthViewProps {
  currentDate: Date;
  eventsByDate: Map<string, CalendarEventItem[]>;
  onNewEvent: (dateStr: string) => void;
  onOpenEvent: (event: CalendarEventItem) => void;
}

const MOBILE_BREAKPOINT = 640;

/** Griglia mensile: pillole degli eventi su desktop, puntini e dettaglio del giorno toccato su mobile. */
export const MonthView: React.FC<MonthViewProps> = ({ currentDate, eventsByDate, onNewEvent, onOpenEvent }) => {
  const [mobileSelectedDate, setMobileSelectedDate] = useState<string | null>(null);
  const days = useMemo(() => buildMonthGrid(currentDate), [currentDate]);
  const selectedEvents = mobileSelectedDate ? eventsByDate.get(mobileSelectedDate) ?? [] : [];

  const handleDayClick = (dateStr: string) => {
    if (window.innerWidth < MOBILE_BREAKPOINT) {
      setMobileSelectedDate(dateStr === mobileSelectedDate ? null : dateStr);
    } else {
      onNewEvent(dateStr);
    }
  };

  const openEvent = (e: React.MouseEvent, ev: CalendarEventItem) => {
    e.stopPropagation();
    onOpenEvent(ev);
  };

  return (
    <div className="flex-1 flex flex-col glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30">
      <div className="grid grid-cols-7 border-b border-border/60 bg-panel-header/60 text-center py-2 text-xs font-semibold text-fg-muted">
        {DAY_NAMES_SHORT.map((d, i) => (
          <div key={d} className={i >= 5 ? 'text-fg-muted/60' : ''}>
            {d}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 flex-1 auto-rows-fr divide-x divide-y divide-border/40 bg-panel/10">
        {days.map((day) => {
          const dayEvents = eventsByDate.get(day.dateStr) ?? [];
          return (
            <div
              key={day.dateStr}
              onClick={() => handleDayClick(day.dateStr)}
              className={`min-h-[64px] sm:min-h-[100px] p-1 sm:p-2 flex flex-col transition cursor-pointer hover:bg-panel-hover/40 relative group ${
                !day.isCurrentMonth ? 'opacity-35 bg-background/20' : ''
              } ${day.isToday ? 'bg-accent/5' : ''} ${mobileSelectedDate === day.dateStr ? 'ring-2 ring-accent ring-inset' : ''}`}
            >
              <div className="flex items-center justify-between mb-0.5 sm:mb-1">
                <span
                  className={`text-xs font-medium w-5 h-5 sm:w-6 sm:h-6 flex items-center justify-center rounded-full transition ${
                    day.isToday ? 'bg-accent text-white font-bold shadow-sm shadow-accent/40' : 'text-fg-muted group-hover:text-fg'
                  }`}
                >
                  {day.dayNumber}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onNewEvent(day.dateStr);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-fg-muted hover:text-accent rounded transition hidden sm:block"
                  title="Aggiungi evento qui"
                >
                  <Plus size={13} />
                </button>
              </div>

              {/* Mobile: puntini colorati ed eventuale contatore */}
              <div className="flex sm:hidden flex-wrap gap-1 justify-center mt-1">
                {dayEvents.slice(0, 3).map((ev, i) => (
                  <span
                    key={ev.uid || ev.id || i}
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: ev.calendar_color || DEFAULT_CALENDAR_COLOR }}
                  />
                ))}
                {dayEvents.length > 3 && (
                  <span className="text-[9px] text-fg-muted font-bold leading-none">+{dayEvents.length - 3}</span>
                )}
              </div>

              {/* Desktop: pillole complete */}
              <div className="hidden sm:block space-y-1 flex-1 overflow-y-auto max-h-[110px] pr-0.5">
                {dayEvents.map((ev) => {
                  const color = ev.calendar_color || DEFAULT_CALENDAR_COLOR;
                  const time = ev.all_day ? 'Tutto il giorno' : eventStartTime(ev);
                  return (
                    <div
                      key={ev.uid || ev.id}
                      onClick={(e) => openEvent(e, ev)}
                      className="px-2 py-1 rounded-md text-[11px] leading-tight font-medium truncate flex items-center gap-1.5 transition shadow-sm hover:scale-[1.01]"
                      style={{ backgroundColor: `${color}20`, borderLeft: `3px solid ${color}`, color: 'var(--fg)' }}
                      title={`${time} - ${ev.summary}${ev.location ? ` @ ${ev.location}` : ''}`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <span className="text-[10px] text-fg-muted shrink-0 font-mono">{ev.all_day ? 'ALL' : time}</span>
                      <span className="truncate">{ev.summary}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {mobileSelectedDate && (
        <div className="sm:hidden border-t border-border/70 p-3 bg-panel/95 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">Eventi del {mobileSelectedDate}</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => onNewEvent(mobileSelectedDate)}
                className="text-xs text-accent font-medium hover:underline flex items-center gap-1"
              >
                <Plus size={12} /> Aggiungi
              </button>
              <button onClick={() => setMobileSelectedDate(null)} className="text-fg-muted hover:text-fg p-1">
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="space-y-1.5 max-h-36 overflow-y-auto">
            {selectedEvents.length === 0 ? (
              <p className="text-xs text-fg-muted italic py-1">Nessun evento in questa data.</p>
            ) : (
              selectedEvents.map((ev) => (
                <div
                  key={ev.uid || ev.id}
                  onClick={(e) => openEvent(e, ev)}
                  className="p-2 rounded-lg bg-panel-hover/50 border border-border/50 flex items-center justify-between text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ev.calendar_color || DEFAULT_CALENDAR_COLOR }} />
                    <span className="font-medium text-fg truncate">{ev.summary}</span>
                  </div>
                  <span className="text-[10px] text-fg-muted font-mono shrink-0">
                    {ev.all_day ? 'Tutto il giorno' : eventStartTime(ev)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
