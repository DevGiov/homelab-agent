// Provider di modelli (backend: docs/providers/PROVIDERS_DESIGN.md, sezione 5.8.6): configurazione, catalogo, prezzi e tetti.
import { http } from './http';
import type { SensitivityLevel } from '../utils/sensitivity';

export type ProviderKind = 'openai_compat' | 'ollama' | 'bedrock' | 'openai_cloud';

/** `env`: definito dal `.env` (non si elimina); `ui`: aggiunto dalla UI. */
export type ProviderOrigin = 'env' | 'ui';

/** Da dove viene il valore di un campo. */
export type FieldSource = 'env' | 'ui' | 'default';

/** Valore di un campo del tipo: testo, sì/no o lista (i modelli di Bedrock). */
export type FieldValue = string | boolean | string[] | number | null;

export interface ProviderField {
  value: FieldValue;
  source: FieldSource;
}

/** Una credenziale non torna mai: solo se c'è e da dove viene. */
export interface ProviderSecret {
  set: boolean;
  source: 'env' | 'ui' | null;
}

export interface ProviderClearance {
  saved: SensitivityLevel;
  effective: SensitivityLevel;
  /** Indirizzo (o regione) per cui il livello è stato concesso. */
  granted_for: string | null;
  /** L'indirizzo è cambiato dopo la concessione: il livello effettivo è tornato `public`. */
  reset_by_address_change: boolean;
}

export interface ProviderConfig {
  name: string;
  display_name: string;
  kind: ProviderKind;
  origin: ProviderOrigin;
  enabled: boolean;
  /** Falso se manca un campo obbligatorio: allora non è nel catalogo. */
  configured: boolean;
  /** I campi obbligatori mancanti. */
  missing: string[];
  cloud: boolean;
  is_default: boolean;
  is_fallback: boolean;
  fields: Record<string, ProviderField>;
  secrets: Record<string, ProviderSecret>;
  /** La credenziale salvata non si legge più (`API_SECRET_KEY` cambiata). */
  secrets_unreadable: boolean;
  clearance: ProviderClearance;
  /** `null`: non provato. */
  healthy: boolean | null;
  error: string | null;
}

export interface ProvidersResponse {
  providers: ProviderConfig[];
  default_provider: string;
  fallback_provider: string;
  /** Falso senza `API_SECRET_KEY`: nessuna credenziale si può salvare dalla UI. */
  can_store_secrets: boolean;
}

export interface CreateProviderRequest {
  name: string;
  kind: ProviderKind;
  display_name?: string;
  fields?: Record<string, FieldValue>;
  secrets?: Record<string, string>;
}

/** `null` toglie il valore della UI: il campo (o la credenziale) torna al `.env`. */
export interface ProviderPatch {
  display_name?: string;
  enabled?: boolean;
  fields?: Record<string, FieldValue>;
  secrets?: Record<string, string | null>;
  /** Solo quando cambia l'indirizzo del provider di ripiego: il backend risponde 409 `confirm_required` senza. */
  confirm?: boolean;
}

export interface ProviderTestResult {
  ok: boolean;
  latency_ms: number | null;
  models_count: number | null;
  error: string | null;
}

export interface ProviderSettings {
  default_provider: string;
  fallback_provider: string;
}

export interface ModelDetail {
  id: string;
  is_vision: boolean;
  input_modalities: string[];
  status?: string;
  is_loaded?: boolean;
  is_loading?: boolean;
  load_progress?: number;
  available?: boolean;
  would_block?: boolean;
  availability_note?: string | null;
  memory_class?: string | null;
}

/** Un provider nel catalogo del selettore: solo i provider attivi e configurati. */
export interface CatalogProvider {
  name: string;
  display_name: string;
  kind: ProviderKind;
  cloud: boolean;
  /** Livello effettivo. */
  clearance: SensitivityLevel;
  /** `null`: non provato. */
  healthy: boolean | null;
  models: ModelDetail[];
}

