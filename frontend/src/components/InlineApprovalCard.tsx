import React, { useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  Check,
  X,
  Terminal,
  MessageSquare,
  AlertTriangle,
  Loader2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  resolveApproval,
  type ApprovalAction,
  type ResolveApprovalResponse,
} from '../api';

export interface InlineApprovalCardProps {
  requestId: string;
  toolName: string;
  argumentsData?: Record<string, any>;
  commandPreview?: string;
  commandPrefix?: string;
  riskReason?: string;
  threadId?: string | null;
  isResolvedInitially?: boolean;
  resolvedActionInitially?: string;
  onResolved?: (action: ApprovalAction, result: ResolveApprovalResponse) => void;
}

export const InlineApprovalCard: React.FC<InlineApprovalCardProps> = ({
  requestId,
  toolName,
  argumentsData,
  commandPreview,
  commandPrefix,
  riskReason,
  threadId: _threadId,
  isResolvedInitially = false,
  resolvedActionInitially,
  onResolved,
}) => {
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [activeAction, setActiveAction] = useState<ApprovalAction | null>(null);
  const [resolved, setResolved] = useState<boolean>(isResolvedInitially);
  const [resolvedAction, setResolvedAction] = useState<string | null>(resolvedActionInitially || null);
  const [resolvedResult, setResolvedResult] = useState<any | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isArgsExpanded, setIsArgsExpanded] = useState<boolean>(false);

  const handleResolve = async (action: ApprovalAction) => {
    setIsLoading(true);
    setActiveAction(action);
    setErrorMsg(null);
    try {
      const res = await resolveApproval(requestId, action);
      setResolved(true);
      setResolvedAction(action);
      if (res.result) {
        setResolvedResult(res.result);
      }
      onResolved?.(action, res);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Errore durante la risoluzione';
      setErrorMsg(msg);
    } finally {
      setIsLoading(false);
      setActiveAction(null);
    }
  };

  const previewCmd =
    commandPreview ||
    (argumentsData?.command as string) ||
    (argumentsData?.cmd as string) ||
    null;

  const displayPrefix = commandPrefix || (previewCmd ? previewCmd.split(/\s+/).slice(0, 2).join(' ') : null);

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-amber-500/40 bg-amber-950/20 backdrop-blur-md shadow-lg transition-all duration-200">
      {/* Header bar */}
      <div className="flex items-center justify-between gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400">
            <ShieldAlert size={16} />
          </div>
          <div className="min-w-0">
            <h4 className="text-xs font-semibold text-amber-200 truncate">
              Autorizzazione Tool Richiesta (Guardrail)
            </h4>
            <div className="text-[10px] text-amber-300/80 font-mono">
              ID: {requestId}
            </div>
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-amber-500/40 bg-amber-500/20 px-2.5 py-0.5 font-mono text-[11px] font-bold text-amber-300">
          {toolName}
        </span>
      </div>

      {/* Card Content */}
      <div className="p-4 space-y-3">
        {/* Risk motivation */}
        {riskReason && (
          <div className="flex items-start gap-2 text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/20 rounded-lg p-2.5">
            <AlertTriangle size={15} className="shrink-0 mt-0.5 text-amber-400" />
            <span>{riskReason}</span>
          </div>
        )}

        {/* Command Terminal Preview */}
        {previewCmd && (
          <div className="rounded-lg border border-border/80 bg-black/60 p-3 font-mono text-xs text-emerald-400 overflow-x-auto shadow-inner">
            <div className="flex items-center justify-between gap-2 mb-1.5 text-[10px] text-fg-muted select-none">
              <span className="flex items-center gap-1.5">
                <Terminal size={12} className="text-accent" />
                Comando shell proposto:
              </span>
              {displayPrefix && (
                <span className="text-fg-muted">
                  Prefisso: <code className="text-emerald-300 font-semibold">{displayPrefix}</code>
                </span>
              )}
            </div>
            <div className="whitespace-pre-wrap break-all select-all font-semibold">
              $ {previewCmd}
            </div>
          </div>
        )}

        {/* Arguments Toggle */}
        {argumentsData && Object.keys(argumentsData).length > 0 && (
          <div>
            <button
              onClick={() => setIsArgsExpanded(!isArgsExpanded)}
              className="flex items-center gap-1.5 text-[11px] text-fg-muted hover:text-fg transition cursor-pointer"
            >
              {isArgsExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              <span>{isArgsExpanded ? 'Nascondi parametri completi' : 'Mostra parametri completi'}</span>
            </button>
            {isArgsExpanded && (
              <pre className="mt-2 rounded-lg border border-border bg-panel/90 p-2.5 font-mono text-[10px] text-fg-muted overflow-x-auto max-h-48">
                {JSON.stringify(argumentsData, null, 2)}
              </pre>
            )}
          </div>
        )}

        {/* Error message */}
        {errorMsg && (
          <div className="flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-xs text-rose-300">
            <X size={15} className="shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Resolved Status Banner */}
        {resolved ? (
          <div className="pt-1">
            {resolvedAction === 'deny' && (
              <div className="flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-xs font-medium text-rose-300">
                <X size={16} className="shrink-0 text-rose-400" />
                <span>Esecuzione rifiutata dall'utente. Il tool non è stato eseguito.</span>
              </div>
            )}
            {resolvedAction === 'approve' && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-2.5 text-xs font-medium text-emerald-300">
                <Check size={16} className="shrink-0 text-emerald-400" />
                <span>Tool autorizzato ed eseguito per questa singola chiamata (one-time).</span>
              </div>
            )}
            {resolvedAction === 'approve_thread' && (
              <div className="flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 p-2.5 text-xs font-medium text-sky-300">
                <MessageSquare size={16} className="shrink-0 text-sky-400" />
                <span>
                  Tool autorizzato per l'intera conversazione corrente
                  {displayPrefix ? ` (prefisso: "${displayPrefix}")` : ''}.
                </span>
              </div>
            )}
            {resolvedAction === 'approve_always' && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-2.5 text-xs font-medium text-emerald-300">
                <ShieldCheck size={16} className="shrink-0 text-emerald-400" />
                <span>
                  Tool autorizzato permanentemente
                  {displayPrefix ? ` per "${displayPrefix}"` : ''} (salvato nei permessi globali).
                </span>
              </div>
            )}

            {/* Execution Result summary if available */}
            {resolvedResult && (
              <div className="mt-2.5 rounded-lg border border-border bg-panel p-2.5 font-mono text-[10px] text-fg-muted overflow-x-auto max-h-48">
                <div className="text-[11px] font-semibold text-fg mb-1">Risultato esecuzione:</div>
                <pre>{typeof resolvedResult === 'string' ? resolvedResult : JSON.stringify(resolvedResult, null, 2)}</pre>
              </div>
            )}
          </div>
        ) : (
          /* The 4 Action Buttons */
          <div className="space-y-2 pt-1">
            <div className="text-[11px] font-medium text-fg-muted">
              Scegli come procedere per questo tool:
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {/* Option 1: No (Rifiuta) */}
              <button
                onClick={() => handleResolve('deny')}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 rounded-lg border border-rose-500/50 bg-rose-600/20 px-3 py-2.5 text-xs font-semibold text-rose-200 hover:bg-rose-600/35 hover:border-rose-500 transition disabled:opacity-50 cursor-pointer shadow-sm"
              >
                {isLoading && activeAction === 'deny' ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <X size={14} className="text-rose-400" />
                )}
                <span>No (Rifiuta)</span>
              </button>

              {/* Option 2: Sì (Una volta) */}
              <button
                onClick={() => handleResolve('approve')}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 rounded-lg border border-slate-600/60 bg-slate-700/40 px-3 py-2.5 text-xs font-semibold text-slate-100 hover:bg-slate-700/60 hover:border-slate-500 transition disabled:opacity-50 cursor-pointer shadow-sm"
              >
                {isLoading && activeAction === 'approve' ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} className="text-emerald-400" />
                )}
                <span>Sì (Una volta)</span>
              </button>

              {/* Option 3: Sì (In questa chat per &cmd) */}
              <button
                onClick={() => handleResolve('approve_thread')}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 rounded-lg border border-sky-500/50 bg-sky-600/20 px-3 py-2.5 text-xs font-semibold text-sky-200 hover:bg-sky-600/35 hover:border-sky-500 transition disabled:opacity-50 cursor-pointer shadow-sm text-center"
                title="Consenti per tutti i turni di questo thread senza richiedere ulteriori conferme"
              >
                {isLoading && activeAction === 'approve_thread' ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <MessageSquare size={14} className="text-sky-400 shrink-0" />
                )}
                <span className="truncate">
                  Sì, in questa chat {displayPrefix ? `(${displayPrefix})` : ''}
                </span>
              </button>

              {/* Option 4: Sì (Sempre per &cmd) */}
              <button
                onClick={() => handleResolve('approve_always')}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-3 py-2.5 text-xs font-bold text-emerald-200 hover:bg-emerald-600/35 hover:border-emerald-500 transition disabled:opacity-50 cursor-pointer shadow-sm text-center"
                title="Salva autorizzazione persistente: non verrà mai più richiesta per questo comando"
              >
                {isLoading && activeAction === 'approve_always' ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <ShieldCheck size={14} className="text-emerald-400 shrink-0" />
                )}
                <span className="truncate">
                  Sì, sempre {displayPrefix ? `(${displayPrefix})` : `(${toolName})`}
                </span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
