import React, { useState, useEffect, useCallback } from 'react';
import {
  Layers,
  Play,
  Shield,
  CheckCircle,
  AlertCircle,
  Trash2,
  RefreshCw,
  Plus,
  Inbox,
  Workflow,
  Sparkles,
  Zap,
  Calendar,
  Eye,
  Check,
  X,
  Mail,
  Key,
  Sliders,
  FileText,
  Pause,
  Square,
  ChevronDown,
  ChevronUp,
  Lock,
  Unlock,
  Star,
  Edit2,
  Globe,
  Clock,
  Menu,
} from 'lucide-react';
import {
  fetchAutomations,
  fetchAutomationRuns,
  fetchAutomationApprovals,
  fetchAutomationTemplates,
  fetchScheduledJobs,
  triggerAutomationRun,
  createOrUpdateAutomation,
  deleteAutomation,
  resolveAutomationApproval,
  deleteAutomationApproval,
  clearExpiredAutomationApprovals,
  getAutomationRunDetails,
  getAutomation,
  deleteAutomationRun,
  bulkDeleteAutomationRuns,
  toggleAutomationRunFavorite,
  toggleAutomationRunPreserve,
  pauseAutomationRun,
  resumeAutomationRun,
  toggleAutomationEnabled,
  type AutomationSummary,
  type AutomationRunSummary,
  type AutomationApprovalItem,
  type AutomationRunDetails,
  type ScheduledJobInfo,
} from '../../api';
import { RunInspectorModal } from './RunInspectorModal';
import { IntegrationsTab } from './IntegrationsTab';
import { ParametersModal } from './ParametersModal';
import { ArtifactsView } from './ArtifactsView';
import { EditAutomationModal } from './EditAutomationModal';
import { TriggerEditorModal } from './TriggerEditorModal';

interface AutomationsViewProps {
  onOpenMobileSidebar?: () => void;
}