/** La scelta di un modello è la coppia (provider, modello). */
export interface ModelRef {
  provider: string;
  model: string;
}

export interface ModelCatalogResponse {
  providers: CatalogProvider[];
  default: ModelRef | null;
}

const providerPath = (name: string) => `/providers/${encodeURIComponent(name)}`;

export function getProviders(): Promise<ProvidersResponse> {
  return http.get('/providers');
}

export function createProvider(req: CreateProviderRequest): Promise<ProviderConfig> {
  return http.post('/providers', req);
}

export function updateProvider(name: string, patch: ProviderPatch): Promise<ProviderConfig> {
  return http.patch(providerPath(name), patch);
}

export function deleteProvider(name: string): Promise<void> {
  return http.delete(providerPath(name));
}

/** Provider del `.env`: toglie tutte le modifiche fatte dalla UI. */
export function resetProvider(name: string): Promise<ProviderConfig> {
  return http.post(`${providerPath(name)}/reset`);
}

/** Alzare il livello senza `confirm: true` risponde 409 `confirm_required`. */
export function setProviderClearance(name: string, level: SensitivityLevel, confirm: boolean): Promise<ProviderConfig> {
  return http.put(`${providerPath(name)}/clearance`, { level, confirm });
}

/** Prova la connessione con la configurazione salvata o, con `draft`, con quella inviata senza salvarla. */
export function testProvider(name: string, draft?: ProviderPatch): Promise<ProviderTestResult> {
  return http.post(`${providerPath(name)}/test`, draft);
}

export function setProviderSettings(settings: Partial<ProviderSettings>): Promise<ProviderSettings> {
  return http.put('/providers/settings', settings);
}

export function getModelCatalog(): Promise<ModelCatalogResponse> {
  return http.get('/models');
}

export function loadModel(provider: string, model: string): Promise<unknown> {
  return http.post(`${providerPath(provider)}/models/load`, { model });
}

// Costi (P1): prezzi dei modelli, tetti mensili e spesa del mese

export interface ModelPrice {
  provider: string;
  model: string;
  input_per_mtok: number;
  cached_per_mtok: number;
  output_per_mtok: number;
  updated_at?: string;
}

export type PriceInput = Pick<ModelPrice, 'input_per_mtok' | 'cached_per_mtok' | 'output_per_mtok'>;

/** Il tetto complessivo ha come scope questo nome, che nessun provider può avere. */
export const TOTAL_SCOPE = 'total';

export interface ProviderCosts {
  prices: ModelPrice[];
  /** Tetto mensile in dollari per scope (nome del provider o `total`); assente = nessun limite. */
  ceilings: Record<string, number>;
  spend: { month: string; by_provider: Record<string, number>; total: number };
  /** Per ogni scope con un tetto: la spesa del mese lo ha raggiunto? */
  reached: Record<string, boolean>;
}

export function getProviderCosts(): Promise<ProviderCosts> {
  return http.get('/providers/costs');
}

const pricePath = (provider: string, model: string) => `${providerPath(provider)}/models/${encodeURIComponent(model)}/price`;

export function setModelPrice(provider: string, model: string, price: PriceInput): Promise<ModelPrice> {
  return http.put(pricePath(provider, model), price);
}

export function deleteModelPrice(provider: string, model: string): Promise<{ provider: string; model: string; deleted: boolean }> {
  return http.delete(pricePath(provider, model));
}

export function setSpendCeiling(scope: string, monthlyUsd: number): Promise<{ scope: string; monthly_usd: number }> {
  return http.put(`/providers/ceilings/${encodeURIComponent(scope)}`, { monthly_usd: monthlyUsd });
}

export function deleteSpendCeiling(scope: string): Promise<{ scope: string; deleted: boolean }> {
  return http.delete(`/providers/ceilings/${encodeURIComponent(scope)}`);
}
