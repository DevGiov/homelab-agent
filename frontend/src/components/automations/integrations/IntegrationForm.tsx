import React, { useState } from 'react';
import { AlertCircle, CheckCircle, Lock, RefreshCw, Trash2 } from 'lucide-react';
import type { IntegrationTestResult, ServiceIntegration } from '../../../api/integrations';
import type { Integrations } from '../../../hooks/useIntegrations';
import type { FieldSpec, FieldValues, IntegrationSpec } from './specs';

const inputClass = 'w-full px-2.5 py-1.5 rounded-lg bg-bg border border-border text-fg focus:outline-none focus:border-accent text-xs font-mono';
const colSpan = { 1: 'col-span-1', 2: 'col-span-2', 3: 'col-span-3' };

/** Valori iniziali: configurazione salvata, segreti mascherati dal backend, altrimenti i default. */
function initialValues(spec: IntegrationSpec, integration?: ServiceIntegration): FieldValues {
  return Object.fromEntries(
    spec.fields.map((f) => {
      const saved = f.source === 'config' ? integration?.config?.[f.key] : integration?.secrets?.[f.key];
      return [f.key, saved ?? f.defaultValue ?? (f.kind === 'checkbox' ? false : '')];
    })
  );
}

function toPayload(spec: IntegrationSpec, values: FieldValues): Partial<ServiceIntegration> {
  const config: Record<string, unknown> = { ...spec.fixedConfig };
  const secrets: Record<string, unknown> = {};
  for (const field of spec.fields) {
    const raw = values[field.key];
    const value = field.kind === 'number' ? Number(raw) : typeof raw === 'string' ? raw.trim() : raw;
    if (field.source === 'config') config[field.key] = value;
    else if (value) secrets[field.key] = value; // segreto vuoto: il backend conserva quello salvato
  }
  return { id: spec.id, service_type: spec.serviceType, name: spec.name(values), config, secrets };
}

const Field: React.FC<{ field: FieldSpec; value: string | number | boolean; onChange: (v: string | number | boolean) => void }> = ({
  field,
  value,
  onChange,
}) => {
  if (field.kind === 'checkbox') {
    const id = `integration-${field.key}`;
    return (
      <div className="col-span-3 flex items-center gap-2 pt-1">
        <input
          type="checkbox"
          id={id}
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-border text-accent focus:ring-0 cursor-pointer"
        />
        <label htmlFor={id} className="text-fg-muted text-[11px] cursor-pointer">
          {field.label}
        </label>
      </div>
    );
  }
  return (
    <div className={`${colSpan[field.cols ?? 3]} space-y-1`}>
      <label className="text-fg-muted text-[11px] font-medium flex items-center justify-between">
        <span>{field.label}</span>
        {field.source === 'secrets' && (
          <span className="text-[10px] text-accent flex items-center gap-1">
            <Lock size={10} /> Cifrato AES
          </span>
        )}
      </label>
      <input
        type={field.kind}
        placeholder={field.placeholder}
        value={String(value)}
        onChange={(e) => onChange(field.kind === 'number' ? Number(e.target.value) : e.target.value)}
        required={field.required}
        className={inputClass}
      />
    </div>
  );
};

const TestResult: React.FC<{ result: IntegrationTestResult; labels: IntegrationSpec['testLabels'] }> = ({ result, labels }) => (
  <div
    className={`p-2.5 rounded-lg text-[11px] mt-2 border ${
      result.success ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800' : 'bg-rose-950/60 text-rose-300 border-rose-800'
    }`}
  >
    <p className="font-medium">{result.success ? labels.success : labels.failure}:</p>
    <p className="mt-0.5 text-[10.5px] opacity-90">{result.message || result.error}</p>
  </div>
);

interface IntegrationFormProps {
  spec: IntegrationSpec;
  integration?: ServiceIntegration;
  actions: Integrations;
}

/** Card di un servizio: stato, campi della specifica, test di connessione ed eliminazione. */
export const IntegrationForm: React.FC<IntegrationFormProps> = ({ spec, integration, actions }) => {
  const [values, setValues] = useState(() => initialValues(spec, integration));
  const [isSaving, setIsSaving] = useState(false);
  const isConnected = integration?.status === 'connected';
  const testResult = actions.testResults[spec.id];
  const Icon = spec.icon;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    await actions.save(toPayload(spec, values), `${spec.title}: configurazione salvata.`, `Errore salvataggio ${spec.title}`);
    setIsSaving(false);
  };

  return (
    <div className="p-5 rounded-2xl bg-panel border border-border flex flex-col justify-between space-y-4 shadow-sm">
      <div>
        <div className="flex items-center justify-between pb-3 border-b border-border/60">
          <div className="flex items-center gap-2.5">
            <div className={`w-8 h-8 rounded-lg border flex items-center justify-center ${spec.iconClass}`}>
              <Icon size={16} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-fg">{spec.title}</h3>
              <span className="text-[11px] text-fg-muted">{spec.subtitle}</span>
            </div>
          </div>
          {integration && (
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-medium border flex items-center gap-1 ${
                isConnected ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
              }`}
            >
              {isConnected ? <CheckCircle size={10} /> : <AlertCircle size={10} />}
              {isConnected ? spec.statusLabels.connected : spec.statusLabels.other}
            </span>
          )}
        </div>

        <form onSubmit={submit} className="mt-4 space-y-3 text-xs">
          <div className="grid grid-cols-3 gap-2">
            {spec.fields.map((field) => (
              <Field
                key={field.key}
                field={field}
                value={values[field.key]}
                onChange={(value) => setValues((prev) => ({ ...prev, [field.key]: value }))}
              />
            ))}
          </div>

          {testResult && <TestResult result={testResult} labels={spec.testLabels} />}

          <div className="pt-2 flex items-center justify-between gap-2 border-t border-border/50">
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={isSaving}
                className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition shadow-sm cursor-pointer"
              >
                {isSaving ? 'Salvataggio...' : spec.saveLabel}
              </button>
              {integration && (
                <button
                  type="button"
                  onClick={() => actions.test(spec.id)}
                  disabled={actions.testingId === spec.id}
                  className="px-3 py-1.5 bg-panel border border-border hover:border-accent/40 text-fg rounded-lg text-xs font-medium transition flex items-center gap-1.5 cursor-pointer"
                >
                  <RefreshCw size={12} className={actions.testingId === spec.id ? 'animate-spin text-accent' : ''} />
                  Testa Connessione
                </button>
              )}
            </div>
            {integration && (
              <button
                type="button"
                onClick={() => actions.remove(spec.id)}
                className="p-1.5 text-fg-muted hover:text-rose-400 rounded-lg transition"
                title={spec.deleteTitle}
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
};
