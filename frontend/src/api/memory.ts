import { http } from './http';

export interface MemoryItem {
  id: number;
  kind: string;
  thread_id?: string | null;
  content: string;
  metadata?: Record<string, any>;
  created_at?: string | null;
}

export interface MemoryListResponse {
  memories: MemoryItem[];
  total: number;
}

export interface ClearMemoryResponse {
  deleted_count: number;
  letta_cleared: boolean;
  message: string;
}

export interface MemorySearchResult {
  id: number;
  kind: string;
  thread_id?: string | null;
  content: string;
  metadata?: Record<string, any>;
  distance: number;
  score: number;
}

export function getMemories(kind: string = 'fact', limit: number = 100, offset: number = 0): Promise<MemoryListResponse> {
  return http.get('/memory', { kind, limit, offset });
}

export function addMemory(content: string, kind: string = 'fact', thread_id?: string): Promise<MemoryItem> {
  return http.post('/memory', { content, kind, thread_id });
}

export function deleteMemory(memoryId: number): Promise<{ status: string; id: number }> {
  return http.delete(`/memory/${memoryId}`);
}

export function clearAllMemory(kind?: string): Promise<ClearMemoryResponse> {
  return http.delete('/memory', { kind });
}

export async function searchMemories(query: string, kind?: string, k: number = 5): Promise<MemorySearchResult[]> {
  const res = await http.get<{ results: MemorySearchResult[] }>('/memory/search', { query, kind, k });
  return res.results || [];
}
