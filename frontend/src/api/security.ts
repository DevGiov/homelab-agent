import { http } from './http';

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
