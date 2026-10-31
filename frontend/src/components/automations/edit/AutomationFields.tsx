import React from 'react';
import { useModelCatalog } from '../../../hooks/useModelCatalog';
import { type AutomationFormState, type Budget, LOADED_MODEL } from '../../../utils/automationForm';

const inputClass = 'w-full bg-panel border border-border rounded-xl px-3 py-2 text-xs text-fg focus:outline-none focus:border-accent';
const labelClass = 'block text-xs font-semibold text-fg mb-1';

interface FieldsProps {
  form: AutomationFormState;
  onChange: (patch: Partial<AutomationFormState>) => void;
}

/** Modello degli step agentici: default, quello caricato quando lo step parte, o un modello preciso. */
const ModelField: React.FC<FieldsProps> = ({ form, onChange }) => {
  const { modelDetails } = useModelCatalog();
  const ids = modelDetails.map((m) => m.id);
  // Un modello salvato che il server non elenca più resta visibile e selezionato
  if (form.model && form.model !== LOADED_MODEL && !ids.includes(form.model)) ids.unshift(form.model);
  return (
    <div className="pt-2 border-t border-border/50">
      <label className={labelClass}>Modello LLM degli step agentici</label>
      <select value={form.model} onChange={(e) => onChange({ model: e.target.value })} className={`${inputClass} py-1.5`}>
        <option value="">Default del server</option>
        <option value={LOADED_MODEL}>Modello caricato al momento dell'esecuzione</option>
        {ids.map((id) => (
          <option key={id} value={id}>
            {id}
          </option>
        ))}
      </select>
      <p className="text-[11px] text-fg-muted mt-1">
        Con il modello caricato, ogni step usa quello presente in VRAM quando parte, senza far caricare altri modelli; se
        nessuno è caricato usa il default. Un modello preciso viene caricato se serve.
      </p>
    </div>
  );
};

export const GeneralFields: React.FC<FieldsProps> = ({ form, onChange }) => (
  <div className="space-y-4">
    <div>
      <label className={labelClass}>Nome Automazione</label>
      <input
        type="text"
        value={form.name}
        onChange={(e) => onChange({ name: e.target.value })}
        className={inputClass}
        placeholder="es. GitHub Trending Daily Report"
      />
    </div>

    <div>
      <label className={labelClass}>Descrizione</label>
      <textarea
        value={form.description}
        onChange={(e) => onChange({ description: e.target.value })}
        rows={3}
        className={`${inputClass} p-3`}
        placeholder="Spiega lo scopo del workflow, gli input attesi e l'output generato."
      />
    </div>

    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-border/50">
      <div>
        <label className={labelClass}>Stato Automazione</label>
        <div className="flex items-center gap-2 mt-1">
          <input
            type="checkbox"
            id="enable-auto-toggle"
            checked={form.enabled}
            onChange={(e) => onChange({ enabled: e.target.checked })}
            className="w-4 h-4 rounded border-border text-accent focus:ring-0"
          />
          <label htmlFor="enable-auto-toggle" className="text-xs text-fg cursor-pointer select-none">
            {form.enabled ? 'Abilitata (schedulazione e trigger attivi)' : 'Disabilitata (nessuna esecuzione automatica)'}
          </label>
        </div>
      </div>

      <div>
        <label className={labelClass}>Retention TTL (Giorni)</label>
        <input
          type="number"
          value={form.retentionDays}
          onChange={(e) => onChange({ retentionDays: e.target.value === '' ? '' : Number(e.target.value) })}
          min={1}
          max={365}
          className={`${inputClass} py-1.5`}
          placeholder="14 (default)"
        />
        <p className="text-[11px] text-fg-muted mt-1">Le run non protette con lucchetto verranno rimosse dopo questo intervallo dal cleanup notturno.</p>
      </div>
    </div>

    <ModelField form={form} onChange={onChange} />

    <p className="text-[11px] text-fg-muted pt-2 border-t border-border/50">
      Schedulazione cron e webhook si configurano dal pulsante con l'orologio sulla card dell'automazione.
    </p>
  </div>
);

const BUDGET_FIELDS: Array<{ key: keyof Budget; label: string; min: number; max: number }> = [
  { key: 'max_duration_seconds', label: 'Timeout Globale Run (Secondi)', min: 10, max: 3600 },
  { key: 'max_tokens', label: 'Tetto Massimo Token', min: 1000, max: 500000 },
  { key: 'max_llm_calls', label: 'Max Chiamate LLM', min: 1, max: 50 },
  { key: 'max_tool_calls', label: 'Max Invocazioni Tool', min: 1, max: 100 },
  { key: 'max_retries_per_step', label: 'Max Retry per Step Fallito', min: 0, max: 5 },
];

export const BudgetFields: React.FC<FieldsProps> = ({ form, onChange }) => (
  <div className="space-y-4">
    <p className="text-xs text-fg-muted">Configura i vincoli di sicurezza e il tetto massimo di risorse consumabili per singola esecuzione.</p>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {BUDGET_FIELDS.map(({ key, label, min, max }) => (
        <div key={key}>
          <label className={labelClass}>{label}</label>
          <input
            type="number"
            value={form.budget[key]}
            onChange={(e) => onChange({ budget: { ...form.budget, [key]: Number(e.target.value) } })}
            min={min}
            max={max}
            className={inputClass}
          />
        </div>
      ))}
    </div>
  </div>
);
