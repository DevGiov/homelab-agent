import React from 'react';
import { Calendar, Layers, Menu, RefreshCw, Shield, Workflow, Zap } from 'lucide-react';

interface AutomationsHeaderProps {
  counts: { automations: number; jobs: number; runs: number; approvals: number };
  isLoading: boolean;
  onRefresh: () => void;
  onOpenMobileSidebar?: () => void;
}

const pill = 'flex items-center gap-1 px-2 py-1 rounded-lg bg-panel/80 border border-border/70 text-xs font-medium text-fg-muted shadow-sm shrink-0';
// Nell'intestazione stretta la pillola mostra icona e numero; l'etichetta resta per i lettori di schermo
const pillLabel = 'sr-only @3xl:not-sr-only';

export const AutomationsHeader: React.FC<AutomationsHeaderProps> = ({ counts, isLoading, onRefresh, onOpenMobileSidebar }) => {
  const hasApprovals = counts.approvals > 0;
  return (
    // Container query: la vista è più stretta della finestra quando la barra laterale è aperta, quindi etichette, sottotitolo e
    // pillola delle run seguono la larghezza dell'intestazione, non quella della finestra.
    // Niente si taglia: il titolo va a capo tra le parole (il titolo occupa almeno la sua parola più lunga, `flex-1` senza
    // `min-w-0`), e se titolo e pillole non stanno su una riga le pillole passano sotto, a destra
    <div className="@container p-2.5 sm:p-3.5 border-b border-border bg-panel-header/40 backdrop-blur-md flex flex-wrap items-center justify-between gap-2 shrink-0">
      <div className="flex-1 flex items-center gap-2 sm:gap-3">
        {onOpenMobileSidebar && (
          <button
            type="button"
            onClick={onOpenMobileSidebar}
            className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition shrink-0 cursor-pointer"
            title="Apri menu principale"
            aria-label="Apri menu principale"
          >
            <Menu size={20} />
          </button>
        )}
        {/* Il logo cede il posto al titolo quando l'intestazione ha meno di 24rem di contenuto (@sm, padding escluso) */}
        <div className="hidden @sm:flex w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-accent/15 border border-accent/30 items-center justify-center text-accent shadow-sm shrink-0">
          <Workflow size={18} />
        </div>
        <div>
          <h2 className="font-semibold text-xs sm:text-sm text-fg leading-tight">Automazioni e loop</h2>
          <p className="text-xs text-fg-muted mt-0.5 hidden @4xl:block">
            Workflow schedulati, task ricorrenti e loop agentici supervisionati
          </p>
        </div>
      </div>

      <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5 sm:gap-2 py-0.5">
        <div className={pill}>
          <Layers size={12} className="text-accent" />
          <span className={pillLabel}>Auto:</span>
          <span className="font-bold text-fg">{counts.automations}</span>
        </div>
        <div className={pill}>
          <Calendar size={12} className="text-emerald-400" />
          <span className={pillLabel}>Job:</span>
          <span className="font-bold text-emerald-400">{counts.jobs}</span>
        </div>
        <div className="hidden @xl:flex items-center gap-1 px-2 py-1 rounded-lg bg-panel/80 border border-border/70 text-xs font-medium text-fg-muted shadow-sm shrink-0">
          <Zap size={12} className="text-amber-400" />
          <span>Run:</span>
          <span className="font-bold text-fg">{counts.runs}</span>
        </div>
        <div
          className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-xs font-medium shadow-sm shrink-0 ${
            hasApprovals ? 'bg-rose-500/15 border-rose-500/40 text-rose-300 animate-tint-pulse' : 'bg-panel/80 border-border/70 text-fg-muted'
          }`}
        >
          <Shield size={12} className={hasApprovals ? 'text-rose-400' : 'text-fg-muted'} />
          <span className={pillLabel}>Approvazioni:</span>
          <span className={`font-bold ${hasApprovals ? 'text-rose-400' : 'text-fg'}`}>{counts.approvals}</span>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="p-1.5 sm:p-2 text-fg-muted hover:text-fg hover:bg-panel rounded-xl border border-border transition cursor-pointer shrink-0"
          title="Aggiorna dati"
          aria-label="Aggiorna dati"
        >
          <RefreshCw size={15} className={isLoading ? 'animate-spin text-accent' : ''} />
        </button>
      </div>
    </div>
  );
};
