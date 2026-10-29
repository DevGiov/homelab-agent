import React, { useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import type { ProceduresState } from '../../hooks/useProcedures';
import { ProcedureCard } from './ProcedureCard';
import { ProcedureEditor } from './ProcedureEditor';

interface ProceduresPanelProps {
  state: ProceduresState;
  threadTitles: Map<string, string>;
  onOpenThread: (threadId: string) => void;
  onDelete: (id: number) => void;
}

/** Memoria procedurale: le note sui tool e i piani modello che l'agente segue, e le proposte da approvare. */
export const ProceduresPanel: React.FC<ProceduresPanelProps> = ({ state, threadTitles, onOpenThread, onDelete }) => {
  const [isAdding, setIsAdding] = useState(false);
  const proposed = state.procedures.filter((p) => p.status === 'proposed').length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-fg-muted">
          Le note sui tool compaiono nel catalogo di act e plan; i piani modello entrano nella memoria quando la richiesta è simile.
          {proposed > 0 && <span className="text-amber-400"> {proposed} da approvare.</span>}
        </p>
        <button onClick={() => setIsAdding(true)} className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-accent text-white text-xs font-semibold cursor-pointer">
          <Plus size={12} /> Procedura
        </button>
      </div>

      {isAdding && (
        <div className="rounded-xl border border-accent/40 bg-panel/80 p-3">
          <ProcedureEditor tools={state.tools} submitLabel="Aggiungi" onSubmit={state.create} onCancel={() => setIsAdding(false)} />
        </div>
      )}

      {state.isLoading && state.procedures.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-12 text-xs text-fg-muted">
          <Loader2 size={14} className="animate-spin text-accent" /> Caricamento…
        </div>
      ) : state.procedures.length === 0 ? (
        <p className="text-xs text-fg-muted text-center py-12">
          Nessuna procedura. L'agente ne propone quando un'esecuzione insegna qualcosa o quando gli chiedi di ricordare come si fa; puoi anche scriverle tu.
        </p>
      ) : (
        <div className="space-y-2">
          {state.procedures.map((procedure) => (
            <ProcedureCard
              key={procedure.id}
              procedure={procedure}
              tools={state.tools}
              threadTitle={procedure.thread_id ? threadTitles.get(procedure.thread_id) : undefined}
              onOpenThread={onOpenThread}
              onSave={(input) => state.save(procedure.id, input)}
              onApprove={() => state.approve(procedure.id)}
              onReject={() => state.reject(procedure.id)}
              onDelete={() => onDelete(procedure.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};
