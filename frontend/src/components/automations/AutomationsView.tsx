import React, { useState } from 'react';
import { FileText, Inbox, Key, Layers, Plus, Sparkles, Workflow, Zap, type LucideIcon } from 'lucide-react';
import { getAutomationRunDetails, triggerAutomationRun, type AutomationRunDetails } from '../../api/automationRuns';
import { deleteAutomation, getAutomation, toggleAutomationEnabled, type AutomationSummary } from '../../api/automations';
import { useAutomationsData } from '../../hooks/useAutomationsData';
import { useFeedback } from '../../hooks/useFeedback';
import { useRunActions } from '../../hooks/useRunActions';
import { formatApiError } from '../../utils/error';
import { FeedbackToast } from '../FeedbackToast';
import { ApprovalsTab } from './ApprovalsTab';
import { ArtifactsView } from './ArtifactsView';
import { AutomationCard, type AutomationActions } from './AutomationCard';
import { AutomationsHeader } from './AutomationsHeader';
import { EditAutomationModal } from './EditAutomationModal';
import { IntegrationsTab } from './IntegrationsTab';
import { ParametersModal } from './ParametersModal';
import { RunInspectorModal } from './RunInspectorModal';
import { RunsTab } from './RunsTab';
import { TemplatesTab } from './TemplatesTab';
import { TriggerEditorModal } from './TriggerEditorModal';

type Tab = 'automations' | 'artifacts' | 'runs' | 'approvals' | 'templates' | 'integrations';

interface AutomationsViewProps {
  onOpenMobileSidebar?: () => void;
}

