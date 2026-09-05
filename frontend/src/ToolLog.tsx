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
    <div className={`border-l border-slate-800 bg-slate-900 flex flex-col transition-all duration-300 ${isOpen ? 'w-80 sm:w-96' : 'w-12'}`}>
      {/* Header / Toggle Button */}
      <div className="p-3 border-b border-slate-800 flex items-center justify-between">
        <button
          onClick={onToggle}
          className="flex items-center gap-2 text-slate-300 hover:text-white transition w-full"
          title={isOpen ? 'Collapse panel' : 'Expand Tool & Plan log'}
        >
          <Activity size={18} className="text-blue-400 shrink-0" />
          {isOpen && <span className="font-semibold text-xs text-slate-200 flex-1 text-left">Agent Diagnostics</span>}
          <ChevronRight size={16} className={`text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>

        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="md:hidden p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded transition ml-1"
            title="Close diagnostics"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {isOpen ? (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Tab switcher: Diagnostics | Knowledge */}
          <div className="flex gap-1 bg-slate-950 rounded-lg p-0.5 border border-slate-800">
            <button
              onClick={() => setTab('diagnostics')}
              className={`flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md text-[10px] font-semibold transition ${
                tab === 'diagnostics' ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Activity size={11} />
              Diagnostics
            </button>
            <button
              onClick={() => setTab('knowledge')}
              className={`flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md text-[10px] font-semibold transition ${
                tab === 'knowledge' ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <BookOpen size={11} />
              Knowledge
            </button>
          </div>

          {tab === 'knowledge' ? (
            /* --- Fase 4.3/4.4: Knowledge Base panel --- */
            <KnowledgePanel />
          ) : (
            <>
          {/* --- Fase 4.2: Pending Approvals (sempre visibile in cima) --- */}
          <ApprovalsPanel threadId={currentThreadId} />

          {/* Active Mode Card */}
          {mode && (
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-1.5">
              <div className="flex items-center gap-2 text-slate-400 text-xs">
                <Zap size={14} className="text-amber-400" />
                <span className="font-medium text-slate-300">Agent Mode</span>
              </div>
              <div className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-mono font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase tracking-wide">
                {mode}
              </div>
            </div>
          )}

          {/* Tool Used Card */}
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-2">
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <Wrench size={14} className="text-emerald-400" />
              <span className="font-medium text-slate-300">Tool Executed</span>
            </div>
            {toolUsed ? (
              <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-3 py-2 rounded-lg text-xs font-mono flex items-center justify-between shadow-sm">
                <span className="truncate">{toolUsed}</span>
                <ShieldCheck size={16} className="text-emerald-400 shrink-0" />
              </div>
            ) : mode === 'chat' || mode === 'ask' ? (
              <div className="bg-slate-900/80 border border-slate-800 text-slate-400 px-3 py-2 rounded-lg text-xs flex items-center gap-2">
                <Info size={14} className="text-blue-400 shrink-0" />
                <span>Info query (no tool execution needed)</span>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">No tool invocation recorded for last query.</p>
            )}
          </div>

          {/* Web Retrieval Context Card */}
          {webPrefetch && (
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 text-slate-400">
                  <Globe size={14} className="text-cyan-400" />
                  <span className="font-medium text-slate-300">Web Context (Prefetch)</span>
                </div>
                {webPrefetch.provider_used && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/50 text-cyan-300">
                    {webPrefetch.provider_used}
                    {webPrefetch.latency_ms ? ` (${webPrefetch.latency_ms}ms)` : ''}
                  </span>
                )}
              </div>

              <div className="text-[11px] text-slate-400 bg-slate-900/60 border border-slate-800/70 rounded-lg p-2 space-y-1">
                <div className="font-mono text-[10px] text-slate-500 truncate">
                  Query: <span className="text-slate-300">"{webPrefetch.query}"</span>
                </div>
                {webPrefetch.sources && webPrefetch.sources.length > 0 ? (
                  <div className="space-y-1.5 pt-1">
                    <div className="text-[10px] text-cyan-400 font-semibold uppercase tracking-wider">
                      {webPrefetch.sources.length} {webPrefetch.sources.length === 1 ? 'Fonte Recuperata' : 'Fonti Recuperate'}
                    </div>
                    <div className="space-y-1 max-h-48 overflow-y-auto pr-1">
                      {webPrefetch.sources.map((src, sIdx) => (
                        <a
                          key={sIdx}
                          href={src.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-cyan-700/50 transition group"
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="text-[11px] font-medium text-slate-200 group-hover:text-cyan-300 truncate">
                              {src.title || src.url}
                            </span>
                            <ExternalLink size={10} className="text-slate-500 group-hover:text-cyan-400 shrink-0" />
                          </div>
                          {src.snippet && (
                            <p className="text-[10px] text-slate-400 line-clamp-2 mt-0.5 leading-tight">
                              {src.snippet}
                            </p>
                          )}
                        </a>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-[10px] text-slate-500 italic">Nessun risultato web trovato per questa query.</p>
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
            <div className="text-center py-8 text-xs text-slate-500">
              Send a prompt to see tool logs and plan execution here.
            </div>
          )}
            </>
          )}
        </div>
      ) : (
        /* Collapsed Vertical Icons */
        <div className="flex-1 py-4 flex flex-col items-center gap-4">
          <div className="p-2 text-slate-400" title="Tool Log Panel (collapsed)">
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
