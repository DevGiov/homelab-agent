import type { AutomationArtifact } from './artifacts';
import { http } from './http';

export interface AutomationRunSummary {
  run_id: string;
  automation_id: string;
  version_applied: number;
  trigger_type: string;
  status: string;
  current_step_id?: string | null;
  is_dry_run: boolean;
  is_preserved?: boolean;
  is_favorite?: boolean;
  artifacts_count?: number;
  started_at: string;
  completed_at?: string | null;
  total_tokens: number;
  total_duration_ms: number;
  error_message?: string | null;
}

export interface StepRun {
  step_run_id: string;
  run_id: string;
  step_id: string;
  status: string;
  attempt: number;
  started_at?: string | null;
  completed_at?: string | null;
  input_payload?: any;
  output_payload?: any;
  error_message?: string | null;
  tool_calls?: Array<{ tool_name: string; args?: any; result?: any; dry_run?: boolean }>;
  tokens_consumed: number;
  approval_request_id?: string | null;
}

export interface AutomationRunDetails extends AutomationRunSummary {
  step_runs: StepRun[];
  artifacts: AutomationArtifact[];
}

export interface AutomationApprovalItem {
  request_id: string;
  run_id: string;
  step_run_id?: string | null;
  tool_name: string;
  arguments?: any;
  command_preview?: string;
  risk_reason?: string;
  status: string;
  created_at: string;
  expires_at?: string | null;
}

const runPath = (runId: string) => `/automations/runs/${runId}`;

export function triggerAutomationRun(
  automationId: string,
  dryRun: boolean = false,
  sync: boolean = false,
  triggerPayload?: Record<string, any>
): Promise<any> {
  return http.post(`/automations/${automationId}/run`, { dry_run: dryRun, trigger_payload: triggerPayload || {} }, { sync });
}

export function fetchAutomationRuns(automationId?: string, status?: string, limit: number = 50): Promise<AutomationRunSummary[]> {
  return http.get('/automations/runs', { automation_id: automationId || undefined, status: status || undefined, limit });
}

export function getAutomationRunDetails(runId: string): Promise<AutomationRunDetails> {
  return http.get(runPath(runId));
}

export function deleteAutomationRun(runId: string): Promise<{ deleted: boolean; run_id: string }> {
  return http.delete(runPath(runId));
}

export function bulkDeleteAutomationRuns(params?: {
  run_ids?: string[];
  automation_id?: string;
  failed_only?: boolean;
  older_than_days?: number;
}): Promise<{ deleted_count: number }> {
  if (params?.run_ids && params.run_ids.length > 0) {
    return http.post('/automations/runs/delete-batch', {
      run_ids: params.run_ids,
      automation_id: params.automation_id,
      failed_only: params.failed_only,
      older_than_days: params.older_than_days,
    });
  }
  return http.delete('/automations/runs', {
    automation_id: params?.automation_id || undefined,
    failed_only: params?.failed_only ? true : undefined,
    older_than_days: params?.older_than_days || undefined,
  });
}

export function toggleAutomationRunFavorite(runId: string, is_favorite?: boolean): Promise<{ run_id: string; is_favorite: boolean }> {
  return http.patch(`${runPath(runId)}/favorite`, undefined, { is_favorite });
}

export function toggleAutomationRunPreserve(runId: string, is_preserved?: boolean): Promise<{ run_id: string; is_preserved: boolean }> {
  return http.patch(`${runPath(runId)}/preserve`, undefined, { is_preserved });
}

export function pauseAutomationRun(runId: string): Promise<{ paused: boolean; run_id: string; status: string }> {
  return http.post(`${runPath(runId)}/pause`);
}

export function resumeAutomationRun(runId: string): Promise<{ resumed: boolean; run_id: string; status: string }> {
  return http.post(`${runPath(runId)}/resume`);
}

// --- Approvazioni richieste dagli step delle run ---

export function fetchAutomationApprovals(runId?: string): Promise<AutomationApprovalItem[]> {
  return http.get('/automations/approvals', { run_id: runId });
}

export function resolveAutomationApproval(
  runId: string,
  approvalId: string,
  action: 'approve' | 'deny',
  resolvedBy: string = 'user'
): Promise<any> {
  return http.post(`${runPath(runId)}/approvals/${approvalId}/resolve`, { action, resolved_by: resolvedBy }, { sync: true });
}

export function deleteAutomationApproval(approvalId: string): Promise<{ status: string; deleted: string }> {
  return http.delete(`/automations/approvals/${approvalId}`);
}

export function clearExpiredAutomationApprovals(): Promise<{ status: string; cleared_count: number }> {
  return http.post('/automations/approvals/clear-expired');
}
