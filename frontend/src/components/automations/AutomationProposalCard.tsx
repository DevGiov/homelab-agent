import React, { useState } from 'react';
import {
  Sparkles,
  Zap,
  Play,
  CheckCircle2,
  Clock,
  Shield,
  Code2,
  AlertCircle,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  Layers,
} from 'lucide-react';
import { createOrUpdateAutomation, triggerAutomationRun } from '../../api';

interface AutomationProposalCardProps {
  rawJson: string;
}

export const AutomationProposalCard: React.FC<AutomationProposalCardProps> = ({ rawJson }) => {
  const [copied, setCopied] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const [isDryRunning, setIsDryRunning] = useState(false);
  const [activated, setActivated] = useState(false);
  const [dryRunResult, setDryRunResult] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  let proposal: any = null;
  try {
    proposal = JSON.parse(rawJson);
  } catch (err) {
    // If not valid JSON, fallback
    return null;
  }

  if (!proposal || typeof proposal !== 'object' || (!proposal.workflow && !proposal.name)) {
    return null;
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(rawJson);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleActivate = async () => {
    setIsActivating(true);
    setErrorMsg(null);
    try {
      // Assicura che l'ID esista
      const payload = {
        ...proposal,
        id: proposal.id || `auto_${Date.now()}`,
        enabled: true,
      };
      await createOrUpdateAutomation(payload);
      setActivated(true);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || err?.message || 'Errore durante il salvataggio');
    } finally {
      setIsActivating(false);
    }
  };

  const handleDryRun = async () => {
    setIsDryRunning(true);
    setErrorMsg(null);
    setDryRunResult(null);
    try {
      const autoId = proposal.id || `auto_test_${Date.now()}`;
      const payload = {
        ...proposal,
        id: autoId,
        enabled: false,
      };
      // Salva come bozza disabilitata per il test
      await createOrUpdateAutomation(payload);
      const res = await triggerAutomationRun(autoId, true, true);
      setDryRunResult(`Dry-Run completato con successo! Stato: ${res.status}`);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || err?.message || 'Errore durante il dry-run');
    } finally {
      setIsDryRunning(false);
    }
  };

  const triggers = proposal.triggers || [];
  const steps = proposal.workflow?.steps || [];
  const allowedTools = proposal.permission_policy?.allowed_tools || [];

  return (
    <div className="my-4 rounded-2xl border border-accent/40 bg-panel/90 backdrop-blur-md overflow-hidden shadow-2xl transition-all">
      {/* Intestazione */}
      <div className="bg-gradient-to-r from-accent/20 via-panel/80 to-panel px-4 py-3 border-b border-border/80 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-accent/20 text-accent border border-accent/40">
            <Sparkles size={18} className="animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase font-bold tracking-wider text-accent">
                Proposta di Automazione
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-panel border border-border text-fg-muted font-mono">
                v{proposal.version || 1}
              </span>
            </div>
            <h4 className="text-sm sm:text-base font-semibold text-fg">
              {proposal.name || 'Nuova Automazione'}
            </h4>
          </div>
        </div>

        <button
          onClick={handleCopy}
          className="p-1.5 rounded-lg text-fg-muted hover:text-fg hover:bg-panel border border-border/60 transition cursor-pointer"
          title="Copia JSON proposta"
        >
          {copied ? <Check size={15} className="text-emerald-400" /> : <Copy size={15} />}
        </button>
      </div>

      <div className="p-4 space-y-3.5 text-xs">
        {/* Descrizione */}
        {proposal.description && (
          <p className="text-fg/80 leading-relaxed font-sans">{proposal.description}</p>
        )}

        {/* Trigger info */}
        {triggers.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-fg-muted font-medium flex items-center gap-1">
              <Clock size={12} className="text-accent" /> Trigger:
            </span>
            {triggers.map((t: any, idx: number) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-panel border border-border text-[11px] font-mono text-fg"
              >
                <Zap size={11} className="text-amber-400" />
                {t.type === 'cron' ? `Cron: ${t.cron_expression}` : t.type}
              </span>
            ))}
          </div>
        )}

        {/* Workflow Steps */}
        <div className="space-y-1.5">
          <span className="text-fg-muted font-medium flex items-center gap-1">
            <Layers size={12} className="text-accent" /> Sequenza Step ({steps.length}):
          </span>
          <div className="rounded-xl border border-border/80 bg-panel/60 p-2 space-y-2">
            {steps.map((s: any, idx: number) => (
              <div
                key={idx}
                className="flex items-start justify-between gap-2 p-1.5 rounded-lg hover:bg-panel/80 transition"
              >
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full bg-accent/20 text-accent font-bold flex items-center justify-center text-[10px] shrink-0 mt-0.5">
                    {idx + 1}
                  </span>
                  <div>
                    <div className="font-semibold text-fg text-xs">{s.name || s.step_id}</div>
                    <div className="text-[10px] font-mono text-fg-muted flex items-center gap-1 mt-0.5">
                      <span className="px-1.5 py-0.5 rounded bg-panel border border-border/60">
                        {s.type}
                      </span>
                      {s.action_or_tool && (
                        <span className="text-accent font-mono">{s.action_or_tool}</span>
                      )}
                    </div>
                  </div>
                </div>
                {s.requires_approval && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 shrink-0">
                    Richiede Approvazione
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Permissions & Security */}
        {allowedTools.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-fg-muted font-medium flex items-center gap-1 text-[11px]">
              <Shield size={12} className="text-emerald-400" /> Permessi Tool:
            </span>
            {allowedTools.map((t: string, idx: number) => (
              <span
                key={idx}
                className="px-2 py-0.5 rounded bg-panel border border-border text-[10px] font-mono text-accent"
              >
                {t}
              </span>
            ))}
          </div>
        )}

        {/* Messaggi di esito o errore */}
        {errorMsg && (
          <div className="flex items-center gap-2 p-2.5 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs">
            <AlertCircle size={14} className="shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {dryRunResult && (
          <div className="flex items-center gap-2 p-2.5 rounded-xl bg-blue-500/20 border border-blue-500/40 text-blue-300 text-xs font-mono">
            <CheckCircle2 size={14} className="shrink-0" />
            <span>{dryRunResult}</span>
          </div>
        )}

        {activated && (
          <div className="flex items-center gap-2 p-2.5 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs">
            <CheckCircle2 size={14} className="shrink-0" />
            <span>Automazione salvata ed attivata con successo! Ora è visibile in Automations Hub.</span>
          </div>
        )}

        {/* Toggle Mostra JSON Raw */}
        <div className="pt-1">
          <button
            onClick={() => setShowJson(!showJson)}
            className="flex items-center gap-1 text-[11px] text-fg-muted hover:text-fg transition cursor-pointer"
          >
            <Code2 size={12} />
            <span>{showJson ? 'Nascondi Spec JSON' : 'Ispeziona Spec JSON'}</span>
            {showJson ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          {showJson && (
            <pre className="mt-2 p-3 rounded-xl bg-panel border border-border text-[11px] font-mono text-fg-muted overflow-x-auto max-h-56">
              {rawJson}
            </pre>
          )}
        </div>

        {/* Action Buttons */}
        <div className="pt-2 border-t border-border/60 flex flex-wrap items-center justify-end gap-2.5">
          <button
            onClick={handleDryRun}
            disabled={isDryRunning || isActivating}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-panel hover:bg-panel/80 text-fg text-xs font-medium border border-border/80 transition cursor-pointer disabled:opacity-50"
          >
            <Play size={13} className="text-amber-400" />
            <span>{isDryRunning ? 'Simulazione...' : 'Test (Dry-Run)'}</span>
          </button>

          <button
            onClick={handleActivate}
            disabled={isActivating || activated}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-accent hover:bg-accent/90 text-accent-contrast text-xs font-semibold shadow-md hover:shadow-lg transition cursor-pointer disabled:opacity-50"
          >
            {activated ? (
              <>
                <CheckCircle2 size={13} />
                <span>Attivata</span>
              </>
            ) : (
              <>
                <Zap size={13} />
                <span>{isActivating ? 'Salvataggio...' : 'Attiva Automazione'}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
