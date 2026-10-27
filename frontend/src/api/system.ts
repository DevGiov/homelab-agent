import { http } from './http';

export function checkHealth(): Promise<{ status: string }> {
  return http.get('/health');
}
