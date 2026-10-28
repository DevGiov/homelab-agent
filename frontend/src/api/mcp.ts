import { http } from './http';

export type ToolRisk = 'auto' | 'view' | 'confirm' | 'blocked';

export interface MCPServerStatus {
  ok: boolean;
  tool_count: number;
  error: string | null;
  checked_at: number | null;
}

export interface MCPServer {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  /** Server predefinito (MetaMCP) configurato dal .env: non modificabile dalla UI. */
  builtin: boolean;
  has_token: boolean;
  status: MCPServerStatus | null;
}

export interface MCPServerInput {
  name: string;
  url: string;
  enabled: boolean;
  /** In modifica: undefined lascia il token salvato, stringa vuota lo rimuove. */
  token?: string;
}

export interface MCPTool {
  name: string;
  server: string;
  description: string;
  enabled: boolean;
  risk: ToolRisk;
  /** Accesso effettivo dopo le impostazioni: lettura automatica o esecuzione con le regole di sicurezza. */
  access: 'view' | 'execute';
}

export interface MCPTestResult {
  ok: boolean;
  tool_count?: number;
  tools?: string[];
  error?: string;
  latency_ms: number;
}

export function listMcpServers(): Promise<MCPServer[]> {
  return http.get('/mcp/servers');
}

export function createMcpServer(server: MCPServerInput & { id: string }): Promise<MCPServer> {
  return http.post('/mcp/servers', server);
}

export function updateMcpServer(id: string, server: MCPServerInput): Promise<MCPServer> {
  return http.put(`/mcp/servers/${encodeURIComponent(id)}`, server);
}

export function deleteMcpServer(id: string): Promise<{ deleted: string }> {
  return http.delete(`/mcp/servers/${encodeURIComponent(id)}`);
}

/** Prova di connessione di un server non ancora salvato. */
export function testMcpConnection(url: string, token: string): Promise<MCPTestResult> {
  return http.post('/mcp/servers/test', { url, token });
}

export function testMcpServer(id: string): Promise<MCPTestResult> {
  return http.post(`/mcp/servers/${encodeURIComponent(id)}/test`);
}

export function listMcpTools(refresh = false): Promise<MCPTool[]> {
  return http.get('/mcp/tools', { refresh: refresh || undefined });
}

export function updateMcpTool(
  name: string,
  setting: { enabled: boolean; risk: ToolRisk }
): Promise<Pick<MCPTool, 'name' | 'enabled' | 'risk' | 'access'>> {
  return http.put(`/mcp/tools/${encodeURIComponent(name)}`, setting);
}

export function reloadMcpServers(): Promise<Record<string, MCPServerStatus>> {
  return http.post('/mcp/reload');
}
