import React, { useState } from 'react';
import { MessageSquare, Pencil, PenLine, Trash2 } from 'lucide-react';
import type { Entity, Fact, FactInput } from '../../api/memory';
import { formatDateTime } from '../../utils/metricsFormat';
import { EntityChip } from './EntityChip';
import { FactEditor } from './FactEditor';

interface FactCardProps {
  fact: Fact;
  known: Entity[];
  selectedEntityId?: number;
  /** Titolo del thread di origine, se il thread esiste ancora. */
  threadTitle?: string;
  onSelectEntity: (id: number) => void;
  onOpenThread?: (threadId: string) => void;
  onSave: (input: FactInput) => Promise<boolean>;
  onDelete: () => void;
}

export const FactCard: React.FC<FactCardProps> = ({ fact, known, selectedEntityId, threadTitle, onSelectEntity, onOpenThread, onSave, onDelete }) => {
  const [isEditing, setIsEditing] = useState(false);

  if (isEditing) {
    return (
      <div className="rounded-xl border border-accent/40 bg-panel/80 p-3">
        <FactEditor
          initial={{ content: fact.content, entities: fact.entities.map(({ name, type }) => ({ name, type })) }}
          known={known}
          submitLabel="Salva"
          onSubmit={onSave}
          onCancel={() => setIsEditing(false)}
        />
      </div>
    );
  }

  return (
    <article className="group rounded-xl border border-border bg-panel/60 p-3 hover:border-accent/30 transition">
      <div className="flex items-start gap-2">
        <p className="flex-1 text-[13px] text-fg leading-relaxed">{fact.content}</p>
        <div className="flex items-center gap-0.5 shrink-0 opacity-60 group-hover:opacity-100 transition">
          <button onClick={() => setIsEditing(true)} className="p-1 rounded-md text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer" title="Modifica fatto">
            <Pencil size={13} />
          </button>
          <button onClick={onDelete} className="p-1 rounded-md text-fg-muted hover:text-rose-400 hover:bg-panel-hover cursor-pointer" title="Elimina fatto">
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {fact.entities.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {fact.entities.map((e) => (
            <EntityChip key={e.id} entity={e} active={e.id === selectedEntityId} onClick={() => onSelectEntity(e.id)} />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[11px] text-fg-muted">
        {fact.thread_id ? (
          threadTitle && onOpenThread ? (
            <button onClick={() => onOpenThread(fact.thread_id as string)} className="flex items-center gap-1 hover:text-accent truncate max-w-[16rem] cursor-pointer" title="Apri la conversazione">
              <MessageSquare size={11} className="shrink-0" />
              <span className="truncate">{threadTitle}</span>
            </button>
          ) : (
            <span className="flex items-center gap-1" title={fact.thread_id}>
              <MessageSquare size={11} /> conversazione eliminata
            </span>
          )
        ) : (
          <span className="flex items-center gap-1">
            <PenLine size={11} /> aggiunto a mano
          </span>
        )}
        {fact.created_at && <span>{formatDateTime(fact.created_at)}</span>}
        {fact.score != null && <span className="tabular-nums">pertinenza {Math.round(fact.score * 100)}%</span>}
      </div>
    </article>
  );
};
