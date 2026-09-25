import React, { useState } from 'react';
import {
  Wrench,
  Activity,
  ShieldCheck,
  ChevronRight,
  Zap,
  X,
  Info,
  BookOpen,
  Globe,
  ExternalLink,
  MessageSquare,
} from 'lucide-react';
import type {
  ExecutionTraceItem,
  PlanStructure,
  RollbackAction,
  WebPrefetchData,
  FormattedMessage,
} from './api';
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
  messages?: FormattedMessage[];
  selectedMessageId?: string | null;
  onSelectMessageId?: (id: string | null) => void;
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
  messages,
  selectedMessageId,
  onSelectMessageId,
}) => {
  const [tab, setTab] = useState<PanelTab>('diagnostics');

  // Filter assistant messages for selection
  const assistantMessages = (messages || []).filter((m) => m.sender === 'assistant');
  const selectedMsg = selectedMessageId
    ? assistantMessages.find((m) => m.id === selectedMessageId)
    : null;

  // Derive active values: if a specific message is selected, inspect that message; otherwise use live/props
  const activeMode = selectedMsg ? selectedMsg.mode : mode;
  const activeTool = selectedMsg ? selectedMsg.tool_used : toolUsed;
  const activePlanSteps = selectedMsg ? selectedMsg.plan_steps : planSteps;
  const activePlanStructure = selectedMsg ? selectedMsg.plan_structure : planStructure;
  const activeExecutionTrace = selectedMsg ? selectedMsg.execution_trace : executionTrace;
  const activeRollbackTrace = selectedMsg ? selectedMsg.rollback_trace : rollbackTrace;
  const activeWebPrefetch = selectedMsg ? selectedMsg.web_prefetch : webPrefetch;

  const hasContent = Boolean(
    activeTool ||
    (activePlanSteps && activePlanSteps.length > 0) ||
    activePlanStructure ||
    (activeExecutionTrace && activeExecutionTrace.length > 0) ||
    (activeRollbackTrace && activeRollbackTrace.length > 0) ||
    (activeWebPrefetch && activeWebPrefetch.sources && activeWebPrefetch.sources.length > 0) ||
    activeMode
  );

  return (
    <div
      className={`border-l border-border glass-panel flex flex-col transition-all duration-300 h-full w-[85vw] max-w-sm md:max-w-none ${
        isOpen ? 'md:w-80 lg:w-96' : 'md:w-12'
      }`}
    >
      {/* Header / Toggle Button */}
      <div className="p-3 border-b border-border flex items-center justify-between shrink-0">
        <button
          onClick={onToggle}
          className="flex items-center gap-2 text-fg-muted hover:text-fg transition w-full cursor-pointer min-w-0"
          title={isOpen ? 'Collassa pannello' : 'Espandi log Tool & Diagnostica'}
        >
          <Activity size={18} className="text-accent shrink-0" />
          {isOpen && (
            <span className="font-semibold text-xs text-fg flex-1 text-left truncate">
              Agent Diagnostics
            </span>
          )}
          <ChevronRight
            size={16}
            className={`text-fg-muted transition-transform shrink-0 hidden md:block ${
              isOpen ? 'rotate-180' : ''
            }`}
          />
        </button>

        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition ml-1 cursor-pointer shrink-0"
            title="Chiudi diagnostica"
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
                tab === 'diagnostics'
                  ? 'bg-accent text-white shadow-sm shadow-accent/25'
                  : 'text-fg-muted hover:text-fg'
              }`}
            >
              <Activity size={12} />
              Diagnostics
            </button>
            <button
              onClick={() => setTab('knowledge')}
              className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[11px] font-medium transition cursor-pointer ${
                tab === 'knowledge'
                  ? 'bg-accent text-white shadow-sm shadow-accent/25'
                  : 'text-fg-muted hover:text-fg'
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
              {/* Message Selector */}
              {assistantMessages.length > 0 && (
                <div className="flex flex-col gap-1.5 p-2.5 rounded-xl bg-panel/70 border border-border text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-fg-muted min-w-0">
                      <MessageSquare size={13} className="text-accent shrink-0" />
                      <span className="text-[11px] font-medium truncate">Messaggio:</span>
                    </div>
                    <select
                      value={selectedMessageId || 'latest'}
                      onChange={(e) =>
                        onSelectMessageId?.(e.target.value === 'latest' ? null : e.target.value)
                      }
                      className="bg-input-bg border border-input-border text-fg rounded-lg px-2 py-1 text-[11px] max-w-[170px] sm:max-w-[200px] truncate focus:outline-none focus:border-accent"
                    >
                      <option value="latest">⚡ Ultimo / Live ({assistantMessages.length})</option>
                      {assistantMessages.map((m, idx) => {
                        let timeStr = '';
                        if (m.timestamp) {
                          if (m.timestamp.includes(':') && !m.timestamp.includes('T') && !m.timestamp.includes('-')) {
                            timeStr = m.timestamp;
                          } else {
                            const d = new Date(m.timestamp);
                            if (!isNaN(d.getTime())) {
                              timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                            }
                          }
                        }
                        return (
                          <option key={m.id} value={m.id}>
                            #{idx + 1} [{m.mode || 'agent'}] {timeStr}
                          </option>
                        );
                      })}
                    </select>
                  </div>

                  {selectedMessageId && (
                    <div className="flex items-center justify-between px-2 py-1 rounded-md bg-accent/10 border border-accent/20 text-accent text-[11px]">
                      <span className="truncate">
                        Ispezione msg #{assistantMessages.findIndex((m) => m.id === selectedMessageId) + 1}
                      </span>
                      <button
                        onClick={() => onSelectMessageId?.(null)}
                        className="underline text-[10px] hover:text-white font-medium ml-2 cursor-pointer shrink-0"
                      >
                        Torna a Live
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Pending Approvals */}
              <ApprovalsPanel threadId={currentThreadId} />

              {/* Active Mode Card */}
              {activeMode && (
                <div className="glass-card border border-border rounded-xl p-3.5 space-y-1.5">
                  <div className="flex items-center gap-2 text-fg-muted text-xs">
                    <Zap size={14} className="text-amber-400" />
                    <span className="font-medium text-fg">Agent Mode</span>
                  </div>
                  <div className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-mono font-bold bg-accent/15 text-accent border border-accent/30 uppercase tracking-wide">
                    {activeMode}
                  </div>
                </div>
              )}

              {/* Tool Used Card */}
              <div className="glass-card border border-border rounded-xl p-3.5 space-y-2">
                <div className="flex items-center gap-2 text-fg-muted text-xs">
                  <Wrench size={14} className="text-emerald-400" />
                  <span className="font-medium text-fg">Tool Executed</span>
                </div>
                {activeTool ? (
                  <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-3 py-2 rounded-lg text-xs font-mono flex items-center justify-between shadow-sm">
                    <span className="truncate">{activeTool}</span>
                    <ShieldCheck size={16} className="text-emerald-400 shrink-0" />
                  </div>
                ) : activeMode === 'chat' || activeMode === 'ask' ? (
                  <div className="bg-panel border border-border text-fg-muted px-3 py-2 rounded-lg text-xs flex items-center gap-2">
                    <Info size={14} className="text-accent shrink-0" />
                    <span>Info query (no tool execution needed)</span>
                  </div>
                ) : (
                  <p className="text-xs text-fg-muted italic">Nessun tool registrato per questa query.</p>
                )}
              </div>

              {/* Web Retrieval Context Card */}
              {activeWebPrefetch && (
                <div className="glass-card border border-border rounded-xl p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2 text-fg-muted">
                      <Globe size={14} className="text-cyan-400" />
                      <span className="font-medium text-fg">Web Context (Prefetch)</span>
                    </div>
                    {activeWebPrefetch.provider_used && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/50 text-cyan-300">
                        {activeWebPrefetch.provider_used}
                        {activeWebPrefetch.latency_ms ? ` (${activeWebPrefetch.latency_ms}ms)` : ''}
                      </span>
                    )}
                  </div>

                  <div className="text-[11px] text-fg-muted bg-panel border border-border/70 rounded-lg p-2 space-y-1">
                    <div className="font-mono text-[10px] text-fg-muted truncate">
                      Query: <span className="text-fg">"{activeWebPrefetch.query}"</span>
                    </div>
                    {activeWebPrefetch.sources && activeWebPrefetch.sources.length > 0 ? (
                      <div className="space-y-1.5 pt-1">
                        <div className="text-[10px] text-accent font-semibold uppercase tracking-wider">
                          {activeWebPrefetch.sources.length}{' '}
                          {activeWebPrefetch.sources.length === 1
                            ? 'Fonte Recuperata'
                            : 'Fonti Recuperate'}
                        </div>
                        <div className="space-y-1 max-h-48 overflow-y-auto pr-1 custom-scrollbar">
                          {activeWebPrefetch.sources.map((src, sIdx) => (
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
                                <ExternalLink
                                  size={10}
                                  className="text-fg-muted group-hover:text-accent shrink-0"
                                />
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
                      <p className="text-[10px] text-fg-muted italic">
                        Nessun risultato web trovato per questa query.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Execution Trace & Reasoning Viewer */}
              <ExecutionTraceViewer
                reasoning={activeExecutionTrace?.find((t) => t.reasoning)?.reasoning}
                trace={activeExecutionTrace}
                rollbackTrace={activeRollbackTrace}
                compact={true}
                initialCollapsed={false}
              />

              {/* Plan Viewer */}
              <PlanViewer
                planSteps={activePlanSteps}
                planStructure={activePlanStructure}
                compact={true}
              />

              {!hasContent && (
                <div className="text-center py-8 text-xs text-fg-muted">
                  Invia un prompt per visualizzare i log dei tool e il piano di esecuzione.
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        /* Collapsed Vertical Icons */
        <div className="flex-1 py-4 flex flex-col items-center gap-4">
          <div
            onClick={onToggle}
            className="p-2 text-fg-muted hover:text-fg transition cursor-pointer"
            title="Apri pannello diagnostica"
          >
            <Wrench size={16} />
          </div>
          {activeWebPrefetch && (
            <div className="p-2 text-cyan-400" title="Web Retrieval (Prefetch) attivo">
              <Globe size={16} />
            </div>
          )}
          {activeTool && (
            <div
              className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"
              title="Attività tool rilevata"
            />
          )}
        </div>
      )}
    </div>
  );
};
