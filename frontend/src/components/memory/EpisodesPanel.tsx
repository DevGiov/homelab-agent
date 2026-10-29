import React from 'react';
import { Loader2, Search } from 'lucide-react';
import type { EpisodesState } from '../../hooks/useEpisodes';
import { EpisodeCard } from './EpisodeCard';

interface EpisodesPanelProps {
  state: EpisodesState;
  threadTitles: Map<string, string>;
  onOpenThread: (threadId: string) => void;
  onDelete: (id: number) => void;
}

/** Esecuzioni passate dei turni act e plan: l'agente rilegge le più simili prima di agire. */
export const EpisodesPanel: React.FC<EpisodesPanelProps> = ({ state, threadTitles, onOpenThread, onDelete }) => (
  <div className="space-y-3">
    <div className="relative">
      <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
      <input
        value={state.query}
        onChange={(e) => state.setQuery(e.target.value)}
        placeholder="Cerca tra le esecuzioni (es. 'riavvio container')"
        className="w-full bg-input-bg border border-input-border rounded-xl pl-8 pr-3 py-2 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent"
        aria-label="Cerca negli episodi"
      />
    </div>
    <p className="text-[11px] text-fg-muted">
      {state.isSearching ? `${state.episodes.length} episodi più pertinenti` : `${state.total} episodi, dal più recente`}
    </p>
    {state.isLoading && state.episodes.length === 0 ? (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-fg-muted">
        <Loader2 size={14} className="animate-spin text-accent" /> Caricamento…
      </div>
    ) : state.episodes.length === 0 ? (
      <p className="text-xs text-fg-muted text-center py-12">
        {state.isSearching ? 'Nessun episodio pertinente.' : "Nessun episodio: l'agente ne salva uno dopo ogni turno act o plan che usa dei tool."}
      </p>
    ) : (
      <div className="space-y-2">
        {state.episodes.map((episode) => (
          <EpisodeCard
            key={episode.id}
            episode={episode}
            threadTitle={episode.thread_id ? threadTitles.get(episode.thread_id) : undefined}
            onOpenThread={onOpenThread}
            onDelete={() => onDelete(episode.id)}
          />
        ))}
        {!state.isSearching && state.episodes.length < state.total && (
          <button onClick={state.loadMore} className="w-full py-2 rounded-xl border border-border text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
            Carica altri ({state.total - state.episodes.length})
          </button>
        )}
      </div>
    )}
  </div>
);
