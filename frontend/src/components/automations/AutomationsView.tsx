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
  type AutomationSummary,
  type AutomationRunSummary,
  type AutomationApprovalItem,
  type AutomationRunDetails,
  type ScheduledJobInfo,
} from '../../api';
import { RunInspectorModal } from './RunInspectorModal';
import { IntegrationsTab } from './IntegrationsTab';
import { ParametersModal } from './ParametersModal';

export const AutomationsView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'automations' | 'runs' | 'approvals' | 'templates' | 'integrations'>('automations');
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

  // Parameters Modal State
  const [isParamModalOpen, setIsParamModalOpen] = useState<boolean>(false);
  const [paramModalMode, setParamModalMode] = useState<'edit' | 'run'>('edit');
  const [selectedAutoForParams, setSelectedAutoForParams] = useState<AutomationSummary | null>(null);

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
    const interval = setInterval(loadData, 15000); // Polling ogni 15s
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

  const filteredRuns = runs.filter((r) => {
    if (runStatusFilter === 'all') return true;
    if (runStatusFilter === 'dry_run') return r.is_dry_run;
    return r.status.toLowerCase() === runStatusFilter.toLowerCase();
  });

  return (
    <div className="flex-1 flex flex-col h-full bg-bg text-fg overflow-hidden relative font-sans">
      {/* Top Header Bar */}
      <div className="p-4 border-b border-border bg-panel-header/40 backdrop-blur-md flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shadow-sm">
            <Workflow size={20} />
          </div>
          <div>
            <h1 className="font-semibold text-sm text-fg leading-tight">Automations & Loops</h1>
            <p className="text-[11px] text-fg-muted mt-0.5">
              Workflow schedulati, task ricorrenti e loop agentici supervisionati
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {actionMessage && (
            <div
              className={`px-3 py-1 rounded-lg text-xs font-medium flex items-center gap-1.5 animate-in fade-in duration-200 ${
                actionMessage.type === 'success'
                  ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800'
                  : 'bg-rose-950/80 text-rose-300 border border-rose-800'
              }`}
            >
              {actionMessage.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
              <span>{actionMessage.text}</span>
            </div>
          )}

          <button
            onClick={loadData}
            disabled={isLoading}
            className="p-2 text-fg-muted hover:text-fg hover:bg-panel rounded-xl border border-border transition cursor-pointer"
            title="Aggiorna dati"
          >
            <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Metric Quick Cards */}
      <div className="grid grid-cols-4 gap-3 p-4 border-b border-border bg-bg/30 text-xs shrink-0">
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block">Automazioni Attive</span>
            <span className="text-lg font-bold text-fg mt-0.5 block">{automations.length}</span>
          </div>
          <Layers className="text-accent/60" size={22} />
        </div>
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block">Job Schedulati (Cron)</span>
            <span className="text-lg font-bold text-emerald-400 mt-0.5 block">{scheduledJobs.length}</span>
          </div>
          <Calendar className="text-emerald-400/60" size={22} />
        </div>
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block">Esecuzioni Totali</span>
            <span className="text-lg font-bold text-fg mt-0.5 block">{runs.length}</span>
          </div>
          <Zap className="text-amber-400/60" size={22} />
        </div>
        <div className="p-3 rounded-xl bg-panel border border-border/60 flex items-center justify-between">
          <div>
            <span className="text-fg-muted block">Approvazioni Pendenti</span>
            <span className={`text-lg font-bold mt-0.5 block ${approvals.length > 0 ? 'text-rose-400 animate-pulse' : 'text-fg-muted'}`}>
              {approvals.length}
            </span>
          </div>
          <Inbox className={approvals.length > 0 ? 'text-rose-400' : 'text-fg-muted'} size={22} />
        </div>
      </div>

      {/* View Tabs */}
      <div className="flex border-b border-border px-4 bg-panel-header/20 shrink-0">
        <button
          onClick={() => setActiveTab('automations')}
          className={`py-3 px-4 text-xs font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'automations' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Layers size={15} /> Automazioni ({automations.length})
        </button>
        <button
          onClick={() => setActiveTab('runs')}
          className={`py-3 px-4 text-xs font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'runs' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Zap size={15} /> Storico Run ({runs.length})
        </button>
        <button
          onClick={() => setActiveTab('approvals')}
          className={`py-3 px-4 text-xs font-medium border-b-2 transition flex items-center gap-2 ${
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
          className={`py-3 px-4 text-xs font-medium border-b-2 transition flex items-center gap-2 cursor-pointer ${
            activeTab === 'templates' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Sparkles size={15} /> Template Gallery ({templates.length})
        </button>
        <button
          onClick={() => setActiveTab('integrations')}
          className={`py-3 px-4 text-xs font-medium border-b-2 transition flex items-center gap-2 cursor-pointer ${
            activeTab === 'integrations' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          <Key size={15} /> Integrazioni & Servizi
        </button>
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 overflow-y-auto p-5">
        {/* TAB 1: AUTOMAZIONI */}
        {activeTab === 'automations' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between pb-2">
              <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">
                Definizioni di Workflow Attive
              </h2>
              <button
                onClick={() => setActiveTab('templates')}
                className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm transition"
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
                {automations.map((auto) => (
                  <div
                    key={auto.id}
                    className="p-5 rounded-2xl bg-panel border border-border/80 shadow-sm hover:border-accent/40 transition flex flex-col justify-between space-y-4"
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
                        <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium ${auto.enabled ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' : 'bg-zinc-500/20 text-zinc-400'}`}>
                          {auto.enabled ? 'Abilitata' : 'Inattiva'}
                        </span>
                      </div>

                      <p className="text-xs text-fg-muted mt-3 line-clamp-2">
                        {auto.description || 'Nessuna descrizione specificata.'}
                      </p>

                      <div className="flex items-center gap-4 mt-4 text-xs text-fg-muted">
                        <span className="flex items-center gap-1.5">
                          <Layers size={13} className="text-accent" /> {auto.steps_count} step
                        </span>
                        <span className="flex items-center gap-1.5">
                          <Calendar size={13} className="text-emerald-400" /> {auto.triggers_count} trigger
                        </span>
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

                    {/* Action buttons */}
                    <div className="pt-3 border-t border-border/60 flex items-center justify-between gap-2 flex-wrap">
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

                      <div className="flex items-center gap-1">
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
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 2: STORICO RUN */}
        {activeTab === 'runs' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-fg-muted font-medium">Filtro stato:</span>
                {['all', 'completed', 'waiting_approval', 'failed', 'running', 'dry_run'].map((st) => (
                  <button
                    key={st}
                    onClick={() => setRunStatusFilter(st)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium transition capitalize ${
                      runStatusFilter === st
                        ? 'bg-accent text-white shadow-sm'
                        : 'bg-panel border border-border text-fg-muted hover:text-fg'
                    }`}
                  >
                    {st.replace('_', ' ')}
                  </button>
                ))}
              </div>
              <span className="text-xs text-fg-muted">{filteredRuns.length} esecuzioni</span>
            </div>

            {filteredRuns.length === 0 ? (
              <div className="text-center py-16 text-xs text-fg-muted border border-dashed border-border rounded-xl">
                Nessuna esecuzione trovata con i filtri correnti.
              </div>
            ) : (
              <div className="border border-border rounded-xl overflow-hidden bg-panel/30">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-border bg-panel-header/40 text-fg-muted font-semibold">
                      <th className="p-3">Run ID</th>
                      <th className="p-3">Automazione</th>
                      <th className="p-3">Stato</th>
                      <th className="p-3">Trigger</th>
                      <th className="p-3">Durata</th>
                      <th className="p-3">Token</th>
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
                        <td className="p-3 font-mono font-medium text-accent">{r.run_id}</td>
                        <td className="p-3 font-semibold text-fg">{r.automation_id}</td>
                        <td className="p-3">
                          {r.is_dry_run ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
                              Dry-Run
                            </span>
                          ) : (
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-medium capitalize ${
                                r.status === 'completed'
                                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                  : r.status === 'failed'
                                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                  : r.status === 'waiting_approval'
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                  : 'bg-zinc-500/20 text-zinc-300'
                              }`}
                            >
                              {r.status}
                            </span>
                          )}
                        </td>
                        <td className="p-3 capitalize text-fg-muted">{r.trigger_type}</td>
                        <td className="p-3 text-fg-muted">{r.total_duration_ms > 0 ? `${r.total_duration_ms} ms` : '-'}</td>
                        <td className="p-3 text-fg-muted">{r.total_tokens.toLocaleString()}</td>
                        <td className="p-3 text-fg-muted">{new Date(r.started_at).toLocaleTimeString()}</td>
                        <td className="p-3 text-right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleInspectRun(r.run_id);
                            }}
                            className="p-1.5 text-fg-muted hover:text-accent rounded-lg hover:bg-panel transition"
                            title="Ispeziona dettagli run"
                          >
                            <Eye size={15} />
                          </button>
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
      </div>

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
    </div>
  );
};
