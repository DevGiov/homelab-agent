import React, { useCallback, useEffect, useState } from 'react';
import { ShieldAlert, Check, X, Clock, RefreshCw } from 'lucide-react';
import { listApprovals, approveRequest, denyRequest, type ApprovalItem } from '../api';

interface ApprovalsPanelProps {
  /** threadId per filtrare le richieste (opzionale: vuoto = tutte) */
  threadId?: string | null;
  /** callback chiamata dopo approve/deny per notificare il parent */
  onResolved?: (requestId: string, approved: boolean) => void;
}

export const ApprovalsPanel: React.FC<ApprovalsPanelProps> = ({ threadId, onResolved }) => {
  const [pending, setPending] = useState<ApprovalItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      setPending(await listApprovals(threadId || undefined));
    } catch {
      setPending([]);
    } finally {
      setIsLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    refresh();
    // Polling ogni 10s per nuove richieste
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [refresh]);

  const handleApprove = async (id: string) => {
    setBusyId(id);
    try {
      await approveRequest(id);
      onResolved?.(id, true);
      await refresh();
    } catch (e: any) {
      console.error('Approve failed', e);
    } finally {
      setBusyId(null);
    }
  };

  const handleDeny = async (id: string) => {
    setBusyId(id);
    try {
      await denyRequest(id);
      onResolved?.(id, false);
      await refresh();
    } catch (e: any) {
      console.error('Deny failed', e);
    } finally {
      setBusyId(null);
    }
  };

  const formatAge = (sec: number) => {
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m`;
  };

  return (
    <div className="glass-card border border-border rounded-xl p-3.5 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-fg-muted text-xs">
          <ShieldAlert size={14} className="text-amber-400" />
          <span className="font-medium text-fg">
            Pending Approvals
            {pending.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-bold">
                {pending.length}
              </span>
            )}
          </span>
        </div>
        <button
          onClick={refresh}
          className="p-1 text-fg-muted hover:text-fg transition rounded cursor-pointer"
          title="Refresh approvals"
        >
          <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {pending.length === 0 ? (
        <p className="text-xs text-fg-muted italic">No pending tool approvals.</p>
      ) : (
        <div className="space-y-2">
          {pending.map((item) => (
            <div
              key={item.request_id}
              className="bg-amber-500/5 border border-amber-500/30 rounded-lg p-2.5 space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  onClick={() => setExpandedId(expandedId === item.request_id ? null : item.request_id)}
                  className="flex-1 text-left min-w-0 cursor-pointer"
                  title="Toggle arguments"
                >
                  <div className="text-xs font-mono font-semibold text-amber-300 truncate">
                    {item.tool_name}
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-fg-muted mt-0.5">
                    <Clock size={9} />
                    <span>{formatAge(item.age_seconds)} ago</span>
                    {item.mode && <span className="uppercase">· {item.mode}</span>}
                  </div>
                </button>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => handleApprove(item.request_id)}
                    disabled={busyId === item.request_id}
                    className="flex items-center gap-1 px-2 py-1 rounded-md bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/40 transition text-[10px] font-semibold disabled:opacity-50 cursor-pointer"
                    title="Approve and execute"
                  >
                    <Check size={11} />
                    Approve
                  </button>
                  <button
                    onClick={() => handleDeny(item.request_id)}
                    disabled={busyId === item.request_id}
                    className="flex items-center gap-1 px-2 py-1 rounded-md bg-rose-600/20 border border-rose-500/40 text-rose-300 hover:bg-rose-600/40 transition text-[10px] font-semibold disabled:opacity-50 cursor-pointer"
                    title="Deny request"
                  >
                    <X size={11} />
                    Deny
                  </button>
                </div>
              </div>

              {expandedId === item.request_id && (
                <pre className="bg-panel border border-border rounded-md p-2 text-[10px] font-mono text-fg-muted overflow-x-auto max-h-32">
                  {JSON.stringify(item.arguments, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
