import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, ChevronDown, ChevronUp, RotateCcw, Brain, Wrench } from 'lucide-react';
import type { ExecutionTraceItem, RollbackAction } from '../api/chat';
import { MarkdownRenderer } from './MarkdownRenderer';

interface ExecutionTraceViewerProps {
  reasoning?: string;
  trace?: ExecutionTraceItem[];
  rollbackTrace?: RollbackAction[];
  compact?: boolean;
  initialCollapsed?: boolean;
}

export const ExecutionTraceViewer: React.FC<ExecutionTraceViewerProps> = ({
  reasoning,
  trace,
  rollbackTrace,
  compact = false,
  initialCollapsed = true,
}) => {
  const [isCollapsed, setIsCollapsed] = useState<boolean>(initialCollapsed);
  const [expandedItems, setExpandedItems] = useState<Record<number | string, boolean>>({});

  const hasTrace = Boolean(trace && trace.length > 0);
  const hasRollback = Boolean(rollbackTrace && rollbackTrace.length > 0);
  const hasReasoning = Boolean(reasoning || trace?.some((t) => t.reasoning));

  if (!hasTrace && !hasRollback && !hasReasoning) return null;

  const toggleStepExpand = (id: number | string) => {
    setExpandedItems((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const stepsCount = trace?.length || 0;

  return (
    <div className={`space-y-3 ${compact ? '' : 'mt-3 pt-3 border-t border-border'}`}>
      {/* Auto-Collapsible Header Bar */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        aria-expanded={!isCollapsed}
        className="@container w-full glass-card hover:bg-panel border border-border rounded-xl p-2.5 flex items-center justify-between gap-2 transition-all cursor-pointer group shadow-sm"
        title={isCollapsed ? 'Mostra ragionamento e dettagli dei tool eseguiti' : 'Nascondi i dettagli'}
      >
        <div className="flex items-center gap-2 text-xs font-medium min-w-0">
          <div className="flex items-center gap-1 text-accent">
            <Brain size={15} />
          </div>
          <span className="text-fg font-semibold">
            {hasReasoning ? 'Ragionamento' : 'Elaborazione'}
          </span>

          {hasTrace && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-panel border border-border text-xs text-accent tabular-nums whitespace-nowrap shrink-0">
              <Wrench size={10} />
              {stepsCount} {stepsCount === 1 ? 'tool eseguito' : 'tool eseguiti'}
            </span>
          )}

          <span className="text-xs text-fg-muted hidden @md:inline ml-1">
            {isCollapsed ? '(compresso)' : '(espanso)'}
          </span>
        </div>

        {/* Sotto i 20rem del pulsante (telefono, pannello stretto) resta solo la freccia: lo stato è in aria-expanded */}
        <div className="flex items-center gap-1.5 text-fg-muted group-hover:text-fg shrink-0">
          <span className="text-xs uppercase hidden @xs:inline">{isCollapsed ? 'Mostra' : 'Nascondi'}</span>
          {isCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        </div>
      </button>

      {/* Expanded Content View */}
      {!isCollapsed && (
        <div className="space-y-3 pt-1 animate-in fade-in duration-200">
          {/* Global or Step-level Reasoning Block */}
          {reasoning && (
            <div className="glass-card border border-border/80 rounded-xl p-3 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs text-accent font-semibold">
                <Brain size={14} className="text-accent" />
                <span>Ragionamento del modello</span>
              </div>
              <div className="pl-4 border-l-2 border-accent/40 font-sans">
                <MarkdownRenderer content={reasoning} />
              </div>
            </div>
          )}

          {/* Trace steps */}
          {hasTrace && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-fg-muted uppercase tracking-wider px-1">
                Traccia dei tool
              </div>
              {trace?.map((tr, idx) => {
                const itemId = tr.step_id || idx;
                const isStepExpanded = Boolean(expandedItems[itemId]);
                const isSandboxed = tr.sandboxed === true;

                return (
                  <div
                    key={itemId}
                    className="glass-card border border-border rounded-xl p-3 space-y-2 transition"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-xs text-fg truncate">
                        <span className="text-accent font-bold tabular-nums">Step {idx + 1}:</span>
                        <span className="truncate font-semibold font-mono">{tr.tool_name}</span>
                      </div>

                      <div className="flex items-center gap-1.5 shrink-0">
                        {/* Firecracker Sandbox Badge */}
                        {tr.sandboxed !== undefined && (
                          <span
                            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs border ${
                              isSandboxed
                                ? 'bg-purple-500/10 border-purple-500/30 text-purple-300'
                                : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                            }`}
                            title={isSandboxed ? 'Eseguito in una microVM Firecracker (KVM)' : 'Eseguito in un sottoprocesso locale, senza sandbox'}
                          >
                            {isSandboxed ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                            {isSandboxed ? 'Firecracker' : 'Locale'}
                          </span>
                        )}

                        {tr.clean_rewrite && (
                          <span
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs border bg-sky-500/10 border-sky-500/30 text-sky-300"
                            title="La destinazione non poteva ricevere i dati di questo turno: gli argomenti li ha scritti una chiamata che vedeva solo la richiesta e i dati pubblici"
                            data-testid="clean-rewrite"
                          >
                            <ShieldCheck size={10} aria-hidden="true" />
                            Senza dati riservati
                          </span>
                        )}

                        {/* Status indicator */}
                        <span
                          className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                            tr.error
                              ? 'bg-rose-500/10 border border-rose-500/30 text-rose-300'
                              : 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
                          }`}
                        >
                          {tr.error ? 'ERRORE' : 'OK'}
                        </span>

                        {/* Step details expand toggle */}
                        {(tr.args || tr.output || tr.result || tr.error || tr.reasoning) && (
                          <button
                            onClick={() => toggleStepExpand(itemId)}
                            aria-expanded={isStepExpanded}
                            aria-label={isStepExpanded ? 'Nascondi i dettagli dello step' : 'Mostra i dettagli dello step'}
                            className="p-1 text-fg-muted hover:text-fg transition cursor-pointer"
                            title={isStepExpanded ? 'Nascondi i dettagli dello step' : 'Mostra i dettagli dello step'}
                          >
                            {isStepExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Step-level Reasoning if present */}
                    {tr.reasoning && (
                      <div className="text-xs text-fg bg-accent/10 p-2 rounded-lg border border-accent/20 flex items-start gap-2">
                        <Brain size={13} className="text-accent shrink-0 mt-0.5" />
                        <span className="italic leading-relaxed">{tr.reasoning}</span>
                      </div>
                    )}

                    {/* Step Details */}
                    {isStepExpanded && (
                      <div className="pt-2 border-t border-border space-y-2 text-xs">
                        {tr.args && (
                          <div>
                            <span className="text-fg-muted block mb-0.5">Parametri:</span>
                            <pre className="bg-panel p-2 rounded-lg text-fg font-mono overflow-x-auto border border-border/60">
                              {JSON.stringify(tr.args, null, 2)}
                            </pre>
                          </div>
                        )}

                        {tr.clean_rewrite && (
                          <div>
                            <span className="text-fg-muted block mb-0.5">
                              Argomenti scritti dal modello con i dati {tr.clean_rewrite.turn_label} del turno (non inviati):
                            </span>
                            <pre className="bg-panel p-2 rounded-lg text-fg-muted font-mono overflow-x-auto border border-border/60">
                              {JSON.stringify(tr.clean_rewrite.original_args, null, 2)}
                            </pre>
                          </div>
                        )}

                        {(tr.output || tr.result) && (
                          <div>
                            <span className="text-fg-muted block mb-0.5">Output:</span>
                            <pre className="bg-panel p-2 rounded-lg text-emerald-400 font-mono overflow-x-auto whitespace-pre-wrap border border-border/60">
                              {typeof (tr.output || tr.result) === 'string'
                                ? tr.output || tr.result
                                : JSON.stringify(tr.output || tr.result, null, 2)}
                            </pre>
                          </div>
                        )}

                        {tr.error && (
                          <div>
                            <span className="text-rose-400 block mb-0.5">Dettaglio dell'errore:</span>
                            <pre className="bg-rose-950/60 p-2 rounded-lg text-rose-300 font-mono border border-rose-900/50 overflow-x-auto whitespace-pre-wrap">
                              {tr.error}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Rollback Actions */}
          {hasRollback && (
            <div className="bg-amber-950/40 border border-amber-800/60 rounded-xl p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs text-amber-400 font-semibold">
                <RotateCcw size={14} />
                <span>Azioni di rollback eseguite ({rollbackTrace?.length})</span>
              </div>
              <div className="space-y-1.5 text-xs">
                {rollbackTrace?.map((act, idx) => (
                  <div key={idx} className="bg-panel p-2 rounded-lg border border-amber-900/40 font-mono text-xs">
                    <div className="flex items-center justify-between text-amber-300">
                      <span>Annulla: {act.tool_name}</span>
                      <span className="text-xs text-amber-400">{act.status || 'eseguita'}</span>
                    </div>
                    {act.args && (
                      <div className="text-xs text-fg-muted mt-1 truncate">
                        Argomenti: {JSON.stringify(act.args)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
