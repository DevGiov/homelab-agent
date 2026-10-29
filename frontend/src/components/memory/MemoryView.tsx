import React, { useMemo, useState } from 'react';
import { Brain, Loader2, Menu, Plus, RefreshCw, Search, Sparkles, Tags, Trash2 } from 'lucide-react';
import type { ThreadItem } from '../../api/threads';
import { useFeedback } from '../../hooks/useFeedback';
import { useMemoryExplorer } from '../../hooks/useMemoryExplorer';
import { FeedbackToast } from '../FeedbackToast';
import { EntityDetail } from './EntityDetail';
import { EntityPanel } from './EntityPanel';
import { FactCard } from './FactCard';
import { FactEditor } from './FactEditor';
import { ProfileCard } from './ProfileCard';

interface MemoryViewProps {
  threads: ThreadItem[];
  onOpenThread: (threadId: string) => void;
  onOpenMobileSidebar?: () => void;
}

const pill = 'flex items-center gap-1 px-2 py-1 rounded-lg bg-panel/80 border border-border/70 text-[11px] text-fg-muted shrink-0';

/** Memoria a lungo termine: profilo dell'utente, fatti ricordati dall'agente, entità che citano e relazioni tra entità. */
export const MemoryView: React.FC<MemoryViewProps> = ({ threads, onOpenThread, onOpenMobileSidebar }) => {
  const { feedback, notify } = useFeedback();
  const memory = useMemoryExplorer(notify);
  const [isAdding, setIsAdding] = useState(false);
  const [showEntities, setShowEntities] = useState(false);
  const { stats, selected } = memory;

  const threadTitles = useMemo(() => new Map(threads.map((t) => [t.thread_id, t.title || t.thread_id])), [threads]);

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-background relative">
      <div className="p-2.5 sm:p-3.5 border-b border-border bg-panel-header/40 backdrop-blur-md flex items-center justify-between gap-2 shrink-0">
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
          <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shadow-sm shrink-0">
            <Brain size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="font-semibold text-xs sm:text-sm text-fg leading-tight truncate">Memoria</h1>
            <p className="text-[10px] sm:text-[11px] text-fg-muted mt-0.5 hidden md:block">Il tuo profilo, i fatti ricordati dall'agente e le entità che citano</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {stats && (
            <div className="hidden sm:flex items-center gap-1.5">
              <span className={pill}>
                <span className="font-semibold text-fg">{stats.facts}</span> fatti
              </span>
              <span className={pill}>
                <span className="font-semibold text-fg">{stats.entities}</span> entità
              </span>
            </div>
          )}
          <button
            onClick={() => setIsAdding(true)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold shadow-sm cursor-pointer"
          >
            <Plus size={13} /> <span className="hidden sm:inline">Fatto</span>
          </button>
          <button
            onClick={memory.reload}
            className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer"
            title="Aggiorna"
          >
            <RefreshCw size={14} className={memory.isLoading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => {
              if (stats?.facts && confirm(`Eliminare tutti i ${stats.facts} fatti e le loro entità? Conversazioni e knowledge base restano.`)) {
                memory.clearAll();
              }
            }}
            disabled={!stats?.facts}
            className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-rose-400 hover:bg-panel-hover disabled:opacity-40 cursor-pointer"
            title="Svuota la memoria"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <FeedbackToast feedback={feedback} />

      <div className="flex-1 min-h-0 flex">
        <aside
          className={`${showEntities ? 'flex' : 'hidden'} md:flex flex-col w-full md:w-64 shrink-0 border-r border-border p-3 min-h-0 absolute md:static inset-x-0 top-[57px] bottom-0 z-20 bg-panel md:bg-transparent`}
        >
          <EntityPanel
            entities={memory.entities}
            query={memory.entityQuery}
            type={memory.entityType}
            selectedId={selected?.id}
            onQueryChange={memory.setEntityQuery}
            onTypeChange={memory.setEntityType}
            onSelect={(id) => {
              memory.selectEntity(id);
              setShowEntities(false);
            }}
          />
        </aside>

        <main className="flex-1 min-w-0 overflow-y-auto p-3 sm:p-4 space-y-3">
          <ProfileCard notify={notify} />

          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
              <input
                value={memory.query}
                onChange={(e) => memory.setQuery(e.target.value)}
                placeholder="Cerca per significato (es. 'che IP ha il NAS?')"
                className="w-full bg-input-bg border border-input-border rounded-xl pl-8 pr-3 py-2 text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent"
                aria-label="Cerca nei fatti"
              />
            </div>
            <button
              onClick={() => setShowEntities(!showEntities)}
              className="md:hidden flex items-center gap-1 px-2.5 py-2 rounded-xl border border-border text-xs text-fg-muted hover:text-fg cursor-pointer"
            >
              <Tags size={13} /> Entità
            </button>
          </div>

          {stats != null && stats.facts_without_entities > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent/30 bg-accent/5 px-3 py-2">
              <p className="text-[11px] text-fg-muted">
                <span className="font-semibold text-fg">{stats.facts_without_entities}</span> fatti non sono mai stati analizzati per le entità. L'analisi usa il modello attivo,
                10 fatti per chiamata.
              </p>
              <button
                onClick={memory.extract}
                disabled={memory.isExtracting}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-accent text-white text-xs font-semibold disabled:opacity-50 cursor-pointer"
              >
                {memory.isExtracting ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                Estrai entità
              </button>
            </div>
          )}

          {isAdding && (
            <div className="rounded-xl border border-accent/40 bg-panel/80 p-3">
              <FactEditor known={memory.entities} submitLabel="Aggiungi" onSubmit={(input) => memory.saveFact(null, input)} onCancel={() => setIsAdding(false)} />
            </div>
          )}

          {selected && (
            <EntityDetail
              key={selected.id}
              entity={selected}
              others={memory.entities.filter((e) => e.id !== selected.id)}
              onClose={() => memory.selectEntity(null)}
              onSelect={memory.selectEntity}
              onEdit={(input) => memory.editEntity(selected.id, input)}
              onMerge={(target) => {
                if (confirm(`Unire '${selected.name}' in '${target.name}'? I fatti di '${selected.name}' passeranno a '${target.name}'.`)) {
                  memory.mergeInto(selected, target);
                }
              }}
              onDelete={() => {
                if (confirm(`Eliminare l'entità '${selected.name}'? I fatti restano, senza questa entità.`)) memory.removeEntity(selected);
              }}
            />
          )}

          <p className="text-[11px] text-fg-muted">
            {memory.isSearching
              ? `${memory.facts.length} fatti più pertinenti${selected ? ` tra quelli di ${selected.name}` : ''}`
              : `${memory.total} fatti${selected ? ` su ${selected.name}` : ''}, dal più recente`}
          </p>

          {memory.isLoading && memory.facts.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-12 text-xs text-fg-muted">
              <Loader2 size={14} className="animate-spin text-accent" /> Caricamento…
            </div>
          ) : memory.facts.length === 0 ? (
            <p className="text-xs text-fg-muted text-center py-12">
              {memory.isSearching ? 'Nessun fatto pertinente.' : "Nessun fatto in memoria: l'agente li salva a fine conversazione, o aggiungine uno."}
            </p>
          ) : (
            <div className="space-y-2">
              {memory.facts.map((fact) => (
                <FactCard
                  key={fact.id}
                  fact={fact}
                  known={memory.entities}
                  selectedEntityId={selected?.id}
                  threadTitle={fact.thread_id ? threadTitles.get(fact.thread_id) : undefined}
                  onSelectEntity={memory.selectEntity}
                  onOpenThread={onOpenThread}
                  onSave={(input) => memory.saveFact(fact.id, input)}
                  onDelete={() => {
                    if (confirm('Eliminare questo fatto?')) memory.removeFact(fact.id);
                  }}
                />
              ))}
              {!memory.isSearching && memory.facts.length < memory.total && (
                <button onClick={memory.loadMore} className="w-full py-2 rounded-xl border border-border text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
                  Carica altri ({memory.total - memory.facts.length})
                </button>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
