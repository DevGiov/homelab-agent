import React from 'react';
import { Clock, MapPin } from 'lucide-react';
import type { CalendarEventItem } from '../../api/calendar';
import {
  DAY_NAMES_SHORT,
  DEFAULT_CALENDAR_COLOR,
  eventEndTime,
  eventStartTime,
  MONTH_NAMES,
  toDateKey,
  weekDays,
} from '../../utils/calendarDates';

interface WeekViewProps {
  currentDate: Date;
  eventsByDate: Map<string, CalendarEventItem[]>;
  onNewEvent: (dateStr: string) => void;
  onOpenEvent: (event: CalendarEventItem) => void;
}

export const WeekView: React.FC<WeekViewProps> = ({ currentDate, eventsByDate, onNewEvent, onOpenEvent }) => {
  const today = toDateKey(new Date());

  return (
    <div className="flex-1 flex flex-col glass-panel border border-border/70 rounded-2xl overflow-hidden shadow-xl bg-panel/30">
      <div className="p-4 border-b border-border/60 bg-panel-header/60 flex items-center justify-between">
        <span className="text-xs font-semibold text-fg-muted uppercase">Vista Settimanale</span>
        <span className="text-xs text-fg-muted">Dettaglio orario appuntamenti</span>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {weekDays(currentDate).map((day, idx) => {
          const dateStr = toDateKey(day);
          const dayEvents = eventsByDate.get(dateStr) ?? [];
          const isToday = dateStr === today;

          return (
            <div
              key={dateStr}
              onClick={() => onNewEvent(dateStr)}
              className={`p-3 rounded-xl border transition cursor-pointer hover:border-accent/40 ${
                isToday ? 'bg-accent/10 border-accent/30' : 'bg-panel/40 border-border/50'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-lg ${isToday ? 'bg-accent text-white' : 'bg-input-bg text-fg'}`}>
                    {DAY_NAMES_SHORT[idx]} {day.getDate()} {MONTH_NAMES[day.getMonth()].substring(0, 3)}
                  </span>
                  {isToday && <span className="text-[10px] text-accent font-semibold uppercase tracking-wider">Oggi</span>}
                </div>
                <span className="text-xs text-fg-muted">{dayEvents.length} eventi</span>
              </div>

              {dayEvents.length === 0 ? (
                <p className="text-xs text-fg-muted/50 italic py-1">Nessun impegno pianificato</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {dayEvents.map((ev) => (
                    <div
                      key={ev.uid || ev.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenEvent(ev);
                      }}
                      className="p-2.5 rounded-xl border border-border/60 bg-panel hover:bg-panel-hover flex items-start justify-between gap-2 shadow-sm transition"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ev.calendar_color || DEFAULT_CALENDAR_COLOR }} />
                          <span className="text-xs font-semibold text-fg truncate">{ev.summary}</span>
                        </div>
                        <div className="text-[11px] text-fg-muted flex items-center gap-2">
                          <span className="flex items-center gap-1">
                            <Clock size={11} />
                            {ev.all_day ? 'Tutto il giorno' : `${eventStartTime(ev)} - ${eventEndTime(ev)}`}
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
  );
};
