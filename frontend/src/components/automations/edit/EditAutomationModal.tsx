import React, { useState } from 'react';
import { AlertCircle, Code2, Layers, Save, Settings, Shield, Sliders, X, type LucideIcon } from 'lucide-react';
import { updateAutomation } from '../../../api/automations';
import type { Notify } from '../../../hooks/useFeedback';
import { buildAutomation, formFromAutomation, stepsFromAutomation } from '../../../utils/automationForm';
import { formatApiError } from '../../../utils/error';
import { BudgetFields, GeneralFields } from './AutomationFields';
import { WorkflowStepsEditor } from './WorkflowStepsEditor';

type Tab = 'general' | 'workflow' | 'budget' | 'json';

interface EditAutomationModalProps {
  automation: any;
  onClose: () => void;
  onSuccess: () => void;
  onFeedback: Notify;
}

/** Modifica di definizione, step e budget di un'automazione; la scheda JSON permette di modificare la specifica intera. */
export const EditAutomationModal: React.FC<EditAutomationModalProps> = ({ automation, onClose, onSuccess, onFeedback }) => {
  const [activeTab, setActiveTab] = useState<Tab>('general');
  const [form, setForm] = useState(() => formFromAutomation(automation));
  const [steps, setSteps] = useState(() => stepsFromAutomation(automation));
  const [rawJson, setRawJson] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const changeTab = (tab: Tab) => {
    // La scheda JSON parte sempre dallo stato corrente del form
    if (tab === 'json') {
      setRawJson(JSON.stringify(buildAutomation(automation, form, steps), null, 2));
      setJsonError(null);
    }
    setActiveTab(tab);
  };

  const editJson = (text: string) => {
    setRawJson(text);
    try {
      JSON.parse(text);
      setJsonError(null);
    } catch (err) {
      setJsonError(`Errore sintassi JSON: ${(err as Error).message}`);
    }
  };

  const payload = () => {
    if (activeTab === 'json') {
      try {
        return JSON.parse(rawJson);
      } catch (err) {
        setJsonError(`Errore sintassi JSON: ${(err as Error).message}`);
        return null;
      }
    }
    const invalid = !form.name.trim()
      ? "Il nome dell'automazione è obbligatorio."
      : steps.length === 0
      ? 'Il workflow deve contenere almeno uno step.'
      : null;
    if (invalid) {
      setErrorMsg(invalid);
      return null;
    }
    return buildAutomation(automation, form, steps);
  };

  const save = async () => {
    setErrorMsg(null);
    const body = payload();
    if (!body) return;
    setSaving(true);
    try {
      const res = await updateAutomation(automation.id, body);
      onFeedback('success', `Automazione '${res.name || automation.name}' aggiornata con successo (v${res.version || body.version})!`);
      onSuccess();
      onClose();
    } catch (err) {
      setErrorMsg(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  const tabs: Array<{ id: Tab; label: string; icon: LucideIcon }> = [
    { id: 'general', label: 'Generale', icon: Settings },
    { id: 'workflow', label: `Pipeline Step (${steps.length})`, icon: Layers },
    { id: 'budget', label: 'Budget & Guardrail', icon: Shield },
    { id: 'json', label: 'Spec JSON Raw', icon: Code2 },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto animate-fade-in">
      <div className="bg-panel border border-border rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden my-auto">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-panel-header/40 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-accent/10 border border-accent/20 rounded-xl text-accent">
              <Sliders size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-fg">Modifica Automazione</h3>
                <span className="font-mono text-xs px-2 py-0.5 bg-panel border border-border rounded-md text-fg-muted">{automation.id}</span>
                <span className="text-[11px] font-semibold px-2 py-0.5 bg-accent/15 text-accent rounded-full border border-accent/30">
                  v{automation.version || 1}
                </span>
              </div>
              <p className="text-xs text-fg-muted mt-0.5">Modifica descrizione, step della pipeline e budget per aggiornare il comportamento del workflow.</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 pt-2 border-b border-border flex items-center gap-2 bg-panel-header/20 overflow-x-auto shrink-0">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => changeTab(id)}
              className={`px-3 py-2 text-xs font-medium border-b-2 flex items-center gap-1.5 transition cursor-pointer ${
                activeTab === id ? 'border-accent text-accent font-semibold' : 'border-transparent text-fg-muted hover:text-fg'
              }`}
            >
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>

        <div className="p-6 overflow-y-auto flex-1 space-y-5">
          {errorMsg && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300 flex items-start gap-2">
              <AlertCircle size={15} className="shrink-0 mt-0.5 text-rose-400" />
              <span>{errorMsg}</span>
            </div>
          )}

          {activeTab === 'general' && <GeneralFields form={form} onChange={(patch) => setForm((f) => ({ ...f, ...patch }))} />}
          {activeTab === 'workflow' && <WorkflowStepsEditor steps={steps} onChange={setSteps} onError={setErrorMsg} />}
          {activeTab === 'budget' && <BudgetFields form={form} onChange={(patch) => setForm((f) => ({ ...f, ...patch }))} />}
          {activeTab === 'json' && (
            <div className="space-y-2">
              <p className="text-xs text-fg-muted">
                Modifica direttamente la specifica completa dell'automazione in formato JSON. Salvando da qui vale il JSON, non i campi delle
                altre schede.
              </p>
              {jsonError && <div className="p-2.5 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">{jsonError}</div>}
              <textarea
                value={rawJson}
                onChange={(e) => editJson(e.target.value)}
                rows={16}
                className="w-full bg-panel border border-border rounded-xl p-3 font-mono text-xs text-fg focus:outline-none focus:border-accent"
              />
            </div>
          )}
        </div>

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
            onClick={save}
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
