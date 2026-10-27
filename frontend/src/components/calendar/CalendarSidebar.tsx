import React from 'react';
import { Check, Plus, Search, Settings, X } from 'lucide-react';
import type { CalendarItem } from '../../api/calendar';
import { DEFAULT_CALENDAR_COLOR } from '../../utils/calendarDates';

const CATEGORIES = [
  { id: 'all', label: 'Tutte' },
  { id: 'meeting', label: 'Meeting' },
  { id: 'personal', label: 'Personale' },
  { id: 'homelab', label: 'Homelab' },
  { id: 'flight', label: 'Viaggi' },
  { id: 'reminder', label: 'Promemoria' },
];

interface CalendarSidebarProps {
  calendars: CalendarItem[];
  visibleCalendarIds: Set<string>;
  onToggleCalendar: (calendarId: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  category: string;
  onCategoryChange: (category: string) => void;
  totalEvents: number;
  filteredEvents: number;
  onManageCalendars: () => void;
  isMobileOpen: boolean;
  onCloseMobile: () => void;
}

/** Ricerca, calendari visibili e filtro per categoria: colonna fissa su desktop, drawer su mobile. */
export const CalendarSidebar: React.FC<CalendarSidebarProps> = ({
  calendars,
  visibleCalendarIds,
  onToggleCalendar,
  searchQuery,
  onSearchChange,
  category,
  onCategoryChange,
  totalEvents,
  filteredEvents,
  onManageCalendars,
  isMobileOpen,
  onCloseMobile,
}) => {
  const content = (
    <div className="p-4 space-y-5 overflow-y-auto flex-1">
      <div className="relative">
        <Search size={14} className="absolute left-3 top-2.5 text-fg-muted" />
        <input
          type="text"
          placeholder="Cerca eventi..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full pl-8 pr-3 py-1.5 bg-input-bg border border-input-border rounded-xl text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent transition"
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-semibold text-fg-muted tracking-wider uppercase">I Miei Calendari</span>
          <div className="flex items-center gap-1.5">
            <button
              onClick={onManageCalendars}
              className="p-1 text-fg-muted hover:text-accent hover:bg-panel-hover rounded-md transition"
              title="Gestisci calendari e import"
            >
              <Settings size={13} />
            </button>
            <span className="text-[10px] text-fg-muted bg-panel px-1.5 py-0.5 rounded-full border border-border/50">
              {calendars.length}
            </span>
          </div>
        </div>

        <div className="space-y-1.5">
          {calendars.map((c) => {
            const isChecked = visibleCalendarIds.has(c.id);
            return (
              <div
                key={c.id}
                onClick={() => onToggleCalendar(c.id)}
                className={`px-2.5 py-1.5 rounded-xl border flex items-center justify-between text-xs cursor-pointer transition select-none ${
                  isChecked
                    ? 'bg-panel-hover/50 border-border/70 text-fg'
                    : 'bg-transparent border-transparent text-fg-muted/60 hover:bg-panel-hover/30'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0 shadow-sm" style={{ backgroundColor: c.color || DEFAULT_CALENDAR_COLOR }} />
                  <span className="truncate font-medium">{c.name}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  {c.event_count !== undefined && <span className="text-[10px] text-fg-muted">{c.event_count}</span>}
                  <div
                    className={`w-3.5 h-3.5 rounded flex items-center justify-center border transition ${
                      isChecked ? 'bg-accent border-accent text-white' : 'border-border/80 bg-input-bg'
                    }`}
                  >
                    {isChecked && <Check size={10} strokeWidth={3} />}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <button
          onClick={onManageCalendars}
          className="w-full mt-2.5 py-1.5 px-2.5 text-xs text-accent hover:bg-accent/10 border border-accent/25 rounded-xl flex items-center justify-center gap-1.5 transition cursor-pointer"
        >
          <Plus size={13} />
          <span>Aggiungi / Importa</span>
        </button>
      </div>

      <div>
        <span className="text-[11px] font-semibold text-fg-muted tracking-wider uppercase block mb-2">Categorie</span>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              onClick={() => onCategoryChange(cat.id)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition cursor-pointer border ${
                category === cat.id
                  ? 'bg-accent/15 border-accent/40 text-accent font-semibold'
                  : 'bg-input-bg/40 border-border/40 text-fg-muted hover:text-fg hover:bg-panel-hover'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-3 bg-panel-header/40 border border-border/50 rounded-xl space-y-1.5 text-xs">
        <div className="flex items-center justify-between text-fg-muted">
          <span>Eventi totali</span>
          <span className="font-semibold text-fg">{totalEvents}</span>
        </div>
        <div className="flex items-center justify-between text-fg-muted">
          <span>Eventi filtrati</span>
          <span className="font-semibold text-accent">{filteredEvents}</span>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <aside className="hidden md:flex w-64 border-r border-border/60 glass-panel bg-panel/40 flex-col shrink-0 overflow-hidden">
        {content}
      </aside>

      {isMobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden flex">
          <div className="fixed inset-0 bg-bg/80 backdrop-blur-sm transition-opacity" onClick={onCloseMobile} />
          <div className="relative w-72 max-w-[85vw] h-full bg-panel border-r border-border flex flex-col shadow-2xl z-50">
            <div className="p-3 border-b border-border flex items-center justify-between">
              <span className="text-xs font-semibold text-fg uppercase tracking-wider">Filtri & Calendari</span>
              <button onClick={onCloseMobile} className="p-1 text-fg-muted hover:text-fg rounded-lg">
                <X size={16} />
              </button>
            </div>
            {content}
          </div>
        </div>
      )}
    </>
  );
};
