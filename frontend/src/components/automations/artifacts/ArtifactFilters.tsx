import React from 'react';
import { Lock, RefreshCw, Search, Star } from 'lucide-react';

export interface ArtifactFilterState {
  query: string;
  automationId: string;
  favoriteOnly: boolean;
  preservedOnly: boolean;
}

interface ArtifactFiltersProps {
  filters: ArtifactFilterState;
  onChange: (patch: Partial<ArtifactFilterState>) => void;
  automations: Array<{ id: string; name: string }>;
  total: number;
  isLoading: boolean;
  onRefresh: () => void;
  /** Su mobile la barra resta nascosta mentre si legge un artefatto. */
  hiddenOnMobile: boolean;
}

const toggleClass = (active: boolean, activeClass: string) =>
  `px-2 py-1.5 rounded-xl border flex items-center gap-1 transition cursor-pointer ${
    active ? activeClass : 'bg-panel border-border/80 text-fg-muted hover:text-fg'
  }`;

export const ArtifactFilters: React.FC<ArtifactFiltersProps> = ({ filters, onChange, automations, total, isLoading, onRefresh, hiddenOnMobile }) => (
  <div
    className={`p-2.5 sm:p-3 border-b border-border bg-panel-header/35 backdrop-blur-md flex-wrap items-center justify-between gap-2.5 shrink-0 ${
      hiddenOnMobile ? 'hidden md:flex' : 'flex'
    }`}
  >
    <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-md">
      <div className="relative w-full">
        <Search className="absolute left-3 top-2.5 text-fg-muted" size={14} />
        <input
          type="text"
          placeholder="Cerca artefatto, report o automazione..."
          value={filters.query}
          onChange={(e) => onChange({ query: e.target.value })}
          className="w-full bg-panel border border-border/80 pl-8 pr-3 py-1.5 rounded-xl text-xs text-fg focus:outline-none focus:border-accent"
        />
      </div>
    </div>

    <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap text-xs">
      <select
        value={filters.automationId}
        onChange={(e) => onChange({ automationId: e.target.value })}
        className="bg-panel border border-border/80 px-2 py-1.5 rounded-xl text-xs text-fg focus:outline-none focus:border-accent max-w-[170px] sm:max-w-xs truncate"
      >
        <option value="all">Tutte le automazioni ({total})</option>
        {automations.map((opt) => (
          <option key={opt.id} value={opt.id}>
            {opt.name}
          </option>
        ))}
      </select>

      <button
        onClick={() => onChange({ favoriteOnly: !filters.favoriteOnly })}
        className={toggleClass(filters.favoriteOnly, 'bg-amber-500/15 border-amber-500/40 text-amber-300 font-semibold')}
        title="Mostra solo preferiti con stella"
      >
        <Star size={13} className={filters.favoriteOnly ? 'fill-amber-400 text-amber-400' : ''} />
        <span className="hidden sm:inline">Preferiti</span>
      </button>

      <button
        onClick={() => onChange({ preservedOnly: !filters.preservedOnly })}
        className={toggleClass(filters.preservedOnly, 'bg-indigo-500/15 border-indigo-500/40 text-indigo-300 font-semibold')}
        title="Mostra solo artefatti protetti da cancellazione"
      >
        <Lock size={13} className={filters.preservedOnly ? 'text-indigo-400' : ''} />
        <span className="hidden sm:inline">Protetti</span>
      </button>

      <button
        onClick={onRefresh}
        disabled={isLoading}
        className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-xl border border-border transition cursor-pointer"
        title="Aggiorna lista"
      >
        <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
      </button>
    </div>
  </div>
);
