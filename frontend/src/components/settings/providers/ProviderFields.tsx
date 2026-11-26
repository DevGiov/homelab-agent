import React, { useId } from 'react';
import { RotateCcw } from 'lucide-react';
import type { ProviderField, ProviderKind, ProviderOrigin, ProviderSecret } from '../../../api/providers';
import { PROVIDER_KINDS, SOURCE_LABELS, toFormValue, type FieldDef, type SecretDef } from '../../../utils/providerKinds';
import { inputClass, labelClass, secretStatus } from './providerStyles';

interface FieldsProps {
  kind: ProviderKind;
  origin: ProviderOrigin;
  /** I campi del provider con la loro origine; vuoto per un provider che si sta creando. */
  fields: Record<string, ProviderField>;
  /** Valori cambiati e non ancora salvati, nel formato del modulo. */
  edits: Record<string, string | boolean>;
  onEdit: (key: string, value: string | boolean) => void;
  /** Riporta un campo al `.env`: manda `null`. */
  onResetField: (key: string) => void;
  disabled?: boolean;
}

/** I campi del tipo di provider, ognuno con l'origine del suo valore e il pulsante per tornare al `.env`. */
export const ProviderFields: React.FC<FieldsProps> = ({ kind, origin, fields, edits, onEdit, onResetField, disabled }) => {
  const baseId = useId();
  return (
    <div className="stack-y-2.5">
      {PROVIDER_KINDS[kind].fields.map((def) => (
        <Field
          key={def.key}
          id={`${baseId}-${def.key}`}
          def={def}
          origin={origin}
          field={fields[def.key]}
          value={edits[def.key] ?? toFormValue(def, fields[def.key]?.value)}
          onEdit={(v) => onEdit(def.key, v)}
          onReset={() => onResetField(def.key)}
          disabled={disabled}
        />
      ))}
    </div>
  );
};

interface FieldProps {
  id: string;
  def: FieldDef;
  origin: ProviderOrigin;
  field: ProviderField | undefined;
  value: string | boolean;
  onEdit: (value: string | boolean) => void;
  onReset: () => void;
  disabled?: boolean;
}

const Field: React.FC<FieldProps> = ({ id, def, origin, field, value, onEdit, onReset, disabled }) => {
  const source = field?.source ?? 'default';
  const canReset = origin === 'env' && source === 'ui';
  const hintId = `${id}-hint`;
  return (
    <div className="stack-y-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {def.type === 'bool' ? (
          <label htmlFor={id} className="flex items-center gap-1.5 text-xs font-medium text-fg-muted cursor-pointer">
            <input
              id={id}
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => onEdit(e.target.checked)}
              disabled={disabled}
              aria-describedby={def.hint ? hintId : undefined}
              className="accent-accent"
            />
            {def.label}
          </label>
        ) : (
          <label htmlFor={id} className={labelClass}>
            {def.label}
            {def.required && <span className="text-rose-400"> *</span>}
          </label>
        )}
        <span className="text-xs text-fg-muted" data-testid={`origin-${def.key}`}>
          ({SOURCE_LABELS[source]})
        </span>
        {canReset && (
          <button
            type="button"
            onClick={onReset}
            disabled={disabled}
            aria-label={`Riporta «${def.label}» al .env`}
            title="Toglie il valore della UI: il campo torna a quello del .env"
            className="flex items-center gap-1 px-1.5 py-0.5 rounded-md text-xs text-accent-text hover:bg-accent/10 cursor-pointer disabled:opacity-40"
          >
            <RotateCcw size={11} aria-hidden="true" />
            torna al .env
          </button>
        )}
      </div>
      {def.type === 'list' ? (
        <textarea
          id={id}
          value={String(value)}
          onChange={(e) => onEdit(e.target.value)}
          disabled={disabled}
          rows={3}
          aria-describedby={def.hint ? hintId : undefined}
          className={`${inputClass} font-mono resize-y`}
        />
      ) : def.type === 'text' ? (
        <input
          id={id}
          type="text"
          value={String(value)}
          onChange={(e) => onEdit(e.target.value)}
          disabled={disabled}
          placeholder={def.placeholder}
          aria-describedby={def.hint ? hintId : undefined}
          className={`${inputClass} font-mono`}
        />
      ) : null}
      {def.hint && (
        <p id={hintId} className="text-xs text-fg-muted">
          {def.hint}
        </p>
      )}
    </div>
  );
};