export const AutomationsView: React.FC<AutomationsViewProps> = ({ onOpenMobileSidebar }) => {
  const [activeTab, setActiveTab] = useState<'automations' | 'artifacts' | 'runs' | 'approvals' | 'templates' | 'integrations'>('automations');
  const [automations, setAutomations] = useState<AutomationSummary[]>([]);
  const [runs, setRuns] = useState<AutomationRunSummary[]>([]);
  const [approvals, setApprovals] = useState<AutomationApprovalItem[]>([]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [scheduledJobs, setScheduledJobs] = useState<ScheduledJobInfo[]>([]);

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Inspector Modal State
  const [selectedRun, setSelectedRun] = useState<AutomationRunDetails | null>(null);
  const [isInspectorOpen, setIsInspectorOpen] = useState<boolean>(false);

  // Artifacts Navigation State
  const [selectedArtifactIdForView, setSelectedArtifactIdForView] = useState<string | null>(null);

  // Expandable Automation Cards State & Cache
  const [expandedCardIds, setExpandedCardIds] = useState<Set<string>>(new Set());
  const [autoDetailsCache, setAutoDetailsCache] = useState<Record<string, any>>({});

  // Parameters Modal State
  const [isParamModalOpen, setIsParamModalOpen] = useState<boolean>(false);
  const [paramModalMode, setParamModalMode] = useState<'edit' | 'run'>('edit');
  const [selectedAutoForParams, setSelectedAutoForParams] = useState<AutomationSummary | null>(null);

  // Edit Automation Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [selectedAutoForEdit, setSelectedAutoForEdit] = useState<any | null>(null);

  // Trigger Editor Modal State
  const [editingTriggersAuto, setEditingTriggersAuto] = useState<AutomationSummary | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [copiedWebhookId, setCopiedWebhookId] = useState<string | null>(null);

  const handleToggleEnabled = async (auto: AutomationSummary) => {
    setTogglingId(auto.id);
    try {
      const res = await toggleAutomationEnabled(auto.id, !auto.enabled);
      setAutomations((prev) =>
        prev.map((a) => (a.id === auto.id ? { ...a, enabled: res.enabled } : a))
      );
      showFeedback('success', `Automazione '${auto.name}' ${res.enabled ? 'attivata' : 'disattivata'}.`);
    } catch (err: any) {
      showFeedback('error', err?.response?.data?.detail || "Errore durante l'aggiornamento dello stato.");
    } finally {
      setTogglingId(null);
    }
  };

  const handleCopyWebhookUrl = (auto: AutomationSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    const token = auto.triggers?.find((t) => t.type === 'webhook')?.webhook_token;
    if (!token) {
      setEditingTriggersAuto(auto);
      return;
    }
    const url = `${window.location.origin}/v1/automations/${auto.id}/webhook/${token}`;
    navigator.clipboard.writeText(url);
    setCopiedWebhookId(auto.id);
    showFeedback('success', 'URL Webhook copiato negli appunti!');
    setTimeout(() => setCopiedWebhookId(null), 2000);
  };

  const handleOpenEdit = async (auto: AutomationSummary) => {
    try {
      const fullDef = autoDetailsCache[auto.id] || (await getAutomation(auto.id));
      setSelectedAutoForEdit(fullDef);
      setIsEditModalOpen(true);
    } catch (err: any) {
      showFeedback('error', `Impossibile caricare l'automazione: ${err.message}`);
    }
  };

  // Filter state
  const [runStatusFilter, setRunStatusFilter] = useState<string>('all');

  const handleOpenParams = (auto: AutomationSummary, mode: 'edit' | 'run') => {
    setSelectedAutoForParams(auto);
    setParamModalMode(mode);
    setIsParamModalOpen(true);
  };

  const showFeedback = (type: 'success' | 'error', text: string) => {
    setActionMessage({ type, text });
    setTimeout(() => setActionMessage(null), 4000);
  };

  const toggleExpandCard = async (autoId: string) => {
    setExpandedCardIds((prev) => {
      const next = new Set(prev);
      if (next.has(autoId)) {
        next.delete(autoId);
      } else {
        next.add(autoId);
        if (!autoDetailsCache[autoId]) {
          getAutomation(autoId)
            .then((full) => {
              setAutoDetailsCache((c) => ({ ...c, [autoId]: full }));
            })
            .catch(console.error);
        }
      }
      return next;
    });
  };

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [autos, rList, apprs, tpls, sched] = await Promise.all([
        fetchAutomations(),
        fetchAutomationRuns(),
        fetchAutomationApprovals(),
        fetchAutomationTemplates(),
        fetchScheduledJobs(),
      ]);
      setAutomations(autos);
      setRuns(rList);
      setApprovals(apprs);
      setTemplates(tpls);
      setScheduledJobs(sched.jobs || []);
    } catch (err: any) {
      console.error('Errore caricamento dati automazioni:', err);
      showFeedback('error', 'Impossibile caricare i dati delle automazioni.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000); // Polling ogni 10s
    return () => clearInterval(interval);
  }, [loadData]);

  // Handler azioni
  const handleTriggerRun = async (autoId: string, dryRun: boolean) => {
    try {
      const result = await triggerAutomationRun(autoId, dryRun, false);
      showFeedback(
        'success',
        `${dryRun ? 'Dry-Run (anteprima sicura)' : 'Esecuzione'} avviata per ${autoId} (ID: ${result.run_id})`
      );
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore avvio run: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleDeleteAutomation = async (autoId: string) => {
    if (!confirm(`Sei sicuro di voler eliminare l'automazione "${autoId}"?`)) return;
    try {
      await deleteAutomation(autoId);
      showFeedback('success', `Automazione "${autoId}" eliminata.`);
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore eliminazione: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleResolveApproval = async (runId: string, approvalId: string, action: 'approve' | 'deny') => {
    try {
      await resolveAutomationApproval(runId, approvalId, action);
      showFeedback(
        'success',
        `Richiesta ${action === 'approve' ? 'approvata ed eseguita' : 'negata'} con successo.`
      );
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore risoluzione: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleDeleteApproval = async (approvalId: string) => {
    if (!confirm('Sei sicuro di voler eliminare questa richiesta di approvazione?')) return;
    try {
      await deleteAutomationApproval(approvalId);
      showFeedback('success', 'Richiesta di approvazione eliminata.');
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore eliminazione: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleClearExpiredApprovals = async () => {
    try {
      const res = await clearExpiredAutomationApprovals();
      showFeedback('success', `Rimosse ${res.cleared_count} approvazioni scadute.`);
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore pulizia scadute: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleInstallTemplate = async (template: any) => {
    try {
      await createOrUpdateAutomation(template);
      showFeedback('success', `Template "${template.name}" installato e attivato con successo!`);
      setActiveTab('automations');
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore installazione template: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleInspectRun = async (runId: string) => {
    try {
      const details = await getAutomationRunDetails(runId);
      setSelectedRun(details);
      setIsInspectorOpen(true);
    } catch (err: any) {
      showFeedback('error', `Impossibile caricare dettaglio run: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleToggleRunFavorite = async (runId: string, currentVal: boolean) => {
    try {
      await toggleAutomationRunFavorite(runId, !currentVal);
      setRuns((prev) =>
        prev.map((r) => (r.run_id === runId ? { ...r, is_favorite: !currentVal } : r))
      );
      showFeedback('success', !currentVal ? 'Aggiunto ai preferiti.' : 'Rimosso dai preferiti.');
    } catch (err: any) {
      showFeedback('error', `Errore toggle preferito: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleToggleRunPreserve = async (runId: string, currentVal: boolean) => {
    try {
      await toggleAutomationRunPreserve(runId, !currentVal);
      setRuns((prev) =>
        prev.map((r) => (r.run_id === runId ? { ...r, is_preserved: !currentVal } : r))
      );
      showFeedback(
        'success',
        !currentVal ? 'Esecuzione preservata da auto-cleanup!' : 'Protezione rimossa.'
      );
    } catch (err: any) {
      showFeedback('error', `Errore toggle preserva: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleDeleteRun = async (runId: string, isPreserved?: boolean) => {
    if (isPreserved) {
      alert('Questa esecuzione è preservata (bloccata con lucchetto). Sbloccala prima di eliminarla.');
      return;
    }
    if (!confirm(`Sei sicuro di voler eliminare la run ${runId}?`)) return;
    try {
      await deleteAutomationRun(runId);
      setRuns((prev) => prev.filter((r) => r.run_id !== runId));
      showFeedback('success', `Run ${runId} eliminata.`);
    } catch (err: any) {
      showFeedback('error', `Errore eliminazione run: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleBulkDeleteRuns = async (failedOnly: boolean) => {
    const msg = failedOnly
      ? 'Sei sicuro di voler eliminare tutte le esecuzioni fallite (non preservate)?'
      : 'Sei sicuro di voler eliminare le esecuzioni non preservate?';
    if (!confirm(msg)) return;
    try {
      const res = await bulkDeleteAutomationRuns({ failed_only: failedOnly });
      showFeedback('success', `Eliminate ${res.deleted_count} esecuzioni.`);
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore eliminazione bulk: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handlePauseRun = async (runId: string) => {
    try {
      await pauseAutomationRun(runId);
      showFeedback('success', `Richiesta di pausa inviata per la run ${runId}.`);
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore pausa run: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const handleResumeRun = async (runId: string) => {
    try {
      await resumeAutomationRun(runId);
      showFeedback('success', `Run ${runId} ripresa con successo.`);
      loadData();
    } catch (err: any) {
      showFeedback('error', `Errore ripresa run: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const filteredRuns = runs.filter((r) => {
    if (runStatusFilter === 'all') return true;
    if (runStatusFilter === 'dry_run') return r.is_dry_run;
    return r.status.toLowerCase() === runStatusFilter.toLowerCase();
  });

  return (
    <div className="flex-1 flex flex-col h-full bg-bg text-fg overflow-hidden relative font-sans">
      {/* Top Header Bar */}
      <div className="p-3 sm:p-4 border-b border-border bg-panel-header/40 backdrop-blur-md flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          {onOpenMobileSidebar && (
            <button
              onClick={onOpenMobileSidebar}
              className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition shrink-0"
              title="Apri menu principale"
            >
              <Menu size={20} />
            </button>
          )}
          <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shadow-sm shrink-0">
            <Workflow size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="font-semibold text-sm text-fg leading-tight">Automations & Loops</h1>
            <p className="text-[11px] text-fg-muted mt-0.5 hidden sm:block">
              Workflow schedulati, task ricorrenti e loop agentici supervisionati
            </p>
          </div>
        </div>

        <button
          onClick={loadData}
          disabled={isLoading}
          className="p-2 text-fg-muted hover:text-fg hover:bg-panel rounded-xl border border-border transition cursor-pointer shrink-0"
          title="Aggiorna dati"
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Floating action message toast */}
      {actionMessage && (
        <div
          className={`absolute top-14 right-4 z-50 px-3 py-1.5 rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-lg animate-in fade-in duration-200 max-w-[90vw] sm:max-w-sm ${
            actionMessage.type === 'success'
              ? 'bg-emerald-950/90 text-emerald-300 border border-emerald-800'
              : 'bg-rose-950/90 text-rose-300 border border-rose-800'
          }`}
        >
          {actionMessage.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
          <span className="truncate">{actionMessage.text}</span>
        </div>
      )}

      {/* Metric Quick Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3 p-3 sm:p-4 border-b border-border bg-bg/30 text-xs shrink-0">
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block truncate">Automazioni Attive</span>
            <span className="text-lg font-bold text-fg mt-0.5 block">{automations.length}</span>
          </div>
          <Layers className="text-accent/60" size={22} />
        </div>
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block truncate">Job Schedulati</span>
            <span className="text-lg font-bold text-emerald-400 mt-0.5 block">{scheduledJobs.length}</span>
          </div>
          <Calendar className="text-emerald-400/60" size={22} />
        </div>
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block truncate">Esecuzioni Totali</span>
            <span className="text-lg font-bold text-fg mt-0.5 block">{runs.length}</span>
          </div>
          <Zap className="text-amber-400/60" size={22} />
        </div>
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block truncate">Approvazioni</span>
            <span className={`text-lg font-bold mt-0.5 block ${approvals.length > 0 ? 'text-rose-400 animate-pulse' : 'text-fg-muted'}`}>
              {approvals.length}
            </span>
          </div>
          <Inbox className={approvals.length > 0 ? 'text-rose-400' : 'text-fg-muted'} size={22} />
        </div>
      </div>

      {/* View Tabs */}
      <div className="flex border-b border-border px-2 sm:px-4 bg-panel-header/20 shrink-0 overflow-x-auto">
        <button
          onClick={() => setActiveTab('automations')}
          className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
            activeTab === 'automations' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Layers size={15} /> Automazioni ({automations.length})
        </button>
        <button
          onClick={() => {
            setSelectedArtifactIdForView(null);
            setActiveTab('artifacts');
          }}
          className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
            activeTab === 'artifacts' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <FileText size={15} /> Artefatti & Report
        </button>
        <button
          onClick={() => setActiveTab('runs')}
          className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
            activeTab === 'runs' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Zap size={15} /> Storico Run ({runs.length})
        </button>
        <button
          onClick={() => setActiveTab('approvals')}
          className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
            activeTab === 'approvals' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Inbox size={15} /> Approvazioni Inbox
          {approvals.length > 0 && (
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-rose-500 text-white font-bold">
              {approvals.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setActiveTab('templates')}
          className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
            activeTab === 'templates' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Sparkles size={15} /> Template Gallery ({templates.length})
        </button>
        <button
          onClick={() => setActiveTab('integrations')}
          className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
            activeTab === 'integrations' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Key size={15} /> Integrazioni & Servizi
        </button>
      </div>

      {/* Main Tab Content — Not used for artifacts tab (needs full-height split pane) */}
      {activeTab !== 'artifacts' && <div className="flex-1 overflow-y-auto p-3 sm:p-5">
        {/* TAB 1: AUTOMAZIONI */}
        {activeTab === 'automations' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between pb-2">
              <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">
                Definizioni di Workflow Attive
              </h2>
              <button
                onClick={() => setActiveTab('templates')}
                className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm transition cursor-pointer"
              >
                <Plus size={14} /> Da Template
              </button>
            </div>

            {automations.length === 0 ? (
              <div className="text-center py-16 border border-dashed border-border rounded-2xl p-6 bg-panel/20">
                <Workflow className="mx-auto text-fg-muted mb-3" size={36} />
                <h3 className="text-sm font-semibold text-fg">Nessuna automazione attiva</h3>
                <p className="text-xs text-fg-muted mt-1 max-w-sm mx-auto">
                  Configura la tua prima automazione homelab partendo dalla galleria template (es. Daily Email Briefing).
                </p>
                <button
                  onClick={() => setActiveTab('templates')}
                  className="mt-4 px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium transition"
                >
                  Esplora Template Gallery
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {automations.map((auto) => {
                  const activeRun = runs.find(
                    (r) =>
                      r.automation_id === auto.id &&
                      ['running', 'waiting_approval', 'paused'].includes(r.status.toLowerCase())
                  );
                  const isRunning = activeRun?.status.toLowerCase() === 'running';
                  const isPaused = activeRun?.status.toLowerCase() === 'paused';
                  const isWaitingApproval = activeRun?.status.toLowerCase() === 'waiting_approval';
                  const isExpanded = expandedCardIds.has(auto.id);
                  const details = autoDetailsCache[auto.id];

                  return (
                    <div
                      key={auto.id}
                      className={`p-5 rounded-2xl bg-panel border transition flex flex-col justify-between space-y-4 ${
                        isRunning
                          ? 'border-accent shadow-lg shadow-accent/20 ring-1 ring-accent animate-in fade-in'
                          : isPaused
                          ? 'border-amber-500/50 shadow-md shadow-amber-500/10'
                          : 'border-border/80 hover:border-accent/40 shadow-sm'
                      }`}
                    >
                      <div>
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <h3 className="text-sm font-bold text-fg flex items-center gap-2">
                              {auto.name}
                              <span className="text-[10px] px-2 py-0.2 rounded-full bg-accent/15 text-accent border border-accent/30 font-mono">
                                v{auto.version}
                              </span>
                            </h3>
                            <span className="text-[11px] font-mono text-fg-muted mt-0.5 block">{auto.id}</span>
                          </div>

                          <div className="flex items-center gap-2">
                            {isRunning ? (
                              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-accent/20 text-accent border border-accent/40 flex items-center gap-1.5 animate-pulse">
                                <span className="w-1.5 h-1.5 rounded-full bg-accent animate-ping" /> In Esecuzione
                              </span>
                            ) : isPaused ? (
                              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                In Pausa
                              </span>
                            ) : isWaitingApproval ? (
                              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30 animate-pulse">
                                Attesa Approvazione
                              </span>
                            ) : null}

                            {/* Slider Toggle Attivazione/Disattivazione */}
                            <div className="flex items-center gap-2 bg-panel-header/60 px-2.5 py-1 rounded-xl border border-border/60">
                              <span className={`text-[11px] font-semibold transition ${auto.enabled ? 'text-emerald-400' : 'text-fg-muted'}`}>
                                {auto.enabled ? 'Attiva' : 'Inattiva'}
                              </span>
                              <label
                                className={`relative inline-flex items-center cursor-pointer ${togglingId === auto.id ? 'opacity-50 pointer-events-none' : ''}`}
                                title={auto.enabled ? "Disattiva automazione e schedulazioni" : "Attiva automazione e schedulazioni"}
                              >
                                <input
                                  type="checkbox"
                                  checked={auto.enabled}
                                  onChange={() => handleToggleEnabled(auto)}
                                  className="sr-only peer"
                                />
                                <div className="w-8 h-4 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-emerald-500"></div>
                              </label>
                            </div>
                          </div>
                        </div>

                        <p className="text-xs text-fg-muted mt-3 line-clamp-2">
                          {auto.description || 'Nessuna descrizione specificata.'}
                        </p>

                        <div className="flex items-center justify-between mt-4 text-xs text-fg-muted flex-wrap gap-2">
                          <div className="flex items-center gap-2">
                            <span className="flex items-center gap-1.5">
                              <Layers size={13} className="text-accent" /> {auto.steps_count} step
                            </span>

                            {/* Trigger Pill / Quick Trigger Config */}
                            <button
                              onClick={() => setEditingTriggersAuto(auto)}
                              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 transition text-[11px] font-medium cursor-pointer"
                              title="Configura Schedulazione Cron e Webhook HTTP"
                            >
                              <Clock size={12} className="text-emerald-400" />
                              <span>
                                {auto.triggers?.find((t) => t.type === 'cron')
                                  ? auto.triggers.find((t) => t.type === 'cron')?.cron_expression
                                  : `${auto.triggers_count} trigger`}
                              </span>
                            </button>

                            {/* Webhook Pill / Quick Copy */}
                            {auto.triggers?.some((t) => t.type === 'webhook') && (
                              <button
                                onClick={(e) => handleCopyWebhookUrl(auto, e)}
                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 transition text-[11px] font-medium cursor-pointer"
                                title="Fai clic per copiare l'URL Webhook negli appunti"
                              >
                                <Globe size={12} className="text-sky-400" />
                                <span>{copiedWebhookId === auto.id ? 'URL Copiato!' : 'Webhook'}</span>
                              </button>
                            )}
                          </div>

                          {/* 1-Click Ultimo Report Button */}
                          {auto.last_artifact_id && (
                            <button
                              onClick={() => {
                                setSelectedArtifactIdForView(auto.last_artifact_id || null);
                                setActiveTab('artifacts');
                              }}
                              className="px-2.5 py-1 rounded-lg bg-accent/15 hover:bg-accent/25 text-accent border border-accent/30 text-[11px] font-medium flex items-center gap-1.5 transition cursor-pointer"
                              title={`Apri report: ${auto.last_artifact_name || 'Ultimo Report'}`}
                            >
                              <FileText size={12} />
                              <span className="truncate max-w-[140px]">
                                {auto.last_artifact_name || 'Ultimo Report'}
                              </span>
                            </button>
                          )}
                        </div>

                        {/* Parameters preview */}
                        {auto.parameters && Object.keys(auto.parameters).length > 0 && (
                          <div className="mt-3 pt-2.5 border-t border-border/40">
                            <div className="text-[10px] text-fg-muted uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
                              <Sliders size={11} className="text-accent" /> Parametri di default
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {Object.entries(auto.parameters).slice(0, 3).map(([k, v]) => (
                                <span
                                  key={k}
                                  className="text-[10px] px-2 py-0.5 rounded-md bg-panel-header/70 border border-border text-fg-muted font-mono"
                                  title={`${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`}
                                >
                                  {k}: <span className="text-fg font-medium">{typeof v === 'object' ? '{...}' : String(v)}</span>
                                </span>
                              ))}
                              {Object.keys(auto.parameters).length > 3 && (
                                <span className="text-[10px] text-fg-muted self-center">
                                  +{Object.keys(auto.parameters).length - 3} altri
                                </span>
                              )}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Expandable Drawer Toggle & Content */}
                      <div className="space-y-2 pt-1">
                        <div className="pt-2 border-t border-border/40 flex items-center justify-between text-[11px] text-fg-muted">
                          <button
                            onClick={() => toggleExpandCard(auto.id)}
                            className="flex items-center gap-1 hover:text-fg transition cursor-pointer font-medium"
                          >
                            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            <span>{isExpanded ? 'Nascondi Pipeline & Statistiche' : 'Mostra Pipeline & Statistiche'}</span>
                          </button>
                          <span className="font-mono text-[10px]">
                            TTL: {auto.retention_days || 14} giorni
                          </span>
                        </div>

                        {isExpanded && (
                          <div className="p-3 rounded-xl bg-bg/80 border border-border/60 space-y-3 animate-in fade-in duration-150">
                            {/* Mini stats */}
                            <div className="grid grid-cols-3 gap-2 text-[11px]">
                              <div className="p-2 rounded-lg bg-panel border border-border/60">
                                <span className="text-fg-muted text-[10px] block">Ultima Run</span>
                                <span className={`font-semibold text-xs capitalize block truncate ${
                                  auto.last_run_status === 'completed'
                                    ? 'text-emerald-400'
                                    : auto.last_run_status === 'failed'
                                    ? 'text-rose-400'
                                    : 'text-fg'
                                }`}>
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
                                <span className="font-semibold text-fg">
                                  {runs.filter((r) => r.automation_id === auto.id).length}
                                </span>
                              </div>
                            </div>

                            {/* Step pipeline visualizer */}
                            <div className="space-y-1.5 pt-1">
                              <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-muted block">
                                Pipeline Step ({details?.workflow?.steps?.length || auto.steps_count})
                              </span>
                              {details?.workflow?.steps ? (
                                <div className="space-y-1.5">
                                  {details.workflow.steps.map((st: any, sIdx: number) => (
                                    <div
                                      key={st.step_id || sIdx}
                                      className="flex items-center gap-2 text-[11px] p-1.5 rounded-lg bg-panel border border-border/50"
                                    >
                                      <span className="w-5 h-5 rounded-md bg-accent/15 text-accent font-mono text-[10px] font-bold flex items-center justify-center shrink-0">
                                        {sIdx + 1}
                                      </span>
                                      <div className="flex-1 min-w-0">
                                        <span className="font-medium text-fg truncate block">{st.name}</span>
                                        <span className="text-[10px] text-fg-muted font-mono truncate block">
                                          {st.action_or_tool || st.type}
                                        </span>
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
                        )}
                      </div>

                      {/* Action buttons (Morphed when active) */}
                      <div className="pt-3 border-t border-border/60 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 flex-wrap">
                        {isRunning && activeRun ? (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <button
                              onClick={() => handlePauseRun(activeRun.run_id)}
                              className="px-3 py-1.5 bg-amber-600/90 hover:bg-amber-600 text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition cursor-pointer"
                              title="Metti in pausa l'esecuzione al termine del passo corrente"
                            >
                              <Pause size={12} /> Pausa
                            </button>
                            <button
                              onClick={() => handleInspectRun(activeRun.run_id)}
                              className="px-3 py-1.5 bg-panel-header hover:bg-panel border border-border text-fg rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
                              title="Ispeziona esecuzione in corso"
                            >
                              <Eye size={12} /> Ispeziona
                            </button>
                            <button
                              onClick={() => handleDeleteRun(activeRun.run_id)}
                              className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg hover:bg-panel transition cursor-pointer"
                              title="Arresta ed elimina run"
                            >
                              <Square size={13} />
                            </button>
                          </div>
                        ) : isPaused && activeRun ? (
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => handleResumeRun(activeRun.run_id)}
                              className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition cursor-pointer"
                              title="Riprendi l'esecuzione dal passo corrente"
                            >
                              <Play size={12} /> Riprendi
                            </button>
                            <button
                              onClick={() => handleInspectRun(activeRun.run_id)}
                              className="px-3 py-1.5 bg-panel-header hover:bg-panel border border-border text-fg rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
                            >
                              <Eye size={12} /> Ispeziona
                            </button>
                            <button
                              onClick={() => handleDeleteRun(activeRun.run_id)}
                              className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg hover:bg-panel transition cursor-pointer"
                              title="Cancella run"
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <button
                              onClick={() => handleTriggerRun(auto.id, false)}
                              className="px-3 py-1.5 bg-accent/90 hover:bg-accent text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition cursor-pointer"
                              title="Lancia esecuzione completa con parametri di default"
                            >
                              <Play size={12} /> Esegui
                            </button>
                            <button
                              onClick={() => handleTriggerRun(auto.id, true)}
                              className="px-3 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 border border-purple-500/30 rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
                              title="Anteprima sicura senza modifiche (Dry-Run)"
                            >
                              <Shield size={12} /> Dry-Run
                            </button>
                            <button
                              onClick={() => handleOpenParams(auto, 'run')}
                              className="px-2.5 py-1.5 bg-panel-header/60 hover:bg-panel-header text-fg-muted hover:text-fg border border-border rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
                              title="Esegui con parametri personalizzati per questa istanza"
                            >
                              <Play size={11} className="text-emerald-400" /> + Parametri
                            </button>
                          </div>
                        )}

                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setEditingTriggersAuto(auto)}
                            className="p-1.5 text-fg-muted hover:text-emerald-400 hover:bg-panel rounded-lg border border-transparent hover:border-border transition cursor-pointer"
                            title="Configura Schedulazione (Cron) e Trigger Webhook HTTP"
                          >
                            <Clock size={15} />
                          </button>
                          <button
                            onClick={() => handleOpenEdit(auto)}
                            className="p-1.5 text-fg-muted hover:text-accent hover:bg-panel rounded-lg border border-transparent hover:border-border transition cursor-pointer"
                            title="Modifica workflow, trigger, prompt e parametri dell'automazione"
                          >
                            <Edit2 size={15} />
                          </button>
                          <button
                            onClick={() => handleOpenParams(auto, 'edit')}
                            className="p-1.5 text-fg-muted hover:text-accent hover:bg-panel rounded-lg border border-transparent hover:border-border transition cursor-pointer"
                            title="Configura o modifica parametri di default"
                          >
                            <Sliders size={15} />
                          </button>
                          <button
                            onClick={() => handleDeleteAutomation(auto.id)}
                            className="p-1.5 text-fg-muted hover:text-rose-400 hover:bg-panel rounded-lg transition cursor-pointer"
                            title="Elimina automazione"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* TAB: ARTIFACTS & REPORT — Rendered outside this wrapper, see below */}

        {/* TAB 2: STORICO RUN */}
        {activeTab === 'runs' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-fg-muted font-medium">Filtro stato:</span>
                {['all', 'completed', 'waiting_approval', 'failed', 'running', 'paused', 'dry_run'].map((st) => (
                  <button
                    key={st}
                    onClick={() => setRunStatusFilter(st)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium transition capitalize cursor-pointer ${
                      runStatusFilter === st
                        ? 'bg-accent text-white shadow-sm'
                        : 'bg-panel border border-border text-fg-muted hover:text-fg'
                    }`}
                  >
                    {st.replace('_', ' ')}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleBulkDeleteRuns(true)}
                  className="px-2.5 py-1 text-xs text-rose-300 hover:text-white bg-rose-950/30 hover:bg-rose-900/60 border border-rose-800/40 rounded-lg flex items-center gap-1.5 transition cursor-pointer"
                  title="Elimina tutte le esecuzioni fallite (eccetto quelle preservate con lucchetto)"
                >
                  <Trash2 size={13} />
                  <span>Elimina Tutte le Fallite</span>
                </button>
                <span className="text-xs text-fg-muted">{filteredRuns.length} esecuzioni</span>
              </div>
            </div>

            {filteredRuns.length === 0 ? (
              <div className="text-center py-16 text-xs text-fg-muted border border-dashed border-border rounded-xl">
                Nessuna esecuzione trovata con i filtri correnti.
              </div>
            ) : (
              <div className="border border-border rounded-xl overflow-hidden bg-panel/30 overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse min-w-[700px]">
                  <thead>
                    <tr className="border-b border-border bg-panel-header/40 text-fg-muted font-semibold">
                      <th className="p-3 w-8"></th>
                      <th className="p-3 w-8"></th>
                      <th className="p-3">Run ID</th>
                      <th className="p-3">Automazione</th>
                      <th className="p-3">Stato</th>
                      <th className="p-3">Trigger</th>
                      <th className="p-3">Report</th>
                      <th className="p-3">Durata</th>
                      <th className="p-3">Avviata</th>
                      <th className="p-3 text-right">Azioni</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {filteredRuns.map((r) => (
                      <tr
                        key={r.run_id}
                        onClick={() => handleInspectRun(r.run_id)}
                        className="hover:bg-panel/70 cursor-pointer transition select-none"
                      >
                        <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => handleToggleRunFavorite(r.run_id, Boolean(r.is_favorite))}
                            className="p-1 text-fg-muted hover:text-amber-400 transition cursor-pointer"
                            title={r.is_favorite ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'}
                          >
                            <Star
                              size={14}
                              className={
                                r.is_favorite ? 'text-amber-400 fill-amber-400' : 'text-fg-muted/40 hover:text-amber-400'
                              }
                            />
                          </button>
                        </td>
                        <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => handleToggleRunPreserve(r.run_id, Boolean(r.is_preserved))}
                            className="p-1 text-fg-muted hover:text-purple-400 transition cursor-pointer"
                            title={r.is_preserved ? 'Preservata da auto-cleanup (clicca per sbloccare)' : 'Blocca e preserva da auto-cleanup'}
                          >
                            {r.is_preserved ? (
                              <Lock size={14} className="text-purple-400" />
                            ) : (
                              <Unlock size={14} className="text-fg-muted/40 hover:text-purple-400" />
                            )}
                          </button>
                        </td>
                        <td className="p-3 font-mono font-medium text-accent">{r.run_id}</td>
                        <td className="p-3 font-semibold text-fg">{r.automation_id}</td>
                        <td className="p-3">
                          {r.is_dry_run ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
                              Dry-Run
                            </span>
                          ) : (
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-medium capitalize flex items-center gap-1 w-fit ${
                                r.status === 'completed'
                                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                  : r.status === 'failed'
                                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                  : r.status === 'waiting_approval'
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse'
                                  : r.status === 'running'
                                  ? 'bg-accent/20 text-accent border border-accent/40 animate-pulse'
                                  : r.status === 'paused'
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                  : 'bg-zinc-500/20 text-zinc-300'
                              }`}
                            >
                              {r.status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-accent animate-ping" />}
                              {r.status}
                            </span>
                          )}
                        </td>
                        <td className="p-3 capitalize text-fg-muted">{r.trigger_type}</td>
                        <td className="p-3">
                          {r.artifacts_count && r.artifacts_count > 0 ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setActiveTab('artifacts');
                              }}
                              className="px-2 py-0.5 rounded-md bg-accent/15 hover:bg-accent/25 text-accent text-[11px] font-medium flex items-center gap-1 transition"
                            >
                              <FileText size={11} /> {r.artifacts_count}
                            </button>
                          ) : (
                            <span className="text-fg-muted text-[11px]">-</span>
                          )}
                        </td>
                        <td className="p-3 text-fg-muted">{r.total_duration_ms > 0 ? `${r.total_duration_ms} ms` : '-'}</td>
                        <td className="p-3 text-fg-muted">{new Date(r.started_at).toLocaleTimeString()}</td>
                        <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1">
                            {r.status === 'running' && (
                              <button
                                onClick={() => handlePauseRun(r.run_id)}
                                className="p-1.5 text-fg-muted hover:text-amber-400 rounded-lg hover:bg-panel transition"
                                title="Metti in pausa"
                              >
                                <Pause size={14} />
                              </button>
                            )}
                            {r.status === 'paused' && (
                              <button
                                onClick={() => handleResumeRun(r.run_id)}
                                className="p-1.5 text-fg-muted hover:text-emerald-400 rounded-lg hover:bg-panel transition"
                                title="Riprendi"
                              >
                                <Play size={14} />
                              </button>
                            )}
                            <button
                              onClick={() => handleInspectRun(r.run_id)}
                              className="p-1.5 text-fg-muted hover:text-accent rounded-lg hover:bg-panel transition"
                              title="Ispeziona dettagli run"
                            >
                              <Eye size={15} />
                            </button>
                            <button
                              onClick={() => handleDeleteRun(r.run_id, r.is_preserved)}
                              className={`p-1.5 rounded-lg transition ${
                                r.is_preserved
                                  ? 'text-fg-muted/30 cursor-not-allowed'
                                  : 'text-fg-muted hover:text-rose-400 hover:bg-panel cursor-pointer'
                              }`}
                              title={r.is_preserved ? 'Esecuzione preservata (sblocca prima di eliminare)' : 'Elimina esecuzione'}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: APPROVALS INBOX */}
        {activeTab === 'approvals' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">
                Richieste di Approvazione in Sospeso
              </h2>
              <button
                onClick={handleClearExpiredApprovals}
                className="px-2.5 py-1 text-xs text-fg-muted hover:text-fg bg-panel border border-border hover:border-border-accent rounded-lg flex items-center gap-1.5 transition"
                title="Rimuovi le richieste di approvazione scadute"
              >
                <Trash2 size={13} />
                <span>Pulisci Scadute</span>
              </button>
            </div>

            {approvals.length === 0 ? (
              <div className="text-center py-16 border border-dashed border-border rounded-xl p-6 bg-panel/20">
                <CheckCircle className="mx-auto text-emerald-400 mb-2" size={32} />
                <h3 className="text-sm font-semibold text-fg">Nessuna approvazione pendente</h3>
                <p className="text-xs text-fg-muted mt-1">
                  Tutti i workflow e le sessioni stanno procedendo normalmente entro i limiti autorizzati.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {approvals.map((apr) => {
                  const isWorkflow = Boolean(apr.step_run_id);
                  return (
                    <div
                      key={apr.request_id}
                      className="p-4 rounded-xl bg-panel border border-amber-500/40 shadow-md space-y-3"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-2">
                          <span className="p-1.5 rounded-lg bg-amber-500/20 text-amber-400">
                            <Shield size={16} />
                          </span>
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-xs font-bold text-fg">
                                Azione Richiesta: {apr.tool_name}
                              </h4>
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                                  isWorkflow
                                    ? 'bg-accent/15 text-accent border-accent/30'
                                    : 'bg-sky-500/15 text-sky-400 border-sky-500/30'
                                }`}
                              >
                                {isWorkflow ? 'Workflow' : 'Chat Session'}
                              </span>
                            </div>
                            <span className="text-[11px] font-mono text-fg-muted">
                              {isWorkflow ? `Run: ${apr.run_id} • Req: ${apr.request_id}` : `Session: ${apr.run_id} • Req: ${apr.request_id}`}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleResolveApproval(apr.run_id, apr.request_id, 'approve')}
                            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition"
                          >
                            <Check size={14} /> Approva ed Esegui
                          </button>
                          <button
                            onClick={() => handleResolveApproval(apr.run_id, apr.request_id, 'deny')}
                            className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-medium flex items-center gap-1 transition"
                          >
                            <X size={14} /> Nega
                          </button>
                          <button
                            onClick={() => handleDeleteApproval(apr.request_id)}
                            className="p-1.5 text-fg-muted hover:text-rose-400 hover:bg-rose-950/30 rounded-lg transition"
                            title="Elimina richiesta"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>

                      <div className="p-3 rounded-lg bg-black/40 border border-border/60 text-xs space-y-1.5">
                        <div className="text-fg-muted">
                          <span className="font-semibold text-fg">Motivo Guardrail:</span> {apr.risk_reason || 'Conferma richiesta da policy.'}
                        </div>
                        {apr.command_preview && (
                          <div className="font-mono text-[11px] text-amber-300">
                            preview: {apr.command_preview}
                          </div>
                        )}
                        {apr.arguments && (
                          <pre className="text-[11px] text-fg-muted overflow-x-auto max-h-32 mt-1">
                            {JSON.stringify(apr.arguments, null, 2)}
                          </pre>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* TAB 4: TEMPLATE GALLERY */}
        {activeTab === 'templates' && (
          <div className="space-y-4">
            <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">
              Template Pronti all'Uso (Homelab Best Practices)
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {templates.map((tpl) => (
                <div
                  key={tpl.id}
                  className="p-5 rounded-2xl bg-panel border border-accent/40 shadow-md flex flex-col justify-between space-y-4 relative overflow-hidden"
                >
                  <div className="absolute top-0 right-0 bg-accent/20 px-3 py-1 text-[10px] font-bold text-accent rounded-bl-xl border-l border-b border-accent/30">
                    MVP READY
                  </div>

                  <div>
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-accent/20 text-accent flex items-center justify-center">
                        <Mail size={18} />
                      </div>
                      <div>
                        <h3 className="text-sm font-bold text-fg">{tpl.name}</h3>
                        <span className="text-[11px] font-mono text-fg-muted">{tpl.id}</span>
                      </div>
                    </div>

                    <p className="text-xs text-fg-muted mt-3">
                      {tpl.description}
                    </p>

                    {/* Step Breakdown */}
                    <div className="mt-4 p-3 rounded-xl bg-bg/50 border border-border/60 space-y-2 text-xs">
                      <span className="font-semibold text-fg block text-[11px]">Workflow Steps:</span>
                      <ol className="list-decimal list-inside space-y-1 text-fg-muted text-[11px]">
                        {tpl.workflow?.steps?.map((st: any) => (
                          <li key={st.step_id}>
                            <span className="font-medium text-fg">{st.name}</span>{' '}
                            <span className="text-[10px] font-mono">({st.type})</span>
                          </li>
                        ))}
                      </ol>
                    </div>

                    {/* Security Guarantees */}
                    <div className="mt-3 p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-800/40 text-[11px] text-emerald-300 flex items-center gap-2">
                      <Shield size={14} className="shrink-0 text-emerald-400" />
                      <span>Sicurezza: Nessun invio automatico. Genera solo bozze e report Markdown.</span>
                    </div>
                  </div>

                  <button
                    onClick={() => handleInstallTemplate(tpl)}
                    className="w-full py-2.5 px-4 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 shadow-md transition cursor-pointer active:scale-[0.99]"
                  >
                    <Plus size={16} /> Installa ed Attiva Automazione
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 5: INTEGRAZIONI & SERVIZI */}
        {activeTab === 'integrations' && (
          <IntegrationsTab onFeedback={showFeedback} />
        )}
      </div>}

      {/* TAB: ARTIFACTS & REPORT — Rendered outside the scrollable wrapper for full-height split pane */}
      {activeTab === 'artifacts' && (
        <ArtifactsView
          initialArtifactId={selectedArtifactIdForView}
          onFeedback={showFeedback}
        />
      )}

      {/* Run Inspector Modal */}
      <RunInspectorModal
        run={selectedRun}
        isOpen={isInspectorOpen}
        onClose={() => setIsInspectorOpen(false)}
        onRefresh={() => {
          if (selectedRun) handleInspectRun(selectedRun.run_id);
        }}
      />

      {/* Parameters Configuration & Run Modal */}
      <ParametersModal
        automation={selectedAutoForParams}
        isOpen={isParamModalOpen}
        mode={paramModalMode}
        onClose={() => {
          setIsParamModalOpen(false);
          setSelectedAutoForParams(null);
        }}
        onSuccess={() => {
          loadData();
        }}
        onFeedback={showFeedback}
      />

      {/* Edit Automation Modal */}
      {isEditModalOpen && selectedAutoForEdit && (
        <EditAutomationModal
          automation={selectedAutoForEdit}
          onClose={() => {
            setIsEditModalOpen(false);
            setSelectedAutoForEdit(null);
          }}
          onSuccess={() => {
            loadData();
          }}
          onFeedback={(type, msg) => {
            showFeedback(type === 'error' ? 'error' : 'success', msg);
          }}
        />
      )}

      {/* Trigger & Webhook Editor Modal */}
      {editingTriggersAuto && (
        <TriggerEditorModal
          automation={editingTriggersAuto}
          onClose={() => setEditingTriggersAuto(null)}
          onSaved={() => {
            loadData();
            showFeedback('success', `Trigger aggiornati per '${editingTriggersAuto.name}'.`);
          }}
        />
      )}
    </div>
  );
};
