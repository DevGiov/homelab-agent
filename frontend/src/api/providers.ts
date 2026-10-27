import { http } from './http';

export interface ProviderInfo {
  name: string;
  is_default: boolean;
  healthy: boolean;
  default_model: string;
}

export interface ProvidersResponse {
  active_provider: string;
  active_model: string;
  providers: ProviderInfo[];
}

export interface ModelDetail {
  id: string;
  is_vision: boolean;
  input_modalities: string[];
  status?: string;
  is_loaded?: boolean;
  is_loading?: boolean;
  load_progress?: number;
}

interface ProviderModelsResponse {
  provider: string;
  models: string[];
  models_detail?: ModelDetail[];
}

const providerPath = (provider: string) => `/providers/${encodeURIComponent(provider)}`;

export function getProviders(): Promise<ProvidersResponse> {
  return http.get('/providers');
}

export async function getProviderModels(providerName: string): Promise<string[]> {
  const res = await http.get<ProviderModelsResponse>(`${providerPath(providerName)}/models`);
  return res.models;
}

export async function getProviderModelsWithDetails(providerName: string): Promise<ModelDetail[]> {
  const res = await http.get<ProviderModelsResponse>(`${providerPath(providerName)}/models`);
  if (res.models_detail && res.models_detail.length > 0) return res.models_detail;
  return res.models.map((m) => ({
    id: m,
    is_vision: /qwen3\.6|vl|vision|llava|pixtral|gemma-4/i.test(m),
    input_modalities: ['text'],
  }));
}

export function loadModel(provider: string, model: string): Promise<any> {
  return http.post(`${providerPath(provider)}/models/load`, { model });
}

export function setDefaultProvider(
  provider: string,
  model?: string
): Promise<{ status: string; active_provider: string; active_model: string }> {
  return http.put('/providers/default', { provider, model });
}
