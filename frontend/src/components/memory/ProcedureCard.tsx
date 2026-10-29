import React, { useState } from 'react';
import { Check, MessageSquare, Pencil, Trash2, X } from 'lucide-react';
import type { Procedure, ProcedureInput } from '../../api/memory';
import { formatDateTime } from '../../utils/metricsFormat';
import { ProcedureEditor } from './ProcedureEditor';
import { KIND_LABELS } from './procedureKinds';

interface ProcedureCardProps {
  procedure: Procedure;
  tools: string[];
  threadTitle?: string;
  onOpenThread?: (threadId: string) => void;
  onSave: (input: ProcedureInput) => Promise<boolean>;
  onApprove: () => void;
  onReject: () => void;
  onDelete: () => void;
}

const STATUS: Record<Procedure['status'], { label: string; className: string }> = {
  proposed: { label: 'da approvare', className: 'text-amber-400 border-amber-400/30 bg-amber-400/10' },
  approved: { label: 'in uso', className: 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10' },
  rejected: { label: 'rifiutata', className: 'text-fg-muted border-border bg-panel' },
};

const SOURCE: Record<string, string> = { user: 'scritta da te', agent: "proposta dall'agente", execution: "ricavata da un'esecuzione" };

/** Una procedura: contenuto, stato e azioni (approva o rifiuta le proposte, modifica, elimina). */
export const ProcedureCard: React.FC<ProcedureCardProps> = ({ procedure, tools, threadTitle, onOpenThread, onSave, onApprove, onReject, onDelete }) => {
  const [isEditing, setIsEditing] = useState(false);
  const status = STATUS[procedure.status];

  if (isEditing) {
    return (
      <div className="rounded-xl border border-accent/40 bg-panel/80 p-3">
        <ProcedureEditor initial={procedure} kindLocked tools={tools} submitLabel="Salva" onSubmit={onSave} onCancel={() => setIsEditing(false)} />
      </div>
    );
  }

  return (
    <article
      className={`group rounded-xl border p-3 transition ${procedure.status === 'proposed' ? 'border-amber-400/40 bg-amber-400/5' : 'border-border bg-panel/60 hover:border-accent/30'} ${procedure.status === 'rejected' ? 'opacity-60' : ''}`}
      aria-label={`Procedura ${procedure.title}`}
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-fg">{procedure.title}</p>
          <p className="text-[11px] text-fg-muted mt-0.5">
            {KIND_LABELS[procedure.kind]}
            {procedure.tool_name && (
              <>
                {' · '}
                <code className="text-fg">{procedure.tool_name}</code>
              </>
            )}
          </p>
        </div>
        <span className={`shrink-0 px-1.5 py-0.5 rounded-md border text-[10px] font-semibold ${status.className}`}>{status.label}</span>
        <div className="flex items-center gap-0.5 shrink-0 opacity-60 group-hover:opacity-100 transition">
          <button onClick={() => setIsEditing(true)} className="p-1 rounded-md text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer" title="Modifica procedura">
            <Pencil size={13} />
          </button>
          <button onClick={onDelete} className="p-1 rounded-md text-fg-muted hover:text-rose-400 hover:bg-panel-hover cursor-pointer" title="Elimina procedura">
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      <p className="mt-2 text-xs text-fg whitespace-pre-wrap leading-relaxed">{procedure.content}</p>

      <div className="flex flex-wrap items-center justify-between gap-2 mt-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-fg-muted">
          <span>{SOURCE[procedure.source] ?? procedure.source}</span>
          {procedure.thread_id && threadTitle && onOpenThread && (
            <button onClick={() => onOpenThread(procedure.thread_id as string)} className="flex items-center gap-1 hover:text-accent truncate max-w-[16rem] cursor-pointer" title="Apri la conversazione">
              <MessageSquare size={11} className="shrink-0" />
              <span className="truncate">{threadTitle}</span>
            </button>
          )}
          {procedure.created_at && <span>{formatDateTime(procedure.created_at)}</span>}
        </div>
        {procedure.status !== 'approved' && (
          <div className="flex gap-1.5">
            {procedure.status === 'proposed' && (
              <button onClick={onReject} className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-border text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
                <X size={12} /> Rifiuta
              </button>
            )}
            <button onClick={onApprove} className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-accent text-white text-xs font-semibold cursor-pointer">
              <Check size={12} /> Approva
            </button>
          </div>
        )}
        {procedure.status === 'approved' && (
          <button onClick={onReject} className="px-2.5 py-1 rounded-lg text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
            Disattiva
          </button>
        )}
      </div>
    </article>
  );
};
