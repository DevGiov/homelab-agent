import React, { useId, useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { createProvider, type FieldValue, type ProviderKind } from '../../../api/providers';
import { providerErrorMessage } from '../../../utils/providerErrors';
import { fromFormValue, KIND_ORDER, PROVIDER_KINDS, PROVIDER_NAME } from '../../../utils/providerKinds';
import { ProviderFields, ProviderSecrets } from './ProviderFields';
import { inputClass, labelClass } from './providerStyles';

interface AddProviderFormProps {
  canStoreSecrets: boolean;
  onCreated: () => Promise<void>;
  onCancel: () => void;
}

/** Nuovo provider: nome stabile, tipo, nome visibile e i campi del tipo. Nasce con il livello «pubblici». */
export const AddProviderForm: React.FC<AddProviderFormProps> = ({ canStoreSecrets, onCreated, onCancel }) => {
  const id = useId();
  const [name, setName] = useState('');
  const [kind, setKind] = useState<ProviderKind>('openai_compat');
  const [displayName, setDisplayName] = useState('');
  const [edits, setEdits] = useState<Record<string, string | boolean>>({});
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameValid = PROVIDER_NAME.test(name);
  const nameInvalid = name !== '' && !nameValid;

  const changeKind = (next: ProviderKind) => {
    setKind(next);
    setEdits({});
    setTyped({});
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!nameValid) return;
    setSaving(true);
    setError(null);
    try {
      const fields = Object.fromEntries(
        PROVIDER_KINDS[kind].fields.filter((def) => def.key in edits).map((def) => [def.key, fromFormValue(def, edits[def.key])])
      ) as Record<string, FieldValue>;
      const secrets = Object.fromEntries(Object.entries(typed).filter(([, value]) => value !== ''));
      await createProvider({
        name,
        kind,
        ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
        ...(Object.keys(fields).length > 0 ? { fields } : {}),
        ...(Object.keys(secrets).length > 0 ? { secrets } : {}),
      });
      await onCreated();
      onCancel();
    } catch (err) {
      setError(providerErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} aria-label="Aggiungi provider" className="p-3 rounded-xl border border-accent/40 bg-accent/5 stack-y-3">
      <h3 className="text-xs font-semibold text-fg">Aggiungi provider</h3>
      {error && (
        <p role="alert" className="p-2 rounded-lg text-xs border bg-rose-950/40 border-rose-800/60 text-rose-300">
          {error}
        </p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="stack-y-1">
          <label htmlFor={`${id}-name`} className={labelClass}>
            Nome (minuscole, cifre e -) <span className="text-rose-400">*</span>
          </label>
          <input
            id={`${id}-name`}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={nameInvalid}
            aria-describedby={`${id}-name-hint`}
            placeholder="vllm-studio"
            className={`${inputClass} font-mono`}
          />
          <p id={`${id}-name-hint`} className={`text-xs ${nameInvalid ? 'text-rose-300' : 'text-fg-muted'}`}>
            {nameInvalid ? 'Nome non valido: usa solo minuscole, cifre e -.' : 'Identificativo stabile: non si cambia dopo.'}
          </p>
        </div>
        <div className="stack-y-1">
          <label htmlFor={`${id}-kind`} className={labelClass}>
            Tipo
          </label>
          <select id={`${id}-kind`} value={kind} onChange={(e) => changeKind(e.target.value as ProviderKind)} className={`${inputClass} cursor-pointer`}>
            {KIND_ORDER.map((k) => (
              <option key={k} value={k} className="bg-panel text-fg">
                {PROVIDER_KINDS[k].label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="stack-y-1">
        <label htmlFor={`${id}-display`} className={labelClass}>
          Nome visibile
        </label>
        <input id={`${id}-display`} type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} className={inputClass} />
      </div>

      <ProviderFields kind={kind} origin="ui" fields={{}} edits={edits} onEdit={(key, value) => setEdits((e) => ({ ...e, [key]: value }))} onResetField={() => {}} />
      <ProviderSecrets
        kind={kind}
        secrets={{}}
        canStoreSecrets={canStoreSecrets}
        typed={typed}
        onType={(key, value) => setTyped((t) => ({ ...t, [key]: value }))}
        onRemove={() => {}}
      />

      <div className="flex justify-end gap-1.5">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
          Annulla
        </button>
        <button
          type="submit"
          disabled={nameInvalid || name === '' || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-accent-contrast text-xs font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default"
        >
          {saving ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <Plus size={12} aria-hidden="true" />}
          Crea provider
        </button>
      </div>
    </form>
  );
};