export const AutomationsView: React.FC<AutomationsViewProps> = ({ onOpenMobileSidebar }) => {
  const { feedback, notify } = useFeedback();
  const data = useAutomationsData(notify);
  const runActions = useRunActions(notify, data.reload, data.setRuns);

  const [activeTab, setActiveTab] = useState<Tab>('automations');
  const [artifactToOpen, setArtifactToOpen] = useState<string | null>(null);
  const [inspectedRun, setInspectedRun] = useState<AutomationRunDetails | null>(null);
  const [paramsTarget, setParamsTarget] = useState<{ automation: AutomationSummary; mode: 'edit' | 'run' } | null>(null);
  const [editTarget, setEditTarget] = useState<any | null>(null);
  const [triggersTarget, setTriggersTarget] = useState<AutomationSummary | null>(null);

  const inspectRun = async (runId: string) => {
    try {
      setInspectedRun(await getAutomationRunDetails(runId));
    } catch (err) {
      notify('error', `Impossibile caricare dettaglio run: ${formatApiError(err)}`);
    }
  };

  const openArtifacts = (artifactId: string | null) => {
    setArtifactToOpen(artifactId);
    setActiveTab('artifacts');
  };

  const automationActions: AutomationActions = {
    run: async (id, dryRun) => {
      try {
        const result = await triggerAutomationRun(id, dryRun, false);
        notify('success', `${dryRun ? 'Dry-Run (anteprima sicura)' : 'Esecuzione'} avviata per ${id} (ID: ${result.run_id})`);
        data.reload();
      } catch (err) {
        notify('error', `Errore avvio run: ${formatApiError(err)}`);
      }
    },
    remove: async (id) => {
      if (!confirm(`Sei sicuro di voler eliminare l'automazione "${id}"?`)) return;
      try {
        await deleteAutomation(id);
        notify('success', `Automazione "${id}" eliminata.`);
        data.reload();
      } catch (err) {
        notify('error', `Errore eliminazione: ${formatApiError(err)}`);
      }
    },
    toggleEnabled: async (auto) => {
      try {
        const res = await toggleAutomationEnabled(auto.id, !auto.enabled);
        data.setAutomations((prev) => prev.map((a) => (a.id === auto.id ? { ...a, enabled: res.enabled } : a)));
        notify('success', `Automazione '${auto.name}' ${res.enabled ? 'attivata' : 'disattivata'}.`);
      } catch (err) {
        notify('error', formatApiError(err, "Errore durante l'aggiornamento dello stato."));
      }
    },
    openParams: (automation, mode) => setParamsTarget({ automation, mode }),
    openTriggers: setTriggersTarget,
    openEditor: async (auto) => {
      try {
        setEditTarget(await getAutomation(auto.id));
      } catch (err) {
        notify('error', `Impossibile caricare l'automazione: ${formatApiError(err)}`);
      }
    },
    openReport: openArtifacts,
    inspectRun,
    copied: (message) => notify('success', message),
  };

  const tabs: Array<{ id: Tab; icon: LucideIcon; label: string; badge?: number }> = [
    { id: 'automations', icon: Layers, label: `Automazioni (${data.automations.length})` },
    { id: 'artifacts', icon: FileText, label: 'Artefatti & Report' },
    { id: 'runs', icon: Zap, label: `Storico Run (${data.runs.length})` },
    { id: 'approvals', icon: Inbox, label: 'Approvazioni Inbox', badge: data.approvals.length },
    { id: 'templates', icon: Sparkles, label: `Template Gallery (${data.templates.length})` },
    { id: 'integrations', icon: Key, label: 'Integrazioni & Servizi' },
  ];

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent text-fg overflow-hidden relative font-sans">
      <AutomationsHeader
        counts={{
          automations: data.automations.length,
          jobs: data.scheduledJobs.length,
          runs: data.runs.length,
          approvals: data.approvals.length,
        }}
        isLoading={data.isLoading}
        onRefresh={data.reload}
        onOpenMobileSidebar={onOpenMobileSidebar}
      />

      <FeedbackToast feedback={feedback} />

      <div className="flex border-b border-border px-2 sm:px-4 bg-panel-header/20 shrink-0 overflow-x-auto">
        {tabs.map(({ id, icon: Icon, label, badge }) => (
          <button
            key={id}
            onClick={() => (id === 'artifacts' ? openArtifacts(null) : setActiveTab(id))}
            className={`py-2.5 sm:py-3 px-2.5 sm:px-4 text-xs font-medium border-b-2 transition flex items-center gap-1.5 sm:gap-2 cursor-pointer shrink-0 whitespace-nowrap ${
              activeTab === id ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Icon size={15} /> {label}
            {Boolean(badge) && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-rose-500 text-white font-bold">{badge}</span>
            )}
          </button>
        ))}
      </div>

      {/* La scheda artefatti usa un layout a pannelli a tutta altezza, fuori dal contenitore scrollabile */}
      {activeTab === 'artifacts' ? (
        <ArtifactsView initialArtifactId={artifactToOpen} onFeedback={notify} />
      ) : (
        <div className="flex-1 overflow-y-auto p-3 sm:p-5">
          {activeTab === 'automations' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between pb-2">
                <h2 className="text-xs font-semibold text-fg-muted uppercase tracking-wider">Definizioni di Workflow Attive</h2>
                <button
                  onClick={() => setActiveTab('templates')}
                  className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm transition cursor-pointer"
                >
                  <Plus size={14} /> Da Template
                </button>
              </div>

              {data.automations.length === 0 ? (
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
                  {data.automations.map((auto) => (
                    <AutomationCard
                      key={auto.id}
                      automation={auto}
                      runs={data.runs.filter((r) => r.automation_id === auto.id)}
                      actions={automationActions}
                      runActions={runActions}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === 'runs' && (
            <RunsTab runs={data.runs} runActions={runActions} onInspect={inspectRun} onOpenArtifacts={() => openArtifacts(null)} />
          )}

          {activeTab === 'approvals' && <ApprovalsTab approvals={data.approvals} notify={notify} reload={data.reload} />}

          {activeTab === 'templates' && (
            <TemplatesTab
              templates={data.templates}
              notify={notify}
              onInstalled={() => {
                setActiveTab('automations');
                data.reload();
              }}
            />
          )}

          {activeTab === 'integrations' && <IntegrationsTab onFeedback={notify} />}
        </div>
      )}

      <RunInspectorModal
        run={inspectedRun}
        isOpen={inspectedRun !== null}
        onClose={() => setInspectedRun(null)}
        onRefresh={() => inspectedRun && inspectRun(inspectedRun.run_id)}
      />

      <ParametersModal
        automation={paramsTarget?.automation ?? null}
        isOpen={paramsTarget !== null}
        mode={paramsTarget?.mode ?? 'edit'}
        onClose={() => setParamsTarget(null)}
        onSuccess={data.reload}
        onFeedback={notify}
      />

      {editTarget && (
        <EditAutomationModal
          automation={editTarget}
          onClose={() => setEditTarget(null)}
          onSuccess={data.reload}
          onFeedback={(type, msg) => notify(type === 'error' ? 'error' : 'success', msg)}
        />
      )}

      {triggersTarget && (
        <TriggerEditorModal
          automation={triggersTarget}
          onClose={() => setTriggersTarget(null)}
          onSaved={() => {
            data.reload();
            notify('success', `Trigger aggiornati per '${triggersTarget.name}'.`);
          }}
        />
      )}
    </div>
  );
};
