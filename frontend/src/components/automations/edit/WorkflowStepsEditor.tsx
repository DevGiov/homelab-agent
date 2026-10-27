import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react';
import { changeStepType, newStep, type StepDef } from '../../../utils/automationForm';

const STEP_TYPES: Array<[string, string]> = [
  ['deterministic_action', 'Azione Deterministica (Tool Diretto)'],
  ['agentic_task', 'Task Agentico (Ragionamento LLM)'],
  ['approval_gate', 'Approval Gate (Blocco con conferma umana)'],
];

const TOOLS: Array<[string, string]> = [
  ['web_search', 'web_search (Ricerca Web & Fetch)'],
  ['save_artifact', 'save_artifact (Salvataggio Report Markdown)'],
  ['email_fetch_unread', 'email_fetch_unread (Lettura Email)'],
  ['email_create_draft', 'email_create_draft (Bozza Email - No auto send)'],
  ['exec_lxc_command', 'exec_lxc_command (Comando Shell LXC)'],
  ['http_get', 'http_get (Chiamata HTTP REST)'],
];

/** Opzioni note più il valore corrente se non è tra queste (il backend supporta anche altri tipi e tool). */
const withCurrent = (options: Array<[string, string]>, current?: string | null) =>
  current && !options.some(([value]) => value === current) ? [...options, [current, current] as [string, string]] : options;

const fieldClass = 'w-full bg-panel border border-border rounded-lg px-2.5 py-1.5 text-xs text-fg focus:outline-none focus:border-accent';

/** Parametri del tool come JSON libero: il testo si modifica liberamente e diventa effettivo solo quando è valido. */
const ParametersField: React.FC<{ value: Record<string, any>; onChange: (value: Record<string, any>) => void }> = ({ value, onChange }) => {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState<string | null>(null);

  const edit = (next: string) => {
    setText(next);
    try {
      const parsed = JSON.parse(next || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('serve un oggetto JSON');
      setError(null);
      onChange(parsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div>
      <label className="block text-[11px] font-medium text-fg-muted mb-1">Parametri Tool (JSON)</label>
      <textarea
        value={text}
        onChange={(e) => edit(e.target.value)}
        rows={2}
        className={`${fieldClass} p-2.5 font-mono ${error ? 'border-rose-500/60' : ''}`}
        placeholder='{"query": "trending github repositories"}'
      />
      {error && <p className="text-[10px] text-rose-400 mt-1">JSON non valido, modifica non applicata: {error}</p>}
    </div>
  );
};

interface WorkflowStepsEditorProps {
  steps: StepDef[];
  onChange: (steps: StepDef[]) => void;
  onError: (message: string) => void;
}

export const WorkflowStepsEditor: React.FC<WorkflowStepsEditorProps> = ({ steps, onChange, onError }) => {
  const update = (index: number, step: StepDef) => onChange(steps.map((s, i) => (i === index ? step : s)));

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const remove = (index: number) => {
    if (steps.length <= 1) return onError('Il workflow deve contenere almeno uno step.');
    onChange(steps.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-fg-muted">
          Riordina gli step con le frecce. Le variabili prodotte sono accessibili tramite <code>{'{{steps.<step_id>.output.text}}'}</code>.
        </span>
        <button
          type="button"
          onClick={() => {
            // Id univoco anche dopo eliminazioni: si salta ogni posizione già usata
            let position = steps.length + 1;
            while (steps.some((s) => s.step_id === newStep(position).step_id)) position += 1;
            onChange([...steps, newStep(position)]);
          }}
          className="px-3 py-1.5 bg-accent/15 hover:bg-accent/25 text-accent border border-accent/30 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer shrink-0"
        >
          <Plus size={13} /> Aggiungi Step
        </button>
      </div>

      <div className="space-y-3">
        {steps.map((step, idx) => (
          <div key={step.step_id} className="p-4 bg-panel-header/20 border border-border/70 rounded-xl space-y-3">
            <div className="flex items-center justify-between gap-2 border-b border-border/50 pb-2">
              <div className="flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-accent/15 text-accent text-[11px] font-bold flex items-center justify-center">{idx + 1}</span>
                <input
                  type="text"
                  value={step.name}
                  onChange={(e) => update(idx, { ...step, name: e.target.value })}
                  className="font-semibold text-xs text-fg bg-transparent border-b border-dashed border-border hover:border-accent focus:border-accent focus:outline-none px-1 py-0.5"
                  placeholder="Nome dello step"
                />
                <span className="text-[10px] font-mono text-fg-muted bg-panel px-1.5 py-0.5 rounded border border-border">{step.step_id}</span>
              </div>

              <div className="flex items-center gap-1">
                <button type="button" onClick={() => move(idx, -1)} disabled={idx === 0} className="p-1 text-fg-muted hover:text-fg disabled:opacity-30 rounded hover:bg-panel" title="Sposta in alto">
                  <ChevronUp size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => move(idx, 1)}
                  disabled={idx === steps.length - 1}
                  className="p-1 text-fg-muted hover:text-fg disabled:opacity-30 rounded hover:bg-panel"
                  title="Sposta in basso"
                >
                  <ChevronDown size={13} />
                </button>
                <button type="button" onClick={() => remove(idx)} className="p-1 text-fg-muted hover:text-rose-400 rounded hover:bg-panel ml-1" title="Elimina step">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div>
                <label className="block text-[11px] font-medium text-fg-muted mb-1">Tipologia Step</label>
                <select value={step.type} onChange={(e) => update(idx, changeStepType(step, e.target.value))} className={fieldClass}>
                  {withCurrent(STEP_TYPES, step.type).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              {step.type === 'deterministic_action' && (
                <div>
                  <label className="block text-[11px] font-medium text-fg-muted mb-1">Tool da Eseguire</label>
                  <select
                    value={step.action_or_tool || ''}
                    onChange={(e) => update(idx, { ...step, action_or_tool: e.target.value })}
                    className={`${fieldClass} font-mono`}
                  >
                    {withCurrent(TOOLS, step.action_or_tool).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {step.type === 'agentic_task' ? (
              <div>
                <label className="block text-[11px] font-medium text-fg-muted mb-1">Prompt Template per LLM</label>
                <textarea
                  value={step.prompt_template || ''}
                  onChange={(e) => update(idx, { ...step, prompt_template: e.target.value })}
                  rows={3}
                  className={`${fieldClass} p-2.5 font-mono`}
                  placeholder="Analizza i risultati: {{steps.step_1_search.output.text}} e genera un report strutturato."
                />
                <p className="text-[10px] text-fg-muted mt-1">
                  Usa <code>{'{{steps.<step_id>.output.text}}'}</code> per passare i dati elaborati dagli step precedenti.
                </p>
              </div>
            ) : (
              <ParametersField value={step.parameters || {}} onChange={(parameters) => update(idx, { ...step, parameters })} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
