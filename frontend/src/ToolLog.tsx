import React, { useState } from 'react';
import { Wrench, Activity, ShieldCheck, ChevronRight, Zap, X, Info, BookOpen, Globe, ExternalLink } from 'lucide-react';
import type { ExecutionTraceItem, PlanStructure, RollbackAction, WebPrefetchData } from './api';
import { PlanViewer } from './components/PlanViewer';
import { ExecutionTraceViewer } from './components/ExecutionTraceViewer';
import { ApprovalsPanel } from './components/ApprovalsPanel';
import { KnowledgePanel } from './components/KnowledgePanel';

type PanelTab = 'diagnostics' | 'knowledge';

interface ToolLogProps {
  toolUsed?: string;
  planSteps?: string[];
  planStructure?: PlanStructure;
  executionTrace?: ExecutionTraceItem[];
  rollbackTrace?: RollbackAction[];
  mode?: string;
  webPrefetch?: WebPrefetchData;
  currentThreadId?: string | null;
  isOpen: boolean;
  onToggle: () => void;
  onCloseMobile?: () => void;
}

export const ToolLog: React.FC<ToolLogProps> = ({
  toolUsed,
  planSteps,
  planStructure,
  executionTrace,
  rollbackTrace,
  mode,
  webPrefetch,
  currentThreadId,
  isOpen,
  onToggle,
  onCloseMobile,
}) => {
  const [tab, setTab] = useState<PanelTab>('diagnostics');
  const hasContent = Boolean(
    toolUsed ||
    (planSteps && planSteps.length > 0) ||
    planStructure ||
    (executionTrace && executionTrace.length > 0) ||
    (rollbackTrace && rollbackTrace.length > 0) ||
    (webPrefetch && webPrefetch.sources && webPrefetch.sources.length > 0) ||
    mode
  );

  return (
    <div className={`border-l border-border glass-panel flex flex-col transition-all duration-300 ${isOpen ? 'w-80 sm:w-96' : 'w-12'}`}>
      {/* Header / Toggle Button */}
      <div className="p-3 border-b border-border flex items-center justify-between">
        <button
          onClick={onToggle}
          className="flex items-center gap-2 text-fg-muted hover:text-fg transition w-full cursor-pointer"
          title={isOpen ? 'Collapse panel' : 'Expand Tool & Plan log'}
        >
          <Activity size={18} className="text-accent shrink-0" />
          {isOpen && <span className="font-semibold text-xs text-fg flex-1 text-left">Agent Diagnostics</span>}
          <ChevronRight size={16} className={`text-fg-muted transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>

        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="md:hidden p-1 text-fg-muted hover:text-fg hover:bg-panel rounded transition ml-1 cursor-pointer"
            title="Close diagnostics"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {isOpen ? (
        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
          {/* Tab switcher: Diagnostics | Knowledge */}
          <div className="flex gap-1 bg-panel/80 rounded-xl p-1 border border-border">
            <button
              onClick={() => setTab('diagnostics')}
              className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[11px] font-medium transition cursor-pointer ${
                tab === 'diagnostics' ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
              }`}
            >
              <Activity size={12} />
              Diagnostics
            </button>
            <button
              onClick={() => setTab('knowledge')}
              className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[11px] font-medium transition cursor-pointer ${
                tab === 'knowledge' ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
              }`}
            >
              <BookOpen size={12} />
              Knowledge
            </button>
          </div>

          {tab === 'knowledge' ? (
            /* Knowledge Base panel */
            <KnowledgePanel />
          ) : (
            <>
              {/* Pending Approvals */}
              <ApprovalsPanel threadId={currentThreadId} />

              {/* Active Mode Card */}
              {mode && (
                <div className="glass-card border border-border rounded-xl p-3.5 space-y-1.5">
                  <div className="flex items-center gap-2 text-fg-muted text-xs">
                    <Zap size={14} className="text-amber-400" />
                    <span className="font-medium text-fg">Agent Mode</span>
                  </div>
                  <div className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-mono font-bold bg-accent/15 text-accent border border-accent/30 uppercase tracking-wide">
                    {mode}
                  </div>
                </div>
              )}

              {/* Tool Used Card */}
              <div className="glass-card border border-border rounded-xl p-3.5 space-y-2">
                <div className="flex items-center gap-2 text-fg-muted text-xs">
                  <Wrench size={14} className="text-emerald-400" />
                  <span className="font-medium text-fg">Tool Executed</span>
                </div>
                {toolUsed ? (
                  <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-3 py-2 rounded-lg text-xs font-mono flex items-center justify-between shadow-sm">
                    <span className="truncate">{toolUsed}</span>
                    <ShieldCheck size={16} className="text-emerald-400 shrink-0" />
                  </div>
                ) : mode === 'chat' || mode === 'ask' ? (
                  <div className="bg-panel border border-border text-fg-muted px-3 py-2 rounded-lg text-xs flex items-center gap-2">
                    <Info size={14} className="text-accent shrink-0" />
                    <span>Info query (no tool execution needed)</span>
                  </div>
                ) : (
                  <p className="text-xs text-fg-muted italic">No tool invocation recorded for last query.</p>
                )}
              </div>

              {/* Web Retrieval Context Card */}
              {webPrefetch && (
                <div className="glass-card border border-border rounded-xl p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2 text-fg-muted">
                      <Globe size={14} className="text-cyan-400" />
                      <span className="font-medium text-fg">Web Context (Prefetch)</span>
                    </div>
                    {webPrefetch.provider_used && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/50 text-cyan-300">
                        {webPrefetch.provider_used}
                        {webPrefetch.latency_ms ? ` (${webPrefetch.latency_ms}ms)` : ''}
                      </span>
                    )}
                  </div>

                  <div className="text-[11px] text-fg-muted bg-panel border border-border/70 rounded-lg p-2 space-y-1">
                    <div className="font-mono text-[10px] text-fg-muted truncate">
                      Query: <span className="text-fg">"{webPrefetch.query}"</span>
                    </div>
                    {webPrefetch.sources && webPrefetch.sources.length > 0 ? (
                      <div className="space-y-1.5 pt-1">
                        <div className="text-[10px] text-accent font-semibold uppercase tracking-wider">
                          {webPrefetch.sources.length} {webPrefetch.sources.length === 1 ? 'Fonte Recuperata' : 'Fonti Recuperate'}
                        </div>
                        <div className="space-y-1 max-h-48 overflow-y-auto pr-1 custom-scrollbar">
                          {webPrefetch.sources.map((src, sIdx) => (
                            <a
                              key={sIdx}
                              href={src.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block p-1.5 rounded bg-panel-header border border-border/80 hover:border-accent transition group"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="text-[11px] font-medium text-fg group-hover:text-accent truncate">
                                  {src.title || src.url}
                                </span>
                                <ExternalLink size={10} className="text-fg-muted group-hover:text-accent shrink-0" />
                              </div>
                              {src.snippet && (
                                <p className="text-[10px] text-fg-muted line-clamp-2 mt-0.5 leading-tight">
                                  {src.snippet}
                                </p>
                              )}
                            </a>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="text-[10px] text-fg-muted italic">Nessun risultato web trovato per questa query.</p>
                    )}
                  </div>
                </div>
              )}

              {/* Execution Trace & Reasoning Viewer */}
              <ExecutionTraceViewer
                reasoning={executionTrace?.find((t) => t.reasoning)?.reasoning}
                trace={executionTrace}
                rollbackTrace={rollbackTrace}
                compact={true}
                initialCollapsed={false}
              />

              {/* Plan Viewer */}
              <PlanViewer
                planSteps={planSteps}
                planStructure={planStructure}
                compact={true}
              />

              {!hasContent && (
                <div className="text-center py-8 text-xs text-fg-muted">
                  Send a prompt to see tool logs and plan execution here.
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        /* Collapsed Vertical Icons */
        <div className="flex-1 py-4 flex flex-col items-center gap-4">
          <div className="p-2 text-fg-muted hover:text-fg transition" title="Tool Log Panel (collapsed)">
            <Wrench size={16} />
          </div>
          {webPrefetch && (
            <div className="p-2 text-cyan-400" title="Web Retrieval (Prefetch) active">
              <Globe size={16} />
            </div>
          )}
          {toolUsed && (
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" title="Tool activity detected" />
          )}
        </div>
      )}
    </div>
  );
};
