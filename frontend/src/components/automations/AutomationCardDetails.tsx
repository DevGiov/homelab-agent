import React, { useEffect, useState } from 'react';
import { getAutomation, type AutomationSummary } from '../../api/automations';

interface AutomationCardDetailsProps {
  automation: AutomationSummary;
  runsCount: number;
}

const statusColor = (status?: string | null) =>
  status === 'completed' ? 'text-emerald-400' : status === 'failed' ? 'text-rose-400' : 'text-fg';

/** Pannello espandibile della card: statistiche e step della pipeline (caricati alla prima apertura). */
export const AutomationCardDetails: React.FC<AutomationCardDetailsProps> = ({ automation: auto, runsCount }) => {
  const [steps, setSteps] = useState<any[] | null>(null);

  useEffect(() => {
    let active = true;
    getAutomation(auto.id)
      .then((full) => active && setSteps(full?.workflow?.steps ?? []))
      .catch((err) => console.error('Step del workflow non caricati:', err));
    return () => {
      active = false;
    };
  }, [auto.id]);

  return (
    <div className="p-3 rounded-xl bg-bg/80 border border-border/60 space-y-3 animate-in fade-in duration-150">
      <div className="grid grid-cols-3 gap-2 text-[11px]">
        <div className="p-2 rounded-lg bg-panel border border-border/60">
          <span className="text-fg-muted text-[10px] block">Ultima Run</span>
          <span className={`font-semibold text-xs capitalize block truncate ${statusColor(auto.last_run_status)}`}>
            {auto.last_run_status || 'Nessuna'}
          </span>
        </div>
        <div className="p-2 rounded-lg bg-panel border border-border/60">
          <span className="text-fg-muted text-[10px] block">Eseguita Il</span>
          <span className="font-medium text-fg truncate block">
            {auto.last_run_at ? new Date(auto.last_run_at).toLocaleDateString() : '-'}
          </span>
        </div>
        <div className="p-2 rounded-lg bg-panel border border-border/60">
          <span className="text-fg-muted text-[10px] block">Runs Storico</span>
          <span className="font-semibold text-fg">{runsCount}</span>
        </div>
      </div>

      <div className="space-y-1.5 pt-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-muted block">
          Pipeline Step ({steps?.length || auto.steps_count})
        </span>
        {steps ? (
          <div className="space-y-1.5">
            {steps.map((st, idx) => (
              <div
                key={st.step_id || idx}
                className="flex items-center gap-2 text-[11px] p-1.5 rounded-lg bg-panel border border-border/50"
              >
                <span className="w-5 h-5 rounded-md bg-accent/15 text-accent font-mono text-[10px] font-bold flex items-center justify-center shrink-0">
                  {idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-fg truncate block">{st.name}</span>
                  <span className="text-[10px] text-fg-muted font-mono truncate block">{st.action_or_tool || st.type}</span>
                </div>
                <span className="px-1.5 py-0.2 rounded text-[9px] font-mono bg-panel-header text-fg-muted border border-border">
                  {st.type}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-fg-muted italic">Caricamento step del workflow...</div>
        )}
      </div>
    </div>
  );
};
