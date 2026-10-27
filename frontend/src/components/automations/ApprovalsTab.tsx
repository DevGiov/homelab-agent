import React from 'react';
import { Check, CheckCircle, Shield, Trash2, X } from 'lucide-react';
import {
  clearExpiredAutomationApprovals,
  deleteAutomationApproval,
  resolveAutomationApproval,
  type AutomationApprovalItem,
} from '../../api/automationRuns';
import type { Notify } from '../../hooks/useFeedback';
import { formatApiError } from '../../utils/error';

interface ApprovalsTabProps {
  approvals: AutomationApprovalItem[];
  notify: Notify;
  reload: () => void;
}

export const ApprovalsTab: React.FC<ApprovalsTabProps> = ({ approvals, notify, reload }) => {
  const attempt = async (action: () => Promise<string>, failure: string) => {
    try {
      notify('success', await action());
      reload();
    } catch (err) {
      notify('error', `${failure}: ${formatApiError(err)}`);
    }
  };

  const resolve = (apr: AutomationApprovalItem, action: 'approve' | 'deny') =>
    attempt(async () => {
      await resolveAutomationApproval(apr.run_id, apr.request_id, action);
      return `Richiesta ${action === 'approve' ? 'approvata ed eseguita' : 'negata'} con successo.`;
    }, 'Errore risoluzione');

  const remove = (requestId: string) => {
    if (!confirm('Sei sicuro di voler eliminare questa richiesta di approvazione?')) return;
    attempt(async () => {
      await deleteAutomationApproval(requestId);
      return 'Richiesta di approvazione eliminata.';
    }, 'Errore eliminazione');
  };

  const clearExpired = () =>
    attempt(async () => {
      const res = await clearExpiredAutomationApprovals();
      return `Rimosse ${res.cleared_count} approvazioni scadute.`;
    }, 'Errore pulizia scadute');

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">Richieste di Approvazione in Sospeso</h2>
        <button
          onClick={clearExpired}
          className="px-2.5 py-1 text-xs text-fg-muted hover:text-fg bg-panel border border-border hover:border-accent/40 rounded-lg flex items-center gap-1.5 transition"
          title="Rimuovi le richieste di approvazione scadute"
        >
          <Trash2 size={13} />
          <span>Pulisci Scadute</span>
        </button>
      </div>

      {approvals.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-border rounded-xl p-6 bg-panel/20">
          <CheckCircle className="mx-auto text-emerald-400 mb-2" size={32} />
          <h3 className="text-sm font-semibold text-fg">Nessuna approvazione pendente</h3>
          <p className="text-xs text-fg-muted mt-1">
            Tutti i workflow e le sessioni stanno procedendo normalmente entro i limiti autorizzati.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((apr) => {
            const isWorkflow = Boolean(apr.step_run_id);
            return (
              <div key={apr.request_id} className="p-4 rounded-xl bg-panel border border-amber-500/40 shadow-md space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <span className="p-1.5 rounded-lg bg-amber-500/20 text-amber-400">
                      <Shield size={16} />
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-bold text-fg">Azione Richiesta: {apr.tool_name}</h4>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                            isWorkflow ? 'bg-accent/15 text-accent border-accent/30' : 'bg-sky-500/15 text-sky-400 border-sky-500/30'
                          }`}
                        >
                          {isWorkflow ? 'Workflow' : 'Chat Session'}
                        </span>
                      </div>
                      <span className="text-[11px] font-mono text-fg-muted">
                        {isWorkflow ? 'Run' : 'Session'}: {apr.run_id} • Req: {apr.request_id}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => resolve(apr, 'approve')}
                      className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition"
                    >
                      <Check size={14} /> Approva ed Esegui
                    </button>
                    <button
                      onClick={() => resolve(apr, 'deny')}
                      className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-medium flex items-center gap-1 transition"
                    >
                      <X size={14} /> Nega
                    </button>
                    <button
                      onClick={() => remove(apr.request_id)}
                      className="p-1.5 text-fg-muted hover:text-rose-400 hover:bg-rose-950/30 rounded-lg transition"
                      title="Elimina richiesta"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-bg/60 border border-border/60 text-xs space-y-1.5">
                  <div className="text-fg-muted">
                    <span className="font-semibold text-fg">Motivo Guardrail:</span> {apr.risk_reason || 'Conferma richiesta da policy.'}
                  </div>
                  {apr.command_preview && <div className="font-mono text-[11px] text-amber-300">preview: {apr.command_preview}</div>}
                  {apr.arguments && (
                    <pre className="text-[11px] text-fg-muted overflow-x-auto max-h-32 mt-1">
                      {JSON.stringify(apr.arguments, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
