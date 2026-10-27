import React from 'react';
import { Calendar, Layers, Menu, RefreshCw, Shield, Workflow, Zap } from 'lucide-react';

interface AutomationsHeaderProps {
  counts: { automations: number; jobs: number; runs: number; approvals: number };
  isLoading: boolean;
  onRefresh: () => void;
  onOpenMobileSidebar?: () => void;
}

const pill = 'flex items-center gap-1 px-2 py-1 rounded-lg bg-panel/80 border border-border/70 text-[11px] font-medium text-fg-muted shadow-sm shrink-0';

export const AutomationsHeader: React.FC<AutomationsHeaderProps> = ({ counts, isLoading, onRefresh, onOpenMobileSidebar }) => {
  const hasApprovals = counts.approvals > 0;
  return (
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
          <Workflow size={18} />
        </div>
        <div className="min-w-0">
          <h1 className="font-semibold text-xs sm:text-sm text-fg leading-tight truncate">Automations & Loops</h1>
          <p className="text-[10px] sm:text-[11px] text-fg-muted mt-0.5 hidden md:block">
            Workflow schedulati, task ricorrenti e loop agentici supervisionati
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2 overflow-x-auto no-scrollbar py-0.5">
        <div className={pill}>
          <Layers size={12} className="text-accent" />
          <span className="hidden xs:inline">Auto:</span>
          <span className="font-bold text-fg">{counts.automations}</span>
        </div>
        <div className={pill}>
          <Calendar size={12} className="text-emerald-400" />
          <span className="hidden xs:inline">Job:</span>
          <span className="font-bold text-emerald-400">{counts.jobs}</span>
        </div>
        <div className="hidden sm:flex items-center gap-1 px-2 py-1 rounded-lg bg-panel/80 border border-border/70 text-[11px] font-medium text-fg-muted shadow-sm shrink-0">
          <Zap size={12} className="text-amber-400" />
          <span>Run:</span>
          <span className="font-bold text-fg">{counts.runs}</span>
        </div>
        <div
          className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[11px] font-medium shadow-sm shrink-0 ${
            hasApprovals ? 'bg-rose-500/15 border-rose-500/40 text-rose-300 animate-pulse' : 'bg-panel/80 border-border/70 text-fg-muted'
          }`}
        >
          <Shield size={12} className={hasApprovals ? 'text-rose-400' : 'text-fg-muted'} />
          <span className="hidden xs:inline">Approvazioni:</span>
          <span className={`font-bold ${hasApprovals ? 'text-rose-400' : 'text-fg'}`}>{counts.approvals}</span>
        </div>

        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="p-1.5 sm:p-2 text-fg-muted hover:text-fg hover:bg-panel rounded-xl border border-border transition cursor-pointer shrink-0"
          title="Aggiorna dati"
        >
          <RefreshCw size={15} className={isLoading ? 'animate-spin text-accent' : ''} />
        </button>
      </div>
    </div>
  );
};
