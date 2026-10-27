import { http } from './http';

/**
 * Valore con cui il backend maschera i segreti salvati. Rimandato invariato in un salvataggio,
 * il backend conserva il segreto esistente invece di sovrascriverlo.
 */
export const MASKED_SECRET = '••••••••';

export interface ServiceIntegration {
  id: string;
  service_type: 'email' | 'github' | 'home_assistant' | 'generic_secret' | string;
  name: string;
  status: 'connected' | 'untested' | 'error' | string;
  config: Record<string, any>;
  secrets: Record<string, any>;
  last_tested_at?: string;
  last_error?: string;
  created_at?: string;
  updated_at?: string;
}

export interface IntegrationTestResult {
  success: boolean;
  message?: string;
  error?: string;
  latency_ms?: number;
  [key: string]: any;
}

export function fetchIntegrations(serviceType?: string): Promise<ServiceIntegration[]> {
  return http.get('/automations/integrations', { service_type: serviceType });
}

export function saveIntegration(data: Partial<ServiceIntegration>): Promise<ServiceIntegration> {
  return http.post('/automations/integrations', data);
}

export function testIntegration(id: string): Promise<IntegrationTestResult> {
  return http.post(`/automations/integrations/${id}/test`);
}

export function deleteIntegration(id: string): Promise<{ deleted: boolean; id: string }> {
  return http.delete(`/automations/integrations/${id}`);
}
