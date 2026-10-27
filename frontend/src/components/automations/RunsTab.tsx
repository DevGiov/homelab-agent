import React, { useState } from 'react';
import { Eye, FileText, Lock, Pause, Play, Star, Trash2, Unlock } from 'lucide-react';
import type { AutomationRunSummary } from '../../api/automationRuns';
import type { RunActions } from '../../hooks/useRunActions';

const STATUS_FILTERS = ['all', 'completed', 'waiting_approval', 'failed', 'running', 'paused', 'dry_run'];

const STATUS_BADGE: Record<string, string> = {
  completed: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
  failed: 'bg-rose-500/20 text-rose-300 border border-rose-500/30',
  waiting_approval: 'bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse',
  running: 'bg-accent/20 text-accent border border-accent/40 animate-pulse',
  paused: 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
};

const matchesFilter = (run: AutomationRunSummary, filter: string) =>
  filter === 'all' || (filter === 'dry_run' ? run.is_dry_run : run.status.toLowerCase() === filter);

const StatusBadge: React.FC<{ run: AutomationRunSummary }> = ({ run }) =>
  run.is_dry_run ? (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
      Dry-Run
    </span>
  ) : (
    <span
      className={`px-2 py-0.5 rounded-full text-[10px] font-medium capitalize flex items-center gap-1 w-fit ${
        STATUS_BADGE[run.status] ?? 'bg-zinc-500/20 text-zinc-300'
      }`}
    >
      {run.status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-accent animate-ping" />}
      {run.status}
    </span>
  );

interface RunsTabProps {
  runs: AutomationRunSummary[];
  runActions: RunActions;
  onInspect: (runId: string) => void;
  onOpenArtifacts: () => void;
}

export const RunsTab: React.FC<RunsTabProps> = ({ runs, runActions, onInspect, onOpenArtifacts }) => {
  const [statusFilter, setStatusFilter] = useState('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);

  const visibleRuns = runs.filter((r) => matchesFilter(r, statusFilter));
  const allVisibleSelected = visibleRuns.length > 0 && visibleRuns.every((r) => selected.has(r.run_id));

  const toggleRun = (runId: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });

  const toggleAllVisible = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      visibleRuns.forEach((r) => (allVisibleSelected ? next.delete(r.run_id) : next.add(r.run_id)));
      return next;
    });

  const deleteSelected = async () => {
    if (selected.size === 0) return;
    setIsDeleting(true);
    if (await runActions.removeMany(Array.from(selected))) setSelected(new Set());
    setIsDeleting(false);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">Filtro stato:</span>
          {STATUS_FILTERS.map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition capitalize cursor-pointer ${
                statusFilter === status ? 'bg-accent text-white shadow-sm' : 'bg-panel border border-border text-fg-muted hover:text-fg'
              }`}
            >
              {status.replace('_', ' ')}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={deleteSelected}
            disabled={selected.size === 0 || isDeleting}
            className="px-2.5 py-1 text-xs text-rose-300 hover:text-white bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800/40 rounded-lg flex items-center gap-1.5 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
            title="Elimina le esecuzioni selezionate tramite checkbox"
          >
            <Trash2 size={13} />
            <span>Elimina Selezionate ({selected.size})</span>
          </button>
          <span className="text-xs text-fg-muted">{visibleRuns.length} esecuzioni</span>
        </div>
      </div>

      {visibleRuns.length === 0 ? (
        <div className="text-center py-16 text-xs text-fg-muted border border-dashed border-border rounded-xl">
          Nessuna esecuzione trovata con i filtri correnti.
        </div>
      ) : (
        <div className="border border-border rounded-xl overflow-hidden bg-panel/30 overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse min-w-[700px]">
            <thead>
              <tr className="border-b border-border bg-panel-header/40 text-fg-muted font-semibold">
                <th className="p-3 w-8 text-center" title="Seleziona tutte le visibili">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    className="rounded bg-input-bg border-border text-accent focus:ring-0 cursor-pointer"
                    title="Seleziona / deseleziona tutte le esecuzioni visibili"
                  />
                </th>
                <th className="p-3 w-8"></th>
                <th className="p-3 w-8"></th>
                <th className="p-3">Run ID</th>
                <th className="p-3">Automazione</th>
                <th className="p-3">Stato</th>
                <th className="p-3">Trigger</th>
                <th className="p-3">Report</th>
                <th className="p-3">Durata</th>
                <th className="p-3">Avviata</th>
                <th className="p-3 text-right">Azioni</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {visibleRuns.map((r) => (
                <tr
                  key={r.run_id}
                  onClick={() => onInspect(r.run_id)}
                  className={`hover:bg-panel/70 cursor-pointer transition select-none ${selected.has(r.run_id) ? 'bg-accent/5' : ''}`}
                >
                  <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(r.run_id)}
                      onChange={() => toggleRun(r.run_id)}
                      className="rounded bg-input-bg border-border text-accent focus:ring-0 cursor-pointer"
                      title="Seleziona run"
                    />
                  </td>
                  <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => runActions.toggleFavorite(r)}
                      className="p-1 text-fg-muted hover:text-amber-400 transition cursor-pointer"
                      title={r.is_favorite ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'}
                    >
                      <Star size={14} className={r.is_favorite ? 'text-amber-400 fill-amber-400' : 'text-fg-muted/40 hover:text-amber-400'} />
                    </button>
                  </td>
                  <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => runActions.togglePreserve(r)}
                      className="p-1 text-fg-muted hover:text-purple-400 transition cursor-pointer"
                      title={r.is_preserved ? 'Preservata da auto-cleanup (clicca per sbloccare)' : 'Blocca e preserva da auto-cleanup'}
                    >
                      {r.is_preserved ? (
                        <Lock size={14} className="text-purple-400" />
                      ) : (
                        <Unlock size={14} className="text-fg-muted/40 hover:text-purple-400" />
                      )}
                    </button>
                  </td>
                  <td className="p-3 font-mono font-medium text-accent">{r.run_id}</td>
                  <td className="p-3 font-semibold text-fg">{r.automation_id}</td>
                  <td className="p-3">
                    <StatusBadge run={r} />
                  </td>
                  <td className="p-3 capitalize text-fg-muted">{r.trigger_type}</td>
                  <td className="p-3">
                    {r.artifacts_count ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenArtifacts();
                        }}
                        className="px-2 py-0.5 rounded-md bg-accent/15 hover:bg-accent/25 text-accent text-[11px] font-medium flex items-center gap-1 transition"
                      >
                        <FileText size={11} /> {r.artifacts_count}
                      </button>
                    ) : (
                      <span className="text-fg-muted text-[11px]">-</span>
                    )}
                  </td>
                  <td className="p-3 text-fg-muted">{r.total_duration_ms > 0 ? `${r.total_duration_ms} ms` : '-'}</td>
                  <td className="p-3 text-fg-muted">{new Date(r.started_at).toLocaleTimeString()}</td>
                  <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {r.status === 'running' && (
                        <button
                          onClick={() => runActions.pause(r.run_id)}
                          className="p-1.5 text-fg-muted hover:text-amber-400 rounded-lg hover:bg-panel transition"
                          title="Metti in pausa"
                        >
                          <Pause size={14} />
                        </button>
                      )}
                      {r.status === 'paused' && (
                        <button
                          onClick={() => runActions.resume(r.run_id)}
                          className="p-1.5 text-fg-muted hover:text-emerald-400 rounded-lg hover:bg-panel transition"
                          title="Riprendi"
                        >
                          <Play size={14} />
                        </button>
                      )}
                      <button
                        onClick={() => onInspect(r.run_id)}
                        className="p-1.5 text-fg-muted hover:text-accent rounded-lg hover:bg-panel transition"
                        title="Ispeziona dettagli run"
                      >
                        <Eye size={15} />
                      </button>
                      <button
                        onClick={() => runActions.remove(r.run_id, r.is_preserved)}
                        className={`p-1.5 rounded-lg transition ${
                          r.is_preserved ? 'text-fg-muted/30 cursor-not-allowed' : 'text-fg-muted hover:text-rose-400 hover:bg-panel cursor-pointer'
                        }`}
                        title={r.is_preserved ? 'Esecuzione preservata (sblocca prima di eliminare)' : 'Elimina esecuzione'}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
