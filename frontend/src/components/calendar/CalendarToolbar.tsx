import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Filter, Menu, Plus, RefreshCw, Settings } from 'lucide-react';
import type { CalendarNavigation, CalendarViewMode } from '../../hooks/useCalendarNavigation';
import { MONTH_NAMES, weekRangeTitle } from '../../utils/calendarDates';

const VIEW_MODES: Array<{ id: CalendarViewMode; label: string }> = [
  { id: 'month', label: 'Mese' },
  { id: 'week', label: 'Settimana' },
  { id: 'agenda', label: 'Agenda' },
];

const iconButton =
  'p-2 bg-input-bg hover:bg-panel-hover text-fg-muted hover:text-fg border border-input-border rounded-xl transition cursor-pointer';

/** Popover di selezione rapida di mese e anno. */
const MonthPicker: React.FC<{ navigation: CalendarNavigation; onClose: () => void }> = ({ navigation, onClose }) => {
  const { currentDate } = navigation;

  return (
    <div
      className="absolute top-full left-0 mt-2 z-50 p-3 rounded-2xl border border-border shadow-2xl text-fg w-64 animate-in fade-in zoom-in-95 duration-150"
      style={{
        backgroundColor: 'var(--panel)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        boxShadow: '0 20px 45px -12px rgba(0,0,0,0.8), 0 0 0 1px var(--border)',
      }}
    >
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-border">
        <button
          type="button"
          onClick={() => navigation.shiftYear(-1)}
          className="p-1 text-fg-muted hover:text-fg hover:bg-panel-header rounded transition cursor-pointer"
          title="Anno precedente"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="font-bold text-sm text-fg tracking-wide">{currentDate.getFullYear()}</span>
        <button
          type="button"
          onClick={() => navigation.shiftYear(1)}
          className="p-1 text-fg-muted hover:text-fg hover:bg-panel-header rounded transition cursor-pointer"
          title="Anno successivo"
        >
          <ChevronRight size={14} />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        {MONTH_NAMES.map((name, idx) => (
          <button
            key={name}
            type="button"
            onClick={() => {
              navigation.selectMonth(idx, currentDate.getFullYear());
              onClose();
            }}
            className={`p-1.5 text-xs rounded-lg font-medium transition cursor-pointer ${
              currentDate.getMonth() === idx ? 'bg-accent text-white shadow-sm' : 'text-fg-muted hover:text-fg hover:bg-panel-header'
            }`}
          >
            {name.substring(0, 3)}
          </button>
        ))}
      </div>
    </div>
  );
};

interface CalendarToolbarProps {
  navigation: CalendarNavigation;
  isSyncing: boolean;
  isSidebarOpen: boolean;
  onSync: () => void;
  onManageCalendars: () => void;
  onNewEvent: () => void;
  onToggleSidebar: () => void;
  onOpenMobileSidebar?: () => void;
}

export const CalendarToolbar: React.FC<CalendarToolbarProps> = ({
  navigation,
  isSyncing,
  isSidebarOpen,
  onSync,
  onManageCalendars,
  onNewEvent,
  onToggleSidebar,
  onOpenMobileSidebar,
}) => {
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const { currentDate, viewMode } = navigation;

  // Click fuori dal titolo e dal popover: chiude il selettore
  useEffect(() => {
    if (!isPickerOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setIsPickerOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isPickerOpen]);

  const title = viewMode === 'week' ? weekRangeTitle(currentDate) : `${MONTH_NAMES[currentDate.getMonth()]} ${currentDate.getFullYear()}`;

  return (
    <header className="px-3 sm:px-5 py-3 border-b border-border/70 glass-panel bg-panel/70 flex flex-wrap items-center justify-between gap-2 sm:gap-3 shrink-0">
      <div className="flex items-center gap-2 sm:gap-3 min-w-0">
        {onOpenMobileSidebar && (
          <button
            onClick={onOpenMobileSidebar}
            className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition shrink-0 cursor-pointer"
            title="Apri menu principale"
          >
            <Menu size={20} />
          </button>
        )}

        <div className="flex items-center gap-1.5 sm:gap-2">
          <div className="flex items-center bg-input-bg border border-input-border rounded-xl p-0.5 sm:p-1 shadow-inner shrink-0 relative">
            <button
              onClick={navigation.prev}
              className="p-1 sm:p-1.5 hover:bg-panel-hover text-fg-muted hover:text-fg rounded-lg transition cursor-pointer"
              title="Precedente"
            >
              <ChevronLeft size={16} />
            </button>

            <div ref={pickerRef} className="relative">
              <button
                type="button"
                onClick={() => setIsPickerOpen(!isPickerOpen)}
                className="px-2 sm:px-3 py-1 text-xs sm:text-sm font-semibold text-fg hover:bg-panel-hover hover:text-accent rounded-lg transition cursor-pointer flex items-center gap-1 tracking-tight"
                title="Clicca per scegliere mese e anno desiderati"
              >
                <span className="truncate max-w-[140px] sm:max-w-none">{title}</span>
              </button>
              {isPickerOpen && <MonthPicker navigation={navigation} onClose={() => setIsPickerOpen(false)} />}
            </div>

            <button
              onClick={navigation.next}
              className="p-1 sm:p-1.5 hover:bg-panel-hover text-fg-muted hover:text-fg rounded-lg transition cursor-pointer"
              title="Successivo"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <button
            onClick={navigation.today}
            className="px-2.5 sm:px-3 py-1.5 text-xs font-semibold text-fg hover:text-accent bg-input-bg hover:bg-panel-hover border border-input-border rounded-xl shadow-inner transition cursor-pointer shrink-0"
            title="Torna ad oggi"
          >
            Oggi
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2">
        <div className="flex items-center bg-input-bg border border-input-border rounded-xl p-1 text-xs shadow-inner">
          {VIEW_MODES.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => navigation.setViewMode(id)}
              className={`px-2.5 sm:px-3 py-1 rounded-lg font-medium transition cursor-pointer ${
                viewMode === id ? 'bg-accent text-white shadow-sm' : 'text-fg-muted hover:text-fg'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <button onClick={onManageCalendars} className={iconButton} title="Gestione Calendari & Import">
          <Settings size={15} />
        </button>

        <button onClick={onSync} disabled={isSyncing} className={`${iconButton} disabled:opacity-50`} title="Sincronizza calendari esterni">
          <RefreshCw size={15} className={isSyncing ? 'animate-spin text-accent' : ''} />
        </button>

        <button
          onClick={onNewEvent}
          className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm shadow-accent/20 transition cursor-pointer"
        >
          <Plus size={15} />
          <span className="hidden sm:inline">Nuovo Evento</span>
        </button>

        <button
          onClick={onToggleSidebar}
          className={`p-2 md:hidden rounded-xl border transition cursor-pointer ${
            isSidebarOpen ? 'bg-accent text-white border-accent' : 'bg-input-bg text-fg-muted hover:text-fg border-input-border'
          }`}
          title="Filtri e calendari"
        >
          <Filter size={15} />
        </button>
      </div>
    </header>
  );
};
