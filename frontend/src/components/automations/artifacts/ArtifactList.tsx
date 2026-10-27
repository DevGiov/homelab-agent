import React, { useMemo } from 'react';
import { Calendar, Clock, FileText, Lock, Star, Unlock } from 'lucide-react';
import type { AutomationArtifact } from '../../../api/artifacts';
import { groupArtifactsByAge } from '../../../utils/artifactGroups';

interface ArtifactListProps {
  artifacts: AutomationArtifact[];
  selectedId: string | null;
  onSelect: (artifactId: string) => void;
  onToggleFavorite: (artifact: AutomationArtifact) => void;
  onTogglePreserve: (artifact: AutomationArtifact) => void;
  query: string;
  onClearQuery: () => void;
}

/** Elenco degli artefatti raggruppato per età; su mobile occupa tutta la larghezza finché non se ne apre uno. */
export const ArtifactList: React.FC<ArtifactListProps> = ({
  artifacts,
  selectedId,
  onSelect,
  onToggleFavorite,
  onTogglePreserve,
  query,
  onClearQuery,
}) => {
  const groups = useMemo(() => groupArtifactsByAge(artifacts), [artifacts]);

  return (
    <div
      className={`w-full md:w-80 lg:w-96 border-r border-border bg-panel-header/10 flex-col overflow-hidden shrink-0 ${
        selectedId ? 'hidden md:flex' : 'flex'
      }`}
    >
      <div className="p-3 border-b border-border/60 bg-panel/30 flex items-center justify-between text-xs text-fg-muted">
        <span>{artifacts.length} artefatti archiviati</span>
        {query && (
          <button onClick={onClearQuery} className="text-[11px] text-accent hover:underline cursor-pointer">
            Azzera ricerca
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-border/40 p-2 space-y-4">
        {groups.length === 0 ? (
          <div className="text-center py-12 px-4">
            <FileText className="mx-auto text-fg-muted/40 mb-3" size={32} />
            <p className="text-xs text-fg-muted font-medium">Nessun artefatto trovato</p>
            <p className="text-[11px] text-fg-muted/70 mt-1">
              I report generati dalle automazioni (come briefing o audit) compariranno qui automaticamente.
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.key} className="space-y-1.5 pt-1">
              <div className="flex items-center gap-1.5 px-2 text-[11px] font-bold text-fg-muted uppercase tracking-wider">
                <Calendar size={12} className="text-accent/70" />
                <span>{group.title}</span>
                <span className="text-[10px] text-fg-muted/60 font-normal">({group.items.length})</span>
              </div>

              <div className="space-y-1">
                {group.items.map((art) => (
                  <div
                    key={art.artifact_id}
                    onClick={() => onSelect(art.artifact_id)}
                    className={`p-2.5 rounded-xl border text-xs transition cursor-pointer flex flex-col gap-1.5 relative group ${
                      selectedId === art.artifact_id
                        ? 'bg-accent/15 border-accent text-fg shadow-sm'
                        : 'bg-panel/60 hover:bg-panel border-border/60 hover:border-border text-fg-muted hover:text-fg'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-semibold text-xs text-fg leading-snug line-clamp-2">{art.title || art.name}</span>
                      <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => onToggleFavorite(art)}
                          className={`p-1 rounded-md transition hover:scale-110 cursor-pointer ${
                            art.is_favorite ? 'text-amber-400' : 'text-fg-muted/40 hover:text-amber-400'
                          }`}
                          title={art.is_favorite ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'}
                        >
                          <Star size={13} className={art.is_favorite ? 'fill-amber-400' : ''} />
                        </button>
                        <button
                          onClick={() => onTogglePreserve(art)}
                          className={`p-1 rounded-md transition hover:scale-110 cursor-pointer ${
                            art.is_preserved ? 'text-indigo-400' : 'text-fg-muted/40 hover:text-indigo-400'
                          }`}
                          title={art.is_preserved ? 'Protetto da pulizia' : 'Blocca per non eliminare'}
                        >
                          {art.is_preserved ? <Lock size={13} /> : <Unlock size={13} />}
                        </button>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-fg-muted mt-0.5">
                      <span className="px-2 py-0.5 rounded-md bg-bg/80 border border-border/50 text-[10px] truncate max-w-[170px]">
                        {art.automation_name || art.automation_id || 'Automazione'}
                      </span>
                      <span className="flex items-center gap-1 text-[10px]">
                        <Clock size={10} />
                        {art.created_at ? new Date(art.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
