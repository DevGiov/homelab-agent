import type { SecurityMode } from './chat';
import { http } from './http';

export type ApprovalAction = 'deny' | 'approve' | 'approve_thread' | 'approve_always';

export interface ApprovalItem {
  request_id: string;
  tool_name: string;
  arguments: Record<string, any>;
  thread_id: string | null;
  mode: string | null;
  age_seconds: number;
  command_preview?: string;
  command_prefix?: string;
  risk_reason?: string;
  security_mode?: SecurityMode;
}

export interface PermissionItem {
  id: number;
  tool_name: string;
  command_prefix?: string | null;
  scope: string;
  created_at?: string;
  created_by?: string;
}

export interface PermissionsListResponse {
  always: PermissionItem[];
  session: Record<string, string[]>;
}

export interface ResolveApprovalResponse {
  request_id: string;
  status: 'approved' | 'denied' | 'expired';
  action?: string;
  tool_name?: string;
  result?: any;
  message?: string;
}

export async function listApprovals(threadId?: string): Promise<ApprovalItem[]> {
  const res = await http.get<{ pending: ApprovalItem[] }>('/approvals', { thread_id: threadId });
  return res.pending;
}

export function resolveApproval(
  requestId: string,
  action: ApprovalAction,
  resolvedBy: string = 'user'
): Promise<ResolveApprovalResponse> {
  return http.post(`/approvals/${encodeURIComponent(requestId)}/resolve`, { action, resolved_by: resolvedBy });
}

export async function listGrantedPermissions(): Promise<PermissionsListResponse> {
  const res = await http.get<any>('/permissions');
  const data = res?.permissions || res || {};
  return {
    always: Array.isArray(data.always) ? data.always : [],
    session: typeof data.session === 'object' && data.session !== null ? data.session : {},
  };
}

export function revokePermission(permissionId: number): Promise<void> {
  return http.delete(`/permissions/${permissionId}`);
}

export function revokeThreadPermissions(threadId: string): Promise<void> {
  return http.delete(`/threads/${encodeURIComponent(threadId)}/permissions`);
}
