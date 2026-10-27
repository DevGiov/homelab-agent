import { http } from './http';

export interface AutomationSummary {
  id: string;
  name: string;
  description: string;
  version: number;
  enabled: boolean;
  triggers_count: number;
  steps_count: number;
  parameters?: Record<string, any>;
  settings?: Record<string, any>;
  retention_days?: number;
  last_run_status?: string | null;
  last_run_at?: string | null;
  last_artifact_id?: string | null;
  last_artifact_name?: string | null;
  last_artifact_at?: string | null;
  triggers?: Array<{
    id: string;
    type: string;
    cron_expression?: string;
    timezone?: string;
    webhook_token?: string;
    webhook_path?: string;
    enabled?: boolean;
  }>;
  webhook_url?: string | null;
  created_by: string;
  source_type: string;
}

export interface ScheduledJobInfo {
  job_id: string;
  name: string;
  next_run_time?: string | null;
  trigger: string;
}

export interface IntrospectedParameter {
  key?: string;
  name: string;
  type: 'string' | 'number' | 'boolean' | 'secret' | string;
  inferred_type?: string;
  source?: string;
  service?: string;
  default?: any;
  required?: boolean;
  description?: string;
}

export interface IntrospectionResult {
  variables: IntrospectedParameter[];
  parameters: IntrospectedParameter[];
  secrets: IntrospectedParameter[];
}

const automationPath = (id: string) => `/automations/${id}`;

export function fetchAutomations(): Promise<AutomationSummary[]> {
  return http.get('/automations');
}

export function getAutomation(id: string): Promise<any> {
  return http.get(automationPath(id));
}

export function createOrUpdateAutomation(automation: any): Promise<any> {
  return http.post('/automations', automation);
}

export function updateAutomation(id: string, automation: any): Promise<any> {
  return http.put(automationPath(id), automation);
}

export function deleteAutomation(id: string): Promise<void> {
  return http.delete(automationPath(id));
}

export function toggleAutomationEnabled(id: string, enabled?: boolean): Promise<{ id: string; enabled: boolean; name: string }> {
  return http.patch(`${automationPath(id)}/toggle`, enabled !== undefined ? { enabled } : {});
}

export function updateAutomationTriggers(id: string, triggers: any[]): Promise<{ id: string; triggers: any[] }> {
  return http.put(`${automationPath(id)}/triggers`, triggers);
}

export function regenerateWebhookToken(
  id: string
): Promise<{ id: string; webhook_token: string; webhook_path: string; triggers: any[] }> {
  return http.post(`${automationPath(id)}/webhook-regenerate`);
}

export function introspectAutomationParameters(id: string): Promise<IntrospectionResult> {
  return http.get(`${automationPath(id)}/introspect-parameters`);
}

export function fetchAutomationTemplates(): Promise<any[]> {
  return http.get('/automations/templates');
}

export function fetchScheduledJobs(): Promise<{ running: boolean; jobs: ScheduledJobInfo[] }> {
  return http.get('/automations/scheduler/jobs');
}
