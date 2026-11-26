// I tipi di provider (docs/providers/PROVIDERS_DESIGN.md, 5.8.2): i campi e le credenziali di ognuno, con i testi della UI.
import type { FieldSource, FieldValue, ProviderKind } from '../api/providers';

export type FieldType = 'text' | 'bool' | 'list';

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  placeholder?: string;
  hint?: string;
}

export interface SecretDef {
  key: string;
  label: string;
  required?: boolean;
}

export interface KindDef {
  label: string;
  fields: FieldDef[];
  secrets: SecretDef[];
  /** Il campo che dice dove va il provider: l'indirizzo, o la regione per Bedrock. */
  addressField: string;
}

const BASE_URL: FieldDef = { key: 'base_url', label: 'Indirizzo (base URL)', type: 'text', required: true, placeholder: 'http://host:porta/v1' };
const DEFAULT_MODEL: FieldDef = { key: 'default_model', label: 'Modello predefinito', type: 'text' };
const MODELS: FieldDef = { key: 'models', label: 'Modelli', type: 'list', required: true, hint: 'Uno per riga.' };

export const PROVIDER_KINDS: Record<ProviderKind, KindDef> = {
  openai_compat: {
    label: 'Motore locale compatibile OpenAI',
    fields: [
      BASE_URL,
      DEFAULT_MODEL,
      { key: 'llama_cpp', label: 'Motore llama.cpp', type: 'bool', hint: 'Progresso e caricamento dei modelli, watchdog, campi del ragionamento.' },
    ],
    secrets: [{ key: 'api_key', label: 'Chiave API (facoltativa)' }],
    addressField: 'base_url',
  },
  ollama: { label: 'Ollama', fields: [BASE_URL, DEFAULT_MODEL], secrets: [], addressField: 'base_url' },
  bedrock: {
    label: 'AWS Bedrock',
    fields: [{ key: 'region', label: 'Regione AWS', type: 'text', required: true, placeholder: 'us-east-1' }, MODELS],
    secrets: [
      { key: 'api_key', label: 'Chiave API di Bedrock' },
      { key: 'access_key_id', label: 'ID della chiave di accesso AWS' },
      { key: 'secret_access_key', label: 'Segreto della chiave di accesso AWS' },
      { key: 'session_token', label: 'Token di sessione AWS' },
    ],
    addressField: 'region',
  },
  openai_cloud: {
    label: 'Servizio cloud compatibile OpenAI',
    fields: [BASE_URL, MODELS],
    secrets: [{ key: 'api_key', label: 'Chiave API', required: true }],
    addressField: 'base_url',
  },
};

export const KIND_ORDER: ProviderKind[] = ['openai_compat', 'ollama', 'bedrock', 'openai_cloud'];

export const SOURCE_LABELS: Record<FieldSource, string> = { env: 'da .env', ui: 'dalla UI', default: 'predefinito' };

/** Nome del campo per un campo obbligatorio mancante (`missing` dell'API). */
export function fieldLabel(kind: ProviderKind, key: string): string {
  const def = PROVIDER_KINDS[kind]?.fields.find((f) => f.key === key) ?? PROVIDER_KINDS[kind]?.secrets.find((s) => s.key === key);
  return def?.label ?? key;
}

/** Il valore di un campo come lo mostra il modulo: testo, booleano, o la lista come testo a righe. */
export function toFormValue(def: FieldDef, value: FieldValue | undefined): string | boolean {
  if (def.type === 'bool') return Boolean(value);
  if (def.type === 'list') return Array.isArray(value) ? value.join('\n') : '';
  return value == null ? '' : String(value);
}

/** Dal valore del modulo a quello dell'API. */
export function fromFormValue(def: FieldDef, value: string | boolean): FieldValue {
  if (def.type === 'list') {
    return String(value)
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  }
  return def.type === 'bool' ? Boolean(value) : String(value).trim();
}

/** Nome valido di un provider: minuscole, cifre e `-`; `total` è riservato al tetto complessivo. */
export const PROVIDER_NAME = /^[a-z0-9][a-z0-9-]*$/;

/** Una copia dell'oggetto senza la chiave. */
export function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([k]) => k !== key));
}
