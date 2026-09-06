import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, ChevronDown, ChevronUp, RotateCcw, Brain, Wrench } from 'lucide-react';
import type { ExecutionTraceItem, RollbackAction } from '../api';
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
        className="w-full glass-card hover:bg-panel border border-border rounded-xl p-2.5 flex items-center justify-between transition-all cursor-pointer group shadow-sm"
        title={isCollapsed ? 'Click to expand reasoning and tool execution details' : 'Click to collapse'}
      >
        <div className="flex items-center gap-2 text-xs font-medium">
          <div className="flex items-center gap-1 text-accent">
            <Brain size={15} />
          </div>
          <span className="text-fg font-semibold">
            {hasReasoning ? 'Reasoning' : 'Process'}
          </span>

          {hasTrace && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-panel border border-border text-[10px] text-accent font-mono">
              <Wrench size={10} />
              {stepsCount} tool {stepsCount === 1 ? 'execution' : 'executions'}
            </span>
          )}

          <span className="text-[10px] text-fg-muted font-mono hidden xs:inline ml-1">
            {isCollapsed ? '(Collapsed)' : '(Expanded)'}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-fg-muted group-hover:text-fg">
          <span className="text-[10px] font-mono uppercase">{isCollapsed ? 'Show' : 'Hide'}</span>
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
                <span>LLM Chain of Thought / Reasoning</span>
              </div>
              <div className="pl-4 border-l-2 border-accent/40 font-sans">
                <MarkdownRenderer content={reasoning} />
              </div>
            </div>
          )}

          {/* Trace steps */}
          {hasTrace && (
            <div className="space-y-2">
              <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider px-1">
                Tool Execution Trace
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
                      <div className="flex items-center gap-2 font-mono text-xs text-fg truncate">
                        <span className="text-accent font-bold">Step {idx + 1}:</span>
                        <span className="truncate font-semibold">{tr.tool_name}</span>
                      </div>

                      <div className="flex items-center gap-1.5 shrink-0">
                        {/* Firecracker Sandbox Badge */}
                        {tr.sandboxed !== undefined && (
                          <span
                            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border ${
                              isSandboxed
                                ? 'bg-purple-500/10 border-purple-500/30 text-purple-300'
                                : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                            }`}
                            title={isSandboxed ? 'KVM Firecracker MicroVM Executed' : 'Local Subprocess Fallback'}
                          >
                            {isSandboxed ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                            {isSandboxed ? 'Firecracker' : 'Fallback'}
                          </span>
                        )}

                        {/* Status indicator */}
                        <span
                          className={`text-[10px] font-bold font-mono px-1.5 py-0.5 rounded ${
                            tr.error
                              ? 'bg-rose-500/10 border border-rose-500/30 text-rose-400'
                              : 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
                          }`}
                        >
                          {tr.error ? 'FAILED' : 'OK'}
                        </span>

                        {/* Step details expand toggle */}
                        {(tr.args || tr.output || tr.result || tr.error || tr.reasoning) && (
                          <button
                            onClick={() => toggleStepExpand(itemId)}
                            className="p-1 text-fg-muted hover:text-fg transition cursor-pointer"
                            title={isStepExpanded ? 'Hide step details' : 'Show step details'}
                          >
                            {isStepExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Step-level Reasoning if present */}
                    {tr.reasoning && (
                      <div className="text-xs text-accent/90 bg-accent/10 p-2 rounded-lg border border-accent/20 flex items-start gap-2">
                        <Brain size={13} className="text-accent shrink-0 mt-0.5" />
                        <span className="italic leading-relaxed">{tr.reasoning}</span>
                      </div>
                    )}

                    {/* Step Details */}
                    {isStepExpanded && (
                      <div className="pt-2 border-t border-border space-y-2 text-[11px] font-mono">
                        {tr.args && (
                          <div>
                            <span className="text-fg-muted block mb-0.5">Parameters:</span>
                            <pre className="bg-panel p-2 rounded-lg text-fg overflow-x-auto border border-border/60">
                              {JSON.stringify(tr.args, null, 2)}
                            </pre>
                          </div>
                        )}

                        {(tr.output || tr.result) && (
                          <div>
                            <span className="text-fg-muted block mb-0.5">Output:</span>
                            <pre className="bg-panel p-2 rounded-lg text-emerald-400 overflow-x-auto whitespace-pre-wrap border border-border/60">
                              {typeof (tr.output || tr.result) === 'string'
                                ? tr.output || tr.result
                                : JSON.stringify(tr.output || tr.result, null, 2)}
                            </pre>
                          </div>
                        )}

                        {tr.error && (
                          <div>
                            <span className="text-rose-400 block mb-0.5">Error detail:</span>
                            <pre className="bg-rose-950/60 p-2 rounded-lg text-rose-300 border border-rose-900/50 overflow-x-auto whitespace-pre-wrap">
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
                <span>Rollback Actions Executed ({rollbackTrace?.length})</span>
              </div>
              <div className="space-y-1.5 text-xs">
                {rollbackTrace?.map((act, idx) => (
                  <div key={idx} className="bg-panel p-2 rounded-lg border border-amber-900/40 font-mono text-[11px]">
                    <div className="flex items-center justify-between text-amber-300">
                      <span>Undo: {act.tool_name}</span>
                      <span className="text-[10px] text-amber-400/80">{act.status || 'Executed'}</span>
                    </div>
                    {act.args && (
                      <div className="text-[10px] text-fg-muted mt-1 truncate">
                        Args: {JSON.stringify(act.args)}
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
