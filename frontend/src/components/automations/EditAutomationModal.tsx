import React, { useState } from 'react';
import {
  X,
  Save,
  Clock,
  Layers,
  Shield,
  Code2,
  Sliders,
  Plus,
  Trash2,
  ChevronUp,
  ChevronDown,
  AlertCircle,
  Settings,
} from 'lucide-react';
import { updateAutomation } from '../../api';
import { formatApiError } from '../../utils/error';

interface StepDef {
  step_id: string;
  name: string;
  type: 'deterministic_action' | 'agentic_task' | 'approval_gate';
  action_or_tool?: string | null;
  prompt_template?: string | null;
  parameters?: Record<string, any>;
  requires_approval?: boolean;
  timeout_seconds?: number;
}

interface EditAutomationModalProps {
  automation: any;
  onClose: () => void;
  onSuccess: (updated: any) => void;
  onFeedback?: (type: 'success' | 'error' | 'info', msg: string) => void;
}

export const EditAutomationModal: React.FC<EditAutomationModalProps> = ({
  automation,
  onClose,
  onSuccess,
  onFeedback,
}) => {
  const [activeTab, setActiveTab] = useState<'general' | 'trigger' | 'workflow' | 'budget' | 'json'>('general');
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Form State
  const [name, setName] = useState(automation.name || '');
  const [description, setDescription] = useState(automation.description || '');
  const [enabled, setEnabled] = useState(automation.enabled ?? true);
  const [retentionDays, setRetentionDays] = useState<number | ''>(
    automation.retention_days !== null && automation.retention_days !== undefined ? automation.retention_days : 14
  );

  // Trigger State
  const initialTrigger = automation.triggers?.[0] || { type: 'cron', cron_expression: '0 12 * * *', timezone: 'Europe/Rome' };
  const [cronExpression, setCronExpression] = useState(initialTrigger.cron_expression || '0 12 * * *');
  const [timezone, setTimezone] = useState(initialTrigger.timezone || 'Europe/Rome');

  // Workflow Steps State
  const initialSteps: StepDef[] = (automation.workflow?.steps || []).map((s: any) => ({
    step_id: s.step_id || `step_${Math.random().toString(36).substring(2, 7)}`,
    name: s.name || 'Step',
    type: s.type || 'deterministic_action',
    action_or_tool: s.action_or_tool || null,
    prompt_template: s.prompt_template || null,
    parameters: s.parameters || {},
    requires_approval: Boolean(s.requires_approval),
    timeout_seconds: s.timeout_seconds || 60,
  }));
  const [steps, setSteps] = useState<StepDef[]>(initialSteps);

  // Budget State
  const [maxDuration, setMaxDuration] = useState<number>(automation.budget?.max_duration_seconds || 300);
  const [maxTokens, setMaxTokens] = useState<number>(automation.budget?.max_tokens || 50000);
  const [maxLlmCalls, setMaxLlmCalls] = useState<number>(automation.budget?.max_llm_calls || 10);
  const [maxToolCalls, setMaxToolCalls] = useState<number>(automation.budget?.max_tool_calls || 25);
  const [maxRetries, setMaxRetries] = useState<number>(automation.budget?.max_retries_per_step || 2);

  // JSON Raw State
  const [rawJson, setRawJson] = useState(() => JSON.stringify(automation, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Sync state to Raw JSON when switching to json tab
  const handleTabChange = (newTab: typeof activeTab) => {
    if (newTab === 'json') {
      const compiled = buildAutomationObject();
      setRawJson(JSON.stringify(compiled, null, 2));
      setJsonError(null);
    }
    setActiveTab(newTab);
  };

  const buildAutomationObject = () => {
    const updated = {
      ...automation,
      name,
      description,
      enabled,
      retention_days: retentionDays === '' ? null : Number(retentionDays),
      version: (automation.version || 1) + 1,
      triggers: [
        {
          id: automation.triggers?.[0]?.id || 'trg_1',
          type: 'cron',
          cron_expression: cronExpression,
          timezone,
          enabled: true,
        },
      ],
      workflow: {
        initial_step_id: steps[0]?.step_id || 'step_1',
        steps: steps.map((s) => ({
          step_id: s.step_id,
          name: s.name,
          type: s.type,
          action_or_tool: s.type === 'agentic_task' ? null : s.action_or_tool,
          prompt_template: s.type === 'agentic_task' ? s.prompt_template : null,
          parameters: s.parameters || {},
          requires_approval: s.requires_approval,
          timeout_seconds: s.timeout_seconds,
        })),
      },
      budget: {
        max_duration_seconds: Number(maxDuration),
        max_tokens: Number(maxTokens),
        max_llm_calls: Number(maxLlmCalls),
        max_tool_calls: Number(maxToolCalls),
        max_retries_per_step: Number(maxRetries),
      },
    };
    return updated;
  };

  const handleAddStep = () => {
    const nextIdx = steps.length + 1;
    const newStep: StepDef = {
      step_id: `step_${nextIdx}_action`,
      name: `Nuovo Step ${nextIdx}`,
      type: 'deterministic_action',
      action_or_tool: 'web_search',
      parameters: { query: '' },
      prompt_template: null,
      requires_approval: false,
      timeout_seconds: 60,
    };
    setSteps([...steps, newStep]);
  };

  const handleRemoveStep = (index: number) => {
    if (steps.length <= 1) {
      setErrorMsg('Il workflow deve contenere almeno uno step.');
      return;
    }
    setSteps(steps.filter((_, i) => i !== index));
  };

  const handleMoveStep = (index: number, direction: 'up' | 'down') => {
    const targetIdx = direction === 'up' ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= steps.length) return;
    const copy = [...steps];
    const item = copy.splice(index, 1)[0];
    copy.splice(targetIdx, 0, item);
    setSteps(copy);
  };

  const handleUpdateStep = (index: number, patch: Partial<StepDef>) => {
    setSteps(
      steps.map((s, i) => {
        if (i !== index) return s;
        const updated = { ...s, ...patch };
        // Reset action/prompt based on type
        if (patch.type === 'agentic_task' && s.type !== 'agentic_task') {
          updated.action_or_tool = null;
          updated.prompt_template = s.prompt_template || 'Analizza i risultati: {{steps.step_1.output.text}}';
        } else if (patch.type === 'deterministic_action' && s.type !== 'deterministic_action') {
          updated.action_or_tool = s.action_or_tool || 'web_search';
          updated.prompt_template = null;
        }
        return updated;
      })
    );
  };

  const handleSave = async () => {
    setErrorMsg(null);
    setSaving(true);

    try {
      let payloadToSave: any;
      if (activeTab === 'json') {
        try {
          payloadToSave = JSON.parse(rawJson);
        } catch (e: any) {
          setJsonError(`Errore sintassi JSON: ${e.message}`);
          setSaving(false);
          return;
        }
      } else {
        if (!name.trim()) {
          setErrorMsg('Il nome dell\'automazione è obbligatorio.');
          setSaving(false);
          return;
        }
        if (steps.length === 0) {
          setErrorMsg('Il workflow deve contenere almeno uno step.');
          setSaving(false);
          return;
        }
        payloadToSave = buildAutomationObject();
      }

      const res = await updateAutomation(automation.id, payloadToSave);
      onFeedback?.('success', `Automazione '${res.name || automation.name}' aggiornata con successo (v${res.version || (automation.version || 1) + 1})!`);
      onSuccess(res);
      onClose();
    } catch (err: any) {
      setErrorMsg(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto animate-fade-in">
      <div className="bg-panel border border-border rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden my-auto">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-panel-header/40 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-accent/10 border border-accent/20 rounded-xl text-accent">
              <Sliders size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-fg">Modifica Automazione</h3>
                <span className="font-mono text-xs px-2 py-0.5 bg-panel border border-border rounded-md text-fg-muted">
                  {automation.id}
                </span>
                <span className="text-[11px] font-semibold px-2 py-0.5 bg-accent/15 text-accent rounded-full border border-accent/30">
                  v{automation.version || 1}
                </span>
              </div>
              <p className="text-xs text-fg-muted mt-0.5">
                Modifica parametri, schedulazione e step della pipeline per aggiornare il comportamento del workflow.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="px-6 pt-2 border-b border-border flex items-center gap-2 bg-panel-header/20 overflow-x-auto shrink-0">
          <button
            onClick={() => handleTabChange('general')}
            className={`px-3 py-2 text-xs font-medium border-b-2 flex items-center gap-1.5 transition cursor-pointer ${
              activeTab === 'general' ? 'border-accent text-accent font-semibold' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Settings size={13} /> Generale
          </button>
          <button
            onClick={() => handleTabChange('trigger')}
            className={`px-3 py-2 text-xs font-medium border-b-2 flex items-center gap-1.5 transition cursor-pointer ${
              activeTab === 'trigger' ? 'border-accent text-accent font-semibold' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Clock size={13} /> Schedulazione & Cron
          </button>
          <button
            onClick={() => handleTabChange('workflow')}
            className={`px-3 py-2 text-xs font-medium border-b-2 flex items-center gap-1.5 transition cursor-pointer ${
              activeTab === 'workflow' ? 'border-accent text-accent font-semibold' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Layers size={13} /> Pipeline Step ({steps.length})
          </button>
          <button
            onClick={() => handleTabChange('budget')}
            className={`px-3 py-2 text-xs font-medium border-b-2 flex items-center gap-1.5 transition cursor-pointer ${
              activeTab === 'budget' ? 'border-accent text-accent font-semibold' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Shield size={13} /> Budget & Guardrail
          </button>
          <button
            onClick={() => handleTabChange('json')}
            className={`px-3 py-2 text-xs font-medium border-b-2 flex items-center gap-1.5 transition cursor-pointer ${
              activeTab === 'json' ? 'border-accent text-accent font-semibold' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Code2 size={13} /> Spec JSON Raw
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto flex-1 space-y-5">
          {errorMsg && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300 flex items-start gap-2">
              <AlertCircle size={15} className="shrink-0 mt-0.5 text-rose-400" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* TAB: GENERALE */}
          {activeTab === 'general' && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-fg mb-1">Nome Automazione</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent"
                  placeholder="es. GitHub Trending Daily Report"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-fg mb-1">Descrizione</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full bg-panel border border-border rounded-xl p-3 text-xs text-fg focus:outline-none focus:border-accent"
                  placeholder="Spiega lo scopo del workflow, gli input attesi e l'output generato."
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-border/50">
                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Stato Automazione</label>
                  <div className="flex items-center gap-2 mt-1">
                    <input
                      type="checkbox"
                      id="enable-auto-toggle"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                      className="w-4 h-4 rounded border-border text-accent focus:ring-0"
                    />
                    <label htmlFor="enable-auto-toggle" className="text-xs text-fg cursor-pointer select-none">
                      {enabled ? 'Abilitata (schedulazione e trigger attivi)' : 'Disabilitata (nessuna esecuzione automatica)'}
                    </label>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Retention TTL (Giorni)</label>
                  <input
                    type="number"
                    value={retentionDays}
                    onChange={(e) => setRetentionDays(e.target.value === '' ? '' : Number(e.target.value))}
                    min={1}
                    max={365}
                    className="w-full bg-panel border border-border rounded-xl px-3 py-1.5 text-xs text-fg focus:outline-none focus:border-accent"
                    placeholder="14 (default)"
                  />
                  <p className="text-[11px] text-fg-muted mt-1">
                    Le run non protette con lucchetto verranno rimosse dopo questo intervallo dal cleanup notturno.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* TAB: SCHEDULAZIONE & CRON */}
          {activeTab === 'trigger' && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-fg mb-1">Espressione Cron</label>
                <input
                  type="text"
                  value={cronExpression}
                  onChange={(e) => setCronExpression(e.target.value)}
                  className="w-full bg-panel border border-border rounded-xl px-3 py-2 font-mono text-xs text-fg focus:outline-none focus:border-accent"
                  placeholder="0 12 * * *"
                />
                <p className="text-[11px] text-fg-muted mt-1">
                  Formato standard a 5 campi: <code>minuti ore giorno_mese mese giorno_settimana</code>
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-fg mb-1.5">Preset Rapidi</label>
                <div className="flex flex-wrap gap-2">
                  {[
                    { label: 'Ogni Ora', expr: '0 * * * *' },
                    { label: 'Ogni Giorno alle 09:00', expr: '0 9 * * *' },
                    { label: 'Ogni Giorno alle 12:00', expr: '0 12 * * *' },
                    { label: 'Ogni Sera alle 20:00', expr: '0 20 * * *' },
                    { label: 'Ogni Notte alle 02:00', expr: '0 2 * * *' },
                    { label: 'Ogni Lunedì alle 08:00', expr: '0 8 * * 1' },
                  ].map((preset) => (
                    <button
                      key={preset.expr}
                      type="button"
                      onClick={() => setCronExpression(preset.expr)}
                      className="px-2.5 py-1 text-xs rounded-lg bg-panel-header/60 hover:bg-panel-header border border-border text-fg-muted hover:text-fg transition cursor-pointer"
                    >
                      {preset.label} <code className="text-[10px] text-accent font-mono ml-1">({preset.expr})</code>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-fg mb-1">Fuso Orario (Timezone)</label>
                <input
                  type="text"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent font-mono"
                  placeholder="Europe/Rome"
                />
              </div>
            </div>
          )}

          {/* TAB: WORKFLOW STEP PIPELINE */}
          {activeTab === 'workflow' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-fg-muted">
                  Trascina o sposta gli step nell'ordine desiderato. Le variabili prodotte sono accessibili tramite <code>{'{{steps.<step_id>.output.text}}'}</code>.
                </span>
                <button
                  type="button"
                  onClick={handleAddStep}
                  className="px-3 py-1.5 bg-accent/15 hover:bg-accent/25 text-accent border border-accent/30 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer"
                >
                  <Plus size={13} /> Aggiungi Step
                </button>
              </div>

              <div className="space-y-3">
                {steps.map((step, idx) => (
                  <div
                    key={step.step_id || idx}
                    className="p-4 bg-panel-header/20 border border-border/70 rounded-xl space-y-3"
                  >
                    <div className="flex items-center justify-between gap-2 border-b border-border/50 pb-2">
                      <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-accent/15 text-accent text-[11px] font-bold flex items-center justify-center">
                          {idx + 1}
                        </span>
                        <input
                          type="text"
                          value={step.name}
                          onChange={(e) => handleUpdateStep(idx, { name: e.target.value })}
                          className="font-semibold text-xs text-fg bg-transparent border-b border-dashed border-border hover:border-accent focus:border-accent focus:outline-none px-1 py-0.5"
                          placeholder="Nome dello step"
                        />
                        <span className="text-[10px] font-mono text-fg-muted bg-panel px-1.5 py-0.5 rounded border border-border">
                          {step.step_id}
                        </span>
                      </div>

                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => handleMoveStep(idx, 'up')}
                          disabled={idx === 0}
                          className="p-1 text-fg-muted hover:text-fg disabled:opacity-30 rounded hover:bg-panel"
                          title="Sposta in alto"
                        >
                          <ChevronUp size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleMoveStep(idx, 'down')}
                          disabled={idx === steps.length - 1}
                          className="p-1 text-fg-muted hover:text-fg disabled:opacity-30 rounded hover:bg-panel"
                          title="Sposta in basso"
                        >
                          <ChevronDown size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRemoveStep(idx)}
                          className="p-1 text-fg-muted hover:text-rose-400 rounded hover:bg-panel ml-1"
                          title="Elimina step"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                      <div>
                        <label className="block text-[11px] font-medium text-fg-muted mb-1">Tipologia Step</label>
                        <select
                          value={step.type}
                          onChange={(e) => handleUpdateStep(idx, { type: e.target.value as any })}
                          className="w-full bg-panel border border-border rounded-lg px-2.5 py-1.5 text-xs text-fg focus:outline-none focus:border-accent"
                        >
                          <option value="deterministic_action">Azione Deterministica (Tool Diretto)</option>
                          <option value="agentic_task">Task Agentico (Ragionamento LLM)</option>
                          <option value="approval_gate">Approval Gate (Blocco con conferma umana)</option>
                        </select>
                      </div>

                      {step.type === 'deterministic_action' && (
                        <div>
                          <label className="block text-[11px] font-medium text-fg-muted mb-1">Tool da Eseguire</label>
                          <select
                            value={step.action_or_tool || ''}
                            onChange={(e) => handleUpdateStep(idx, { action_or_tool: e.target.value })}
                            className="w-full bg-panel border border-border rounded-lg px-2.5 py-1.5 text-xs text-fg font-mono focus:outline-none focus:border-accent"
                          >
                            <option value="web_search">web_search (Ricerca Web & Fetch)</option>
                            <option value="save_artifact">save_artifact (Salvataggio Report Markdown)</option>
                            <option value="email_fetch_unread">email_fetch_unread (Lettura Email)</option>
                            <option value="email_create_draft">email_create_draft (Bozza Email - No auto send)</option>
                            <option value="exec_lxc_command">exec_lxc_command (Comando Shell LXC)</option>
                            <option value="http_get">http_get (Chiamata HTTP REST)</option>
                          </select>
                        </div>
                      )}
                    </div>

                    {step.type === 'agentic_task' ? (
                      <div>
                        <label className="block text-[11px] font-medium text-fg-muted mb-1">
                          Prompt Template per LLM
                        </label>
                        <textarea
                          value={step.prompt_template || ''}
                          onChange={(e) => handleUpdateStep(idx, { prompt_template: e.target.value })}
                          rows={3}
                          className="w-full bg-panel border border-border rounded-lg p-2.5 text-xs font-mono text-fg focus:outline-none focus:border-accent"
                          placeholder="Analizza i risultati: {{steps.step_1_search.output.text}} e genera un report strutturato."
                        />
                        <p className="text-[10px] text-fg-muted mt-1">
                          Usa <code>{'{{steps.<step_id>.output.text}}'}</code> per passare i dati elaborati dagli step precedenti.
                        </p>
                      </div>
                    ) : (
                      <div>
                        <label className="block text-[11px] font-medium text-fg-muted mb-1">
                          Parametri Tool (JSON)
                        </label>
                        <textarea
                          value={JSON.stringify(step.parameters || {}, null, 2)}
                          onChange={(e) => {
                            try {
                              const parsed = JSON.parse(e.target.value);
                              handleUpdateStep(idx, { parameters: parsed });
                            } catch {
                              // keep raw in field until valid
                            }
                          }}
                          rows={2}
                          className="w-full bg-panel border border-border rounded-lg p-2.5 text-xs font-mono text-fg focus:outline-none focus:border-accent"
                          placeholder='{"query": "trending github repositories"}'
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB: BUDGET & GUARDRAIL */}
          {activeTab === 'budget' && (
            <div className="space-y-4">
              <p className="text-xs text-fg-muted">
                Configura i vincoli di sicurezza e il tetto massimo di risorse consumabili per singola esecuzione.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Timeout Globale Run (Secondi)</label>
                  <input
                    type="number"
                    value={maxDuration}
                    onChange={(e) => setMaxDuration(Number(e.target.value))}
                    min={10}
                    max={3600}
                    className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Tetto Massimo Token</label>
                  <input
                    type="number"
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(Number(e.target.value))}
                    min={1000}
                    max={500000}
                    className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Max Chiamate LLM</label>
                  <input
                    type="number"
                    value={maxLlmCalls}
                    onChange={(e) => setMaxLlmCalls(Number(e.target.value))}
                    min={1}
                    max={50}
                    className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Max Invocazioni Tool</label>
                  <input
                    type="number"
                    value={maxToolCalls}
                    onChange={(e) => setMaxToolCalls(Number(e.target.value))}
                    min={1}
                    max={100}
                    className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-fg mb-1">Max Retry per Step Fallito</label>
                  <input
                    type="number"
                    value={maxRetries}
                    onChange={(e) => setMaxRetries(Number(e.target.value))}
                    min={0}
                    max={5}
                    className="w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent"
                  />
                </div>
              </div>
            </div>
          )}

          {/* TAB: JSON RAW */}
          {activeTab === 'json' && (
            <div className="space-y-2">
              <p className="text-xs text-fg-muted">
                Modifica direttamente la specifica completa dell'automazione in formato JSON.
              </p>
              {jsonError && (
                <div className="p-2.5 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
                  {jsonError}
                </div>
              )}
              <textarea
                value={rawJson}
                onChange={(e) => {
                  setRawJson(e.target.value);
                  try {
                    JSON.parse(e.target.value);
                    setJsonError(null);
                  } catch (err: any) {
                    setJsonError(`Errore sintassi JSON: ${err.message}`);
                  }
                }}
                rows={16}
                className="w-full bg-panel border border-border rounded-xl p-3 font-mono text-xs text-fg focus:outline-none focus:border-accent"
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-border flex items-center justify-end gap-2.5 bg-panel-header/40 shrink-0">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-xs font-medium text-fg-muted hover:text-fg hover:bg-panel rounded-xl transition cursor-pointer"
          >
            Annulla
          </button>

          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 px-5 py-2 rounded-xl bg-accent hover:bg-accent/90 text-accent-contrast text-xs font-semibold shadow-md transition cursor-pointer disabled:opacity-50"
          >
            <Save size={14} />
            <span>{saving ? 'Salvataggio...' : 'Salva Modifiche'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
