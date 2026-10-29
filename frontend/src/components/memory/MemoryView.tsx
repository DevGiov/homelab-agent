import React, { useMemo, useState } from 'react';
import { Brain, Loader2, Menu, Plus, RefreshCw, Search, Sparkles, Tags, Trash2 } from 'lucide-react';
import type { ThreadItem } from '../../api/threads';
import { useConfirm } from '../../hooks/useConfirm';
import { useEpisodes } from '../../hooks/useEpisodes';
import { useProcedures } from '../../hooks/useProcedures';
import { useFeedback } from '../../hooks/useFeedback';
import { ConfirmDialog } from '../ConfirmDialog';
import { useMemoryExplorer } from '../../hooks/useMemoryExplorer';
import { FeedbackToast } from '../FeedbackToast';
import { EntityDetail } from './EntityDetail';
import { EntityPanel } from './EntityPanel';
import { EpisodesPanel } from './EpisodesPanel';
import { ProceduresPanel } from './ProceduresPanel';
import { FactCard } from './FactCard';
import { FactEditor } from './FactEditor';
import { ProfileCard } from './ProfileCard';

interface MemoryViewProps {
  threads: ThreadItem[];
  onOpenThread: (threadId: string) => void;
  onOpenMobileSidebar?: () => void;
}

const TABS = [
  ['facts', 'Fatti'],
  ['episodes', 'Episodi'],
  ['procedures', 'Procedure'],
] as const;

const pill = 'flex items-center gap-1 px-2 py-1 rounded-lg bg-panel/80 border border-border/70 text-[11px] text-fg-muted shrink-0';

type Tab = 'facts' | 'episodes' | 'procedures';

/** Memoria a lungo termine: profilo dell'utente, fatti ricordati dall'agente con le entità che citano, episodi di esecuzione e procedure. */
export const MemoryView: React.FC<MemoryViewProps> = ({ threads, onOpenThread, onOpenMobileSidebar }) => {
  const { feedback, notify } = useFeedback();
  const memory = useMemoryExplorer(notify);
  const { confirm, dialog } = useConfirm();
  const episodes = useEpisodes(notify, memory.refreshStats);
  const procedures = useProcedures(notify, memory.refreshStats);
  const [tab, setTab] = useState<Tab>('facts');
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
            <p className="text-[10px] sm:text-[11px] text-fg-muted mt-0.5 hidden md:block">Il tuo profilo, i fatti ricordati dall'agente, le sue esecuzioni passate e le procedure</p>
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
              <span className={pill}>
                <span className="font-semibold text-fg">{stats.episodes}</span> episodi
              </span>
            </div>
          )}
          {tab === 'facts' && (
            <button
              onClick={() => setIsAdding(true)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold shadow-sm cursor-pointer"
            >
              <Plus size={13} /> <span className="hidden sm:inline">Fatto</span>
            </button>
          )}
          <button
            onClick={{ facts: memory.reload, episodes: episodes.reload, procedures: procedures.reload }[tab]}
            className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer"
            title="Aggiorna"
          >
            <RefreshCw size={14} className={{ facts: memory.isLoading, episodes: episodes.isLoading, procedures: procedures.isLoading }[tab] ? 'animate-spin' : ''} />
          </button>
          {tab !== 'procedures' && (
          <button
            onClick={async () => {
              if (tab === 'episodes') {
                if (await confirm({ message: `Eliminare tutti i ${episodes.total} episodi di esecuzione? Fatti e conversazioni restano.`, confirmLabel: 'Svuota' })) {
                  episodes.clearAll();
                }
              } else if (await confirm({ message: `Eliminare tutti i ${stats?.facts} fatti e le loro entità? Conversazioni e knowledge base restano.`, confirmLabel: 'Svuota' })) {
                memory.clearAll();
              }
            }}
            disabled={tab === 'facts' ? !stats?.facts : !episodes.total}
            className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-rose-400 hover:bg-panel-hover disabled:opacity-40 cursor-pointer"
            title={tab === 'facts' ? 'Svuota i fatti' : 'Svuota gli episodi'}
          >
            <Trash2 size={14} />
          </button>
          )}
        </div>
      </div>

      <FeedbackToast feedback={feedback} />
      <ConfirmDialog {...dialog} />

      <div className="flex-1 min-h-0 flex">
        <aside
          className={`${showEntities ? 'flex' : 'hidden'} ${tab === 'facts' ? 'md:flex' : ''} flex-col w-full md:w-64 shrink-0 border-r border-border p-3 min-h-0 absolute md:static inset-x-0 top-[57px] bottom-0 z-20 bg-panel md:bg-transparent`}
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

          <div className="flex gap-1 border-b border-border" role="tablist">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`px-3 py-1.5 text-xs font-semibold border-b-2 -mb-px cursor-pointer ${tab === id ? 'border-accent text-fg' : 'border-transparent text-fg-muted hover:text-fg'}`}
              >
                {label}
                {id === 'procedures' && !!stats?.procedures_proposed && (
                  <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-amber-400/20 text-amber-400 text-[10px] tabular-nums">{stats.procedures_proposed}</span>
                )}
              </button>
            ))}
          </div>

          {tab === 'episodes' && (
            <EpisodesPanel
              state={episodes}
              threadTitles={threadTitles}
              onOpenThread={onOpenThread}
              onDelete={async (id) => {
                if (await confirm({ message: "Eliminare questo episodio? L'agente non lo rileggerà più prima di agire." })) episodes.remove(id);
              }}
            />
          )}

          {tab === 'procedures' && (
            <ProceduresPanel
              state={procedures}
              threadTitles={threadTitles}
              onOpenThread={onOpenThread}
              onDelete={async (id) => {
                if (await confirm({ message: 'Eliminare questa procedura? Se era in uso, l\'agente non la seguirà più.' })) procedures.remove(id);
              }}
            />
          )}

          {tab === 'facts' && (
            <div className="space-y-3">

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
              onMerge={async (target) => {
                if (await confirm({ message: `Unire '${selected.name}' in '${target.name}'? I fatti di '${selected.name}' passeranno a '${target.name}'.`, confirmLabel: 'Unisci' })) {
                  memory.mergeInto(selected, target);
                }
              }}
              onDelete={async () => {
                if (await confirm({ message: `Eliminare l'entità '${selected.name}'? I fatti restano, senza questa entità.` })) memory.removeEntity(selected);
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
                  onDelete={async () => {
                    if (await confirm({ message: 'Eliminare questo fatto?' })) memory.removeFact(fact.id);
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
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