interface SecretsProps {
  kind: ProviderKind;
  /** Stato di ogni credenziale; vuoto per un provider che si sta creando. */
  secrets: Record<string, ProviderSecret>;
  unreadable?: boolean;
  canStoreSecrets: boolean;
  /** Valori digitati e non ancora salvati: restano solo qui, mai nei dati dell'API. */
  typed: Record<string, string>;
  onType: (key: string, value: string) => void;
  /** Toglie la credenziale salvata dalla UI: manda `null`. */
  onRemove: (key: string) => void;
  disabled?: boolean;
}

/** Credenziali in sola scrittura: lo stato a parole, un campo per scrivere il valore nuovo, mai il valore salvato. */
export const ProviderSecrets: React.FC<SecretsProps> = ({ kind, secrets, unreadable, canStoreSecrets, typed, onType, onRemove, disabled }) => {
  const baseId = useId();
  const defs = PROVIDER_KINDS[kind].secrets;
  if (defs.length === 0) return null;
  return (
    <div className="stack-y-2.5" role="group" aria-label="Credenziali">
      <h4 className="text-xs font-semibold text-fg">Credenziali</h4>
      {unreadable && (
        <p role="alert" className="text-xs text-rose-300">
          Credenziale illeggibile, inseriscila di nuovo.
        </p>
      )}
      {!canStoreSecrets && (
        <p className="text-xs text-amber-300" id={`${baseId}-reason`}>
          Credenziali non modificabili: imposta API_SECRET_KEY nel .env.
        </p>
      )}
      {defs.map((def) => (
        <SecretRow
          key={def.key}
          id={`${baseId}-${def.key}`}
          def={def}
          secret={secrets[def.key]}
          value={typed[def.key] ?? ''}
          onType={(v) => onType(def.key, v)}
          onRemove={() => onRemove(def.key)}
          storable={canStoreSecrets}
          reasonId={`${baseId}-reason`}
          disabled={disabled}
        />
      ))}
    </div>
  );
};

interface SecretRowProps {
  id: string;
  def: SecretDef;
  secret: ProviderSecret | undefined;
  value: string;
  onType: (value: string) => void;
  onRemove: () => void;
  storable: boolean;
  reasonId: string;
  disabled?: boolean;
}

const SecretRow: React.FC<SecretRowProps> = ({ id, def, secret, value, onType, onRemove, storable, reasonId, disabled }) => (
  <div className="stack-y-1">
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <label htmlFor={id} className={labelClass}>
        {def.label}
        {def.required && <span className="text-rose-400"> *</span>}
      </label>
      <span className="text-xs text-fg-muted" data-testid={`secret-${def.key}`}>
        {secretStatus(secret)}
      </span>
      {secret?.source === 'ui' && (
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`Togli la credenziale «${def.label}» salvata dalla UI`}
          className="px-1.5 py-0.5 rounded-md text-xs text-accent-text hover:bg-accent/10 cursor-pointer disabled:opacity-40"
        >
          togli
        </button>
      )}
    </div>
    <input
      id={id}
      type="password"
      autoComplete="new-password"
      value={value}
      onChange={(e) => onType(e.target.value)}
      disabled={disabled || !storable}
      aria-describedby={storable ? undefined : reasonId}
      placeholder={storable ? 'Scrivi il nuovo valore (sola scrittura)' : 'imposta API_SECRET_KEY nel .env'}
      title={storable ? undefined : 'imposta API_SECRET_KEY nel .env'}
      className={`${inputClass} font-mono`}
    />
  </div>
);
