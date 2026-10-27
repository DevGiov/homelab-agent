import React, { useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  Clock,
  Edit2,
  Eye,
  FileText,
  Globe,
  Layers,
  Pause,
  Play,
  Shield,
  Sliders,
  Square,
  Trash2,
} from 'lucide-react';
import type { AutomationRunSummary } from '../../api/automationRuns';
import type { AutomationSummary } from '../../api/automations';
import { useCopyFeedback } from '../../hooks/useCopyFeedback';
import type { RunActions } from '../../hooks/useRunActions';
import { AutomationCardDetails } from './AutomationCardDetails';

export interface AutomationActions {
  run: (automationId: string, dryRun: boolean) => void;
  remove: (automationId: string) => void;
  toggleEnabled: (automation: AutomationSummary) => Promise<void>;
  openParams: (automation: AutomationSummary, mode: 'edit' | 'run') => void;
  openTriggers: (automation: AutomationSummary) => void;
  openEditor: (automation: AutomationSummary) => void;
  openReport: (artifactId: string) => void;
  inspectRun: (runId: string) => void;
  copied: (message: string) => void;
}

interface AutomationCardProps {
  automation: AutomationSummary;
  /** Run di questa automazione. */
  runs: AutomationRunSummary[];
  actions: AutomationActions;
  runActions: RunActions;
}

const ACTIVE_STATUSES = ['running', 'waiting_approval', 'paused'];
const iconButton = 'p-1.5 text-fg-muted hover:bg-panel rounded-lg border border-transparent hover:border-border transition cursor-pointer';
const secondaryButton =
  'px-3 py-1.5 bg-panel-header hover:bg-panel border border-border text-fg rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer';

