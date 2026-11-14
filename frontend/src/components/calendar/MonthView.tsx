import React, { useId, useMemo, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import type { CalendarEventItem } from '../../api/calendar';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { buildMonthGrid, DAY_NAMES_SHORT, dayLabel, DEFAULT_CALENDAR_COLOR, eventStartTime } from '../../utils/calendarDates';

interface MonthViewProps {
  currentDate: Date;
  eventsByDate: Map<string, CalendarEventItem[]>;
  onNewEvent: (dateStr: string) => void;
  onOpenEvent: (event: CalendarEventItem) => void;
}

/**
 * Griglia mensile: pillole degli eventi su desktop, puntini e dettaglio del giorno toccato su mobile.
 * Da tastiera ogni giorno è il pulsante col suo numero ("14 novembre, 2 eventi"), che fa quello che fa il clic sulla cella:
 * su desktop un evento nuovo in quella data, su mobile apre e chiude il dettaglio del giorno. Gli eventi sono pulsanti
 * accanto, mai dentro, a quello del giorno. Il clic sul resto della cella resta una comodità per il mouse.
 */
export const MonthView: React.FC<MonthViewProps> = ({ currentDate, eventsByDate, onNewEvent, onOpenEvent }) => {
  const [mobileSelectedDate, setMobileSelectedDate] = useState<string | null>(null);
  const isDesktop = useMediaQuery('(min-width: 640px)', true);
  const detailId = useId();
  const gridRef = useRef<HTMLDivElement>(null);
  const days = useMemo(() => buildMonthGrid(currentDate), [currentDate]);
  const selectedEvents = mobileSelectedDate ? eventsByDate.get(mobileSelectedDate) ?? [] : [];

  const handleDayClick = (dateStr: string) => {
    if (isDesktop) onNewEvent(dateStr);
    else setMobileSelectedDate(dateStr === mobileSelectedDate ? null : dateStr);
  };

  const openEvent = (e: React.MouseEvent, ev: CalendarEventItem) => {
    e.stopPropagation();
    onOpenEvent(ev);
  };

  // Chiuso il dettaglio, il focus torna al giorno da cui era stato aperto invece di perdersi col pulsante che sparisce
  const closeDetail = () => {
    const date = mobileSelectedDate;
    setMobileSelectedDate(null);
    gridRef.current?.querySelector<HTMLButtonElement>(`button[data-date="${date}"]`)?.focus();
  };

  return (
    <div className="flex-1 flex flex-col glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30">
      <div className="grid grid-cols-7 border-b border-border/60 bg-panel-header/60 text-center py-2 text-xs font-semibold text-fg-muted">
        {DAY_NAMES_SHORT.map((d, i) => (
          <div key={d} className={i >= 5 ? 'font-normal' : ''}>
            {d}
          </div>
        ))}
      </div>

      <div ref={gridRef} className="grid grid-cols-7 flex-1 auto-rows-fr divide-x divide-y divide-border/40 bg-panel/10">
        {days.map((day) => {
          const dayEvents = eventsByDate.get(day.dateStr) ?? [];
          const isSelected = mobileSelectedDate === day.dateStr;
          return (
            <div
              key={day.dateStr}
              onClick={() => handleDayClick(day.dateStr)}
              className={`min-h-[64px] sm:min-h-[100px] p-1 sm:p-2 flex flex-col transition cursor-pointer hover:bg-panel-hover/40 relative group ${
                !day.isCurrentMonth ? 'bg-bg-secondary/60' : ''
              } ${day.isToday ? 'bg-accent/5' : ''} ${isSelected ? 'ring-2 ring-accent ring-inset' : ''}`}
            >
              <div className="group/day flex items-center justify-between mb-0.5 sm:mb-1">
                <button
                  type="button"
                  data-date={day.dateStr}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDayClick(day.dateStr);
                  }}
                  aria-label={dayLabel(day.dateStr, dayEvents.length)}
                  aria-current={day.isToday ? 'date' : undefined}
                  aria-expanded={isDesktop ? undefined : isSelected}
                  aria-controls={!isDesktop && isSelected ? detailId : undefined}
                  title={isDesktop ? 'Aggiungi evento qui' : undefined}
                  className={`text-xs font-medium w-5 h-5 sm:w-6 sm:h-6 flex items-center justify-center rounded-full transition cursor-pointer ${
                    day.isToday
                      ? 'bg-accent text-accent-contrast font-bold shadow-sm shadow-accent/40'
                      : day.isCurrentMonth
                        ? 'text-fg'
                        : 'text-fg-muted group-hover:text-fg'
                  }`}
                >
                  {day.dayNumber}
                </button>
                {/* Solo un segno: il clic passa alla cella, e da tastiera aggiunge il pulsante del giorno, che lo fa comparire */}
                <span
                  aria-hidden="true"
                  className="pointer-events-none can-hover:opacity-0 group-hover:opacity-100 group-focus-within/day:opacity-100 p-0.5 text-fg-muted rounded transition hidden sm:block"
                >
                  <Plus size={13} />
                </span>
              </div>

              {/* Mobile: puntini colorati ed eventuale contatore */}
              <div className="flex sm:hidden flex-wrap gap-1 justify-center mt-1" aria-hidden="true">
                {dayEvents.slice(0, 3).map((ev, i) => (
                  <span
                    key={ev.uid || ev.id || i}
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: ev.calendar_color || DEFAULT_CALENDAR_COLOR }}
                  />
                ))}
                {dayEvents.length > 3 && (
                  <span className="text-xs text-fg-muted font-bold leading-none">+{dayEvents.length - 3}</span>
                )}
              </div>

              {/* Desktop: pillole complete */}
              {/* Container: nelle celle strette il titolo dell'evento ha la precedenza sull'ora */}
              <div className="@container hidden sm:block space-y-1 flex-1 overflow-y-auto max-h-[110px] pr-0.5">
                {dayEvents.map((ev) => {
                  const color = ev.calendar_color || DEFAULT_CALENDAR_COLOR;
                  const time = ev.all_day ? 'Tutto il giorno' : eventStartTime(ev);
                  return (
                    // L'anello del focus va dentro la pillola: fuori lo taglierebbe l'elenco scorrevole
                    <button
                      type="button"
                      key={ev.uid || ev.id}
                      onClick={(e) => openEvent(e, ev)}
                      className="w-full text-left px-2 py-1 rounded-md text-xs leading-tight font-medium truncate flex items-center gap-1.5 transition shadow-sm hover:scale-[1.01] cursor-pointer focus-visible:outline-offset-[-2px]"
                      style={{ backgroundColor: `${color}20`, borderLeft: `3px solid ${color}`, color: 'var(--fg)' }}
                      title={`${time} - ${ev.summary}${ev.location ? ` @ ${ev.location}` : ''}`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <span className="hidden @[8rem]:inline text-xs text-fg-muted shrink-0 tabular-nums">{ev.all_day ? 'Giornata' : time}</span>
                      <span className="truncate min-w-0">{ev.summary}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {mobileSelectedDate && (
        <div id={detailId} className="sm:hidden border-t border-border/70 p-3 bg-panel/95 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">Eventi del {mobileSelectedDate}</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onNewEvent(mobileSelectedDate)}
                className="text-xs text-accent font-medium hover:underline flex items-center gap-1"
              >
                <Plus size={12} /> Aggiungi
              </button>
              <button type="button" onClick={closeDetail} aria-label="Chiudi" className="text-fg-muted hover:text-fg p-1">
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="space-y-1.5 max-h-36 overflow-y-auto">
            {selectedEvents.length === 0 ? (
              <p className="text-xs text-fg-muted italic py-1">Nessun evento in questa data.</p>
            ) : (
              selectedEvents.map((ev) => (
                <button
                  type="button"
                  key={ev.uid || ev.id}
                  onClick={(e) => openEvent(e, ev)}
                  className="w-full text-left p-2 rounded-lg bg-panel-hover/50 border border-border/50 flex items-center justify-between text-xs cursor-pointer focus-visible:outline-offset-[-2px]"
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ev.calendar_color || DEFAULT_CALENDAR_COLOR }} />
                    <span className="font-medium text-fg truncate">{ev.summary}</span>
                  </span>
                  <span className="text-xs text-fg-muted tabular-nums shrink-0">
                    {ev.all_day ? 'Tutto il giorno' : eventStartTime(ev)}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
