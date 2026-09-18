import React, { useState } from 'react';
import {
  X,
  Clock,
  Zap,
  CheckCircle,
  AlertCircle,
  PauseCircle,
  PlayCircle,
  FileText,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Terminal,
  Shield,
  Layers,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AutomationRunDetails, StepRun } from '../../api';

interface RunInspectorModalProps {
  run: AutomationRunDetails | null;
  isOpen: boolean;
  onClose: () => void;
  onRefresh?: () => void;
}

export const RunInspectorModal: React.FC<RunInspectorModalProps> = ({
  run,
  isOpen,
  onClose,
}) => {
  const [activeTab, setActiveTab] = useState<'timeline' | 'artifacts' | 'raw'>('timeline');
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});
  const [copiedArtifactId, setCopiedArtifactId] = useState<string | null>(null);

  if (!isOpen || !run) return null;

  const toggleStep = (stepRunId: string) => {
    setExpandedSteps((prev) => ({ ...prev, [stepRunId]: !prev[stepRunId] }));
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedArtifactId(id);
    setTimeout(() => setCopiedArtifactId(null), 2000);
  };

  const getStatusBadge = (status: string, isDryRun: boolean) => {
    if (isDryRun) {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30 flex items-center gap-1">
          <Shield size={12} /> Dry-Run
        </span>
      );
    }
    switch (status.toLowerCase()) {
      case 'completed':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
            <CheckCircle size={12} /> Completed
          </span>
        );
      case 'running':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-500/20 text-blue-300 border border-blue-500/30 flex items-center gap-1 animate-pulse">
            <PlayCircle size={12} /> Running
          </span>
        );
      case 'waiting_approval':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1">
            <PauseCircle size={12} /> Waiting Approval
          </span>
        );
      case 'failed':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-500/20 text-rose-300 border border-rose-500/30 flex items-center gap-1">
            <AlertCircle size={12} /> Failed
          </span>
        );
      default:
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-zinc-500/20 text-zinc-300 border border-zinc-500/30">
            {status}
          </span>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-panel border border-border rounded-2xl shadow-2xl flex flex-col overflow-hidden text-fg">
        {/* Header */}
        <div className="p-5 border-b border-border flex items-center justify-between bg-panel-header/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-accent/20 border border-accent/40 flex items-center justify-center text-accent">
              <Layers size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-fg font-mono">
                  Run: {run.run_id}
                </h2>
                {getStatusBadge(run.status, run.is_dry_run)}
              </div>
              <p className="text-xs text-fg-muted mt-0.5">
                Automazione: <span className="font-semibold text-fg">{run.automation_id}</span> • Trigger:{' '}
                <span className="capitalize">{run.trigger_type}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition"
          >
            <X size={20} />
          </button>
        </div>

        {/* Quick Stats Bar */}
        <div className="grid grid-cols-4 gap-2 p-4 bg-bg/40 border-b border-border text-center text-xs">
          <div className="p-2 rounded-lg bg-panel border border-border/50">
            <span className="text-fg-muted block mb-1">Stato</span>
            <span className="font-semibold text-fg uppercase">{run.status}</span>
          </div>
          <div className="p-2 rounded-lg bg-panel border border-border/50">
            <span className="text-fg-muted flex items-center justify-center gap-1 mb-1">
              <Clock size={12} /> Durata
            </span>
            <span className="font-semibold text-fg">
              {run.total_duration_ms > 0 ? `${run.total_duration_ms} ms` : '< 1s'}
            </span>
          </div>
          <div className="p-2 rounded-lg bg-panel border border-border/50">
            <span className="text-fg-muted flex items-center justify-center gap-1 mb-1">
              <Zap size={12} /> Token Usati
            </span>
            <span className="font-semibold text-fg">
              {run.total_tokens.toLocaleString()}
            </span>
          </div>
          <div className="p-2 rounded-lg bg-panel border border-border/50">
            <span className="text-fg-muted flex items-center justify-center gap-1 mb-1">
              <FileText size={12} /> Artefatti
            </span>
            <span className="font-semibold text-accent">
              {run.artifacts?.length || 0}
            </span>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="flex border-b border-border px-5 bg-panel-header/30">
          <button
            onClick={() => setActiveTab('timeline')}
            className={`py-2.5 px-4 text-xs font-medium border-b-2 transition ${
              activeTab === 'timeline'
                ? 'border-accent text-accent'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            Step Timeline ({run.step_runs?.length || 0})
          </button>
          <button
            onClick={() => setActiveTab('artifacts')}
            className={`py-2.5 px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 ${
              activeTab === 'artifacts'
                ? 'border-accent text-accent'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            Report & Artefatti
            {run.artifacts?.length ? (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-accent/20 text-accent">
                {run.artifacts.length}
              </span>
            ) : null}
          </button>
          <button
            onClick={() => setActiveTab('raw')}
            className={`py-2.5 px-4 text-xs font-medium border-b-2 transition ${
              activeTab === 'raw'
                ? 'border-accent text-accent'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            JSON Raw
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* TAB 1: Step Timeline */}
          {activeTab === 'timeline' && (
            <div className="space-y-3">
              {(!run.step_runs || run.step_runs.length === 0) ? (
                <div className="text-center py-10 text-fg-muted text-xs">
                  Nessun record di step disponibile per questa esecuzione.
                </div>
              ) : (
                run.step_runs.map((sr: StepRun, idx: number) => {
                  const isExpanded = expandedSteps[sr.step_run_id];
                  return (
                    <div
                      key={sr.step_run_id || idx}
                      className="border border-border rounded-xl bg-bg/50 overflow-hidden transition"
                    >
                      <div
                        onClick={() => toggleStep(sr.step_run_id)}
                        className="p-3.5 flex items-center justify-between cursor-pointer hover:bg-panel/60 select-none"
                      >
                        <div className="flex items-center gap-3">
                          <span className="w-6 h-6 rounded-full bg-accent/15 text-accent text-xs flex items-center justify-center font-bold">
                            {idx + 1}
                          </span>
                          <div>
                            <h4 className="text-xs font-semibold text-fg">
                              Step: {sr.step_id}
                            </h4>
                            <span className="text-[11px] text-fg-muted flex items-center gap-2 mt-0.5">
                              <span>Tentativo {sr.attempt}</span>
                              {sr.tokens_consumed > 0 && (
                                <span>• {sr.tokens_consumed} tokens</span>
                              )}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          {getStatusBadge(sr.status, false)}
                          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        </div>
                      </div>

                      {/* Expanded Step Details */}
                      {isExpanded && (
                        <div className="p-4 border-t border-border bg-panel/30 space-y-3 text-xs">
                          {sr.error_message && (
                            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800 text-rose-300">
                              <span className="font-semibold block mb-1">Errore:</span>
                              {sr.error_message}
                            </div>
                          )}

                          {sr.tool_calls && sr.tool_calls.length > 0 && (
                            <div>
                              <span className="text-fg-muted font-medium flex items-center gap-1 mb-1.5">
                                <Terminal size={12} /> Chiamate Tool ({sr.tool_calls.length})
                              </span>
                              <div className="space-y-1.5">
                                {sr.tool_calls.map((tc, tcIdx) => (
                                  <div
                                    key={tcIdx}
                                    className="p-2 rounded bg-black/40 border border-border/60 font-mono text-[11px]"
                                  >
                                    <div className="text-accent font-semibold">
                                      {tc.tool_name}
                                    </div>
                                    {tc.args && (
                                      <pre className="text-fg-muted overflow-x-auto mt-1">
                                        args: {JSON.stringify(tc.args, null, 2)}
                                      </pre>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {sr.output_payload && (
                            <div>
                              <span className="text-fg-muted font-medium block mb-1">Output Step:</span>
                              <pre className="p-2.5 rounded-lg bg-black/50 border border-border font-mono text-[11px] overflow-x-auto text-emerald-300 max-h-60">
                                {typeof sr.output_payload === 'string'
                                  ? sr.output_payload
                                  : JSON.stringify(sr.output_payload, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}

          {/* TAB 2: Artefatti Generati */}
          {activeTab === 'artifacts' && (
            <div className="space-y-4">
              {(!run.artifacts || run.artifacts.length === 0) ? (
                <div className="text-center py-12 text-fg-muted text-xs">
                  Nessun artefatto generato durante questa run.
                </div>
              ) : (
                run.artifacts.map((art) => (
                  <div
                    key={art.artifact_id}
                    className="border border-border rounded-xl bg-bg/40 p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between pb-2 border-b border-border/60">
                      <div className="flex items-center gap-2">
                        <FileText size={16} className="text-accent" />
                        <h3 className="text-xs font-semibold text-fg">{art.title}</h3>
                        <span className="text-[10px] px-2 py-0.5 rounded bg-panel border border-border text-fg-muted uppercase">
                          {art.type}
                        </span>
                      </div>
                      <button
                        onClick={() => copyToClipboard(art.content, art.artifact_id)}
                        className="px-2 py-1 text-xs text-fg-muted hover:text-fg hover:bg-panel rounded flex items-center gap-1 transition"
                        title="Copia Markdown"
                      >
                        {copiedArtifactId === art.artifact_id ? (
                          <>
                            <Check size={12} className="text-emerald-400" /> Copiato!
                          </>
                        ) : (
                          <>
                            <Copy size={12} /> Copia
                          </>
                        )}
                      </button>
                    </div>

                    <div className="prose prose-invert prose-xs max-w-none bg-panel/40 p-4 rounded-lg border border-border/50 max-h-96 overflow-y-auto">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {art.content || '(Nessun contenuto disponibile)'}
                      </ReactMarkdown>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* TAB 3: Raw JSON */}
          {activeTab === 'raw' && (
            <div className="relative">
              <button
                onClick={() => copyToClipboard(JSON.stringify(run, null, 2), 'raw')}
                className="absolute top-2 right-2 px-2.5 py-1 text-xs bg-panel hover:bg-panel-header text-fg-muted hover:text-fg rounded-md border border-border transition flex items-center gap-1 z-10"
              >
                {copiedArtifactId === 'raw' ? (
                  <>
                    <Check size={12} className="text-emerald-400" /> Copiato!
                  </>
                ) : (
                  <>
                    <Copy size={12} /> Copia JSON
                  </>
                )}
              </button>
              <pre className="p-4 rounded-xl bg-black/60 border border-border font-mono text-xs text-fg-muted overflow-x-auto max-h-[60vh]">
                {JSON.stringify(run, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border flex items-center justify-end bg-panel-header/30">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-panel hover:bg-panel-header text-fg text-xs font-medium rounded-xl border border-border transition"
          >
            Chiudi
          </button>
        </div>
      </div>
    </div>
  );
};