export const AutomationCard: React.FC<AutomationCardProps> = ({ automation: auto, runs, actions, runActions }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isToggling, setIsToggling] = useState(false);
  const { copied, copy } = useCopyFeedback();

  const activeRun = runs.find((r) => ACTIVE_STATUSES.includes(r.status.toLowerCase()));
  const activeStatus = activeRun?.status.toLowerCase();
  const isRunning = activeStatus === 'running';
  const isPaused = activeStatus === 'paused';
  const cron = auto.triggers?.find((t) => t.type === 'cron');
  const webhookToken = auto.triggers?.find((t) => t.type === 'webhook')?.webhook_token;
  const parameters = Object.entries(auto.parameters ?? {});

  const toggleEnabled = async () => {
    setIsToggling(true);
    await actions.toggleEnabled(auto);
    setIsToggling(false);
  };

  const copyWebhookUrl = async () => {
    if (!webhookToken) {
      actions.openTriggers(auto);
      return;
    }
    await copy(`${window.location.origin}/v1/automations/${auto.id}/webhook/${webhookToken}`);
    actions.copied('URL Webhook copiato negli appunti!');
  };

  return (
    <div
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
            ) : activeStatus === 'waiting_approval' ? (
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30 animate-pulse">
                Attesa Approvazione
              </span>
            ) : null}

            <div className="flex items-center gap-2 bg-panel-header/60 px-2.5 py-1 rounded-xl border border-border/60">
              <span className={`text-[11px] font-semibold transition ${auto.enabled ? 'text-emerald-400' : 'text-fg-muted'}`}>
                {auto.enabled ? 'Attiva' : 'Inattiva'}
              </span>
              <label
                className={`relative inline-flex items-center cursor-pointer ${isToggling ? 'opacity-50 pointer-events-none' : ''}`}
                title={auto.enabled ? 'Disattiva automazione e schedulazioni' : 'Attiva automazione e schedulazioni'}
              >
                <input type="checkbox" checked={auto.enabled} onChange={toggleEnabled} className="sr-only peer" />
                <div className="w-8 h-4 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-emerald-500"></div>
              </label>
            </div>
          </div>
        </div>

        <p className="text-xs text-fg-muted mt-3 line-clamp-2">{auto.description || 'Nessuna descrizione specificata.'}</p>

        <div className="flex items-center justify-between mt-4 text-xs text-fg-muted flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5">
              <Layers size={13} className="text-accent" /> {auto.steps_count} step
            </span>

            <button
              onClick={() => actions.openTriggers(auto)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 transition text-[11px] font-medium cursor-pointer"
              title="Configura Schedulazione Cron e Webhook HTTP"
            >
              <Clock size={12} className="text-emerald-400" />
              <span>{cron ? cron.cron_expression : `${auto.triggers_count} trigger`}</span>
            </button>

            {auto.triggers?.some((t) => t.type === 'webhook') && (
              <button
                onClick={copyWebhookUrl}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 transition text-[11px] font-medium cursor-pointer"
                title="Fai clic per copiare l'URL Webhook negli appunti"
              >
                <Globe size={12} className="text-sky-400" />
                <span>{copied ? 'URL Copiato!' : 'Webhook'}</span>
              </button>
            )}
          </div>

          {auto.last_artifact_id && (
            <button
              onClick={() => actions.openReport(auto.last_artifact_id!)}
              className="px-2.5 py-1 rounded-lg bg-accent/15 hover:bg-accent/25 text-accent border border-accent/30 text-[11px] font-medium flex items-center gap-1.5 transition cursor-pointer"
              title={`Apri report: ${auto.last_artifact_name || 'Ultimo Report'}`}
            >
              <FileText size={12} />
              <span className="truncate max-w-[140px]">{auto.last_artifact_name || 'Ultimo Report'}</span>
            </button>
          )}
        </div>

        {parameters.length > 0 && (
          <div className="mt-3 pt-2.5 border-t border-border/40">
            <div className="text-[10px] text-fg-muted uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
              <Sliders size={11} className="text-accent" /> Parametri di default
            </div>
            <div className="flex flex-wrap gap-1.5">
              {parameters.slice(0, 3).map(([key, value]) => (
                <span
                  key={key}
                  className="text-[10px] px-2 py-0.5 rounded-md bg-panel-header/70 border border-border text-fg-muted font-mono"
                  title={`${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`}
                >
                  {key}: <span className="text-fg font-medium">{typeof value === 'object' ? '{...}' : String(value)}</span>
                </span>
              ))}
              {parameters.length > 3 && (
                <span className="text-[10px] text-fg-muted self-center">+{parameters.length - 3} altri</span>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2 pt-1">
        <div className="pt-2 border-t border-border/40 flex items-center justify-between text-[11px] text-fg-muted">
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 hover:text-fg transition cursor-pointer font-medium"
          >
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            <span>{isExpanded ? 'Nascondi Pipeline & Statistiche' : 'Mostra Pipeline & Statistiche'}</span>
          </button>
          <span className="font-mono text-[10px]">TTL: {auto.retention_days || 14} giorni</span>
        </div>
        {isExpanded && <AutomationCardDetails automation={auto} runsCount={runs.length} />}
      </div>

      <div className="pt-3 border-t border-border/60 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 flex-wrap">
        {activeRun && (isRunning || isPaused) ? (
          <div className="flex items-center gap-1.5 flex-wrap">
            {isRunning ? (
              <button
                onClick={() => runActions.pause(activeRun.run_id)}
                className="px-3 py-1.5 bg-amber-600/90 hover:bg-amber-600 text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition cursor-pointer"
                title="Metti in pausa l'esecuzione al termine del passo corrente"
              >
                <Pause size={12} /> Pausa
              </button>
            ) : (
              <button
                onClick={() => runActions.resume(activeRun.run_id)}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition cursor-pointer"
                title="Riprendi l'esecuzione dal passo corrente"
              >
                <Play size={12} /> Riprendi
              </button>
            )}
            <button onClick={() => actions.inspectRun(activeRun.run_id)} className={secondaryButton} title="Ispeziona esecuzione">
              <Eye size={12} /> Ispeziona
            </button>
            <button
              onClick={() => runActions.remove(activeRun.run_id)}
              className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg hover:bg-panel transition cursor-pointer"
              title={isRunning ? 'Arresta ed elimina run' : 'Cancella run'}
            >
              {isRunning ? <Square size={13} /> : <Trash2 size={13} />}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => actions.run(auto.id, false)}
              className="px-3 py-1.5 bg-accent/90 hover:bg-accent text-white rounded-lg text-xs font-medium flex items-center gap-1 shadow-sm transition cursor-pointer"
              title="Lancia esecuzione completa con parametri di default"
            >
              <Play size={12} /> Esegui
            </button>
            <button
              onClick={() => actions.run(auto.id, true)}
              className="px-3 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 border border-purple-500/30 rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
              title="Anteprima sicura senza modifiche (Dry-Run)"
            >
              <Shield size={12} /> Dry-Run
            </button>
            <button
              onClick={() => actions.openParams(auto, 'run')}
              className="px-2.5 py-1.5 bg-panel-header/60 hover:bg-panel-header text-fg-muted hover:text-fg border border-border rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
              title="Esegui con parametri personalizzati per questa istanza"
            >
              <Play size={11} className="text-emerald-400" /> + Parametri
            </button>
          </div>
        )}

        <div className="flex items-center gap-1">
          <button
            onClick={() => actions.openTriggers(auto)}
            className={`${iconButton} hover:text-emerald-400`}
            title="Configura Schedulazione (Cron) e Trigger Webhook HTTP"
          >
            <Clock size={15} />
          </button>
          <button
            onClick={() => actions.openEditor(auto)}
            className={`${iconButton} hover:text-accent`}
            title="Modifica workflow, trigger, prompt e parametri dell'automazione"
          >
            <Edit2 size={15} />
          </button>
          <button
            onClick={() => actions.openParams(auto, 'edit')}
            className={`${iconButton} hover:text-accent`}
            title="Configura o modifica parametri di default"
          >
            <Sliders size={15} />
          </button>
          <button
            onClick={() => actions.remove(auto.id)}
            className="p-1.5 text-fg-muted hover:text-rose-400 hover:bg-panel rounded-lg transition cursor-pointer"
            title="Elimina automazione"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>
    </div>
  );
};
