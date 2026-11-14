import { http } from './http';
import type { SensitivityLevel } from '../utils/sensitivity';

export type HostOrigin = 'default' | 'user' | 'approval';

export interface AllowedHost {
  host: string;
  note: string;
  origin: HostOrigin;
  created_at: string;
}

export interface AllowedHostsResponse {
  hosts: AllowedHost[];
  defaults: string[];
}

export interface RestoreDefaultsResponse {
  added: number;
  hosts: AllowedHost[];
}

export function listAllowedHosts(): Promise<AllowedHostsResponse> {
  return http.get<AllowedHostsResponse>('/security/allowed-hosts');
}

export function addAllowedHost(host: string, note = ''): Promise<AllowedHost> {
  return http.post<AllowedHost>('/security/allowed-hosts', { host, note });
}

export function removeAllowedHost(host: string): Promise<{ removed: string }> {
  return http.delete<{ removed: string }>(`/security/allowed-hosts/${encodeURIComponent(host)}`);
}

export function restoreDefaultHosts(): Promise<RestoreDefaultsResponse> {
  return http.post<RestoreDefaultsResponse>('/security/allowed-hosts/defaults');
}

// --- Classificazione dei server MCP (sensibilità dei dati, app/security/flows.py) ---

export interface McpFlowSetting {
  /** Nome del server MCP (il prefisso dei tool, es. `files` per `files__read`) o nome completo di un tool. */
  scope: string;
  result_label: SensitivityLevel;
  result_untrusted: boolean;
  clearance: SensitivityLevel;
}

export interface McpFlowsResponse {
  scopes: McpFlowSetting[];
  /** Come vale un server non classificato: il più stretto. */
  default: Omit<McpFlowSetting, 'scope'>;
}

export function listMcpFlows(): Promise<McpFlowsResponse> {
  return http.get<McpFlowsResponse>('/security/mcp-flows');
}

export function saveMcpFlow(scope: string, setting: Omit<McpFlowSetting, 'scope'>): Promise<McpFlowSetting> {
  return http.put<McpFlowSetting>(`/security/mcp-flows/${encodeURIComponent(scope)}`, setting);
}

export function deleteMcpFlow(scope: string): Promise<{ removed: string }> {
  return http.delete<{ removed: string }>(`/security/mcp-flows/${encodeURIComponent(scope)}`);
}

// --- Uscite di dati nell'audit ---

export interface DataExitDestination {
  destination: string;
  allow: number;
  ask: number;
  approved: number;
  deny: number;
  lowered: number;
  /** Uscite consentite perché gli argomenti sono stati riscritti senza i dati riservati del turno. */
  clean?: number;
  labels: Record<string, number>;
}

export interface DataExitEvent {
  timestamp: string;
  thread_id: string | null;
  automation_id: string | null;
  tool_name: string;
  label: string;
  destination: string;
  flow: 'ask' | 'deny' | 'lowered';
  summary: string;
}

export interface DataExitSummary {
  hours: number;
  destinations: DataExitDestination[];
  recent: DataExitEvent[];
}

export function getDataExitSummary(hours = 168): Promise<DataExitSummary> {
  return http.get<DataExitSummary>('/security/flows', { hours });
}
