import React from 'react';
import { CheckCircle2, MessageSquare, Trash2, Undo2, XCircle } from 'lucide-react';
import type { Episode } from '../../api/memory';
import { formatDateTime } from '../../utils/metricsFormat';

interface EpisodeCardProps {
  episode: Episode;
  /** Titolo del thread di origine, se il thread esiste ancora. */
  threadTitle?: string;
  onOpenThread?: (threadId: string) => void;
  onDelete: () => void;
}

const outcomeClass = (outcome: string | null) =>
  outcome?.startsWith('fallito')
    ? 'text-rose-400 border-rose-400/30 bg-rose-400/10'
    : outcome?.includes('errori') || outcome?.includes('rollback')
      ? 'text-amber-400 border-amber-400/30 bg-amber-400/10'
      : 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10';

/** Un'esecuzione passata: richiesta, tool chiamati con esito ed eventuale errore. */
export const EpisodeCard: React.FC<EpisodeCardProps> = ({ episode, threadTitle, onOpenThread, onDelete }) => (
  <article className="group rounded-xl border border-border bg-panel/60 p-3 hover:border-accent/30 transition" aria-label={`Episodio ${episode.id}`}>
    <div className="flex items-start gap-2">
      <p className="flex-1 text-[13px] text-fg leading-relaxed">{episode.task ?? episode.content}</p>
      {episode.outcome && <span className={`shrink-0 px-1.5 py-0.5 rounded-md border text-[10px] font-semibold ${outcomeClass(episode.outcome)}`}>{episode.outcome}</span>}
      <button onClick={onDelete} className="p-1 rounded-md text-fg-muted hover:text-rose-400 hover:bg-panel-hover cursor-pointer shrink-0 opacity-60 group-hover:opacity-100" title="Elimina episodio">
        <Trash2 size={13} />
      </button>
    </div>

    {episode.steps.length > 0 && (
      <ol className="mt-2 space-y-1">
        {episode.steps.map((step, i) => (
          <li key={i} className="flex items-start gap-1.5 text-[11px]">
            {step.error ? (
              <XCircle size={12} className="text-rose-400 shrink-0 mt-0.5" />
            ) : step.rolled_back ? (
              <Undo2 size={12} className="text-amber-400 shrink-0 mt-0.5" />
            ) : (
              <CheckCircle2 size={12} className="text-emerald-400 shrink-0 mt-0.5" />
            )}
            <span className="min-w-0">
              <code className="text-fg">{step.tool}</code>
              {step.args !== '{}' && <code className="text-fg-muted break-all"> {step.args}</code>}
              {step.error && <span className="block text-rose-300/90 break-words">{step.error}</span>}
            </span>
          </li>
        ))}
      </ol>
    )}

    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[11px] text-fg-muted">
      {episode.mode && <span className="uppercase tracking-wide">{episode.mode}</span>}
      {episode.thread_id &&
        (threadTitle && onOpenThread ? (
          <button onClick={() => onOpenThread(episode.thread_id as string)} className="flex items-center gap-1 hover:text-accent truncate max-w-[16rem] cursor-pointer" title="Apri la conversazione">
            <MessageSquare size={11} className="shrink-0" />
            <span className="truncate">{threadTitle}</span>
          </button>
        ) : (
          <span className="flex items-center gap-1" title={episode.thread_id}>
            <MessageSquare size={11} /> conversazione eliminata
          </span>
        ))}
      {episode.created_at && <span>{formatDateTime(episode.created_at)}</span>}
      {episode.score != null && <span className="tabular-nums">pertinenza {Math.round(episode.score * 100)}%</span>}
    </div>
  </article>
);
