import { http } from './http';

export interface KbDocument {
  filename: string;
  doc_id?: string;
  source?: string;
  chunks: number;
}

export interface KbUploadResponse {
  status: string;
  chunks_indexed: number;
  chunks_total?: number;
}

export async function listKbDocuments(): Promise<KbDocument[]> {
  const res = await http.get<{ documents: KbDocument[] }>('/kb/documents');
  return res.documents;
}

export function uploadKbDocument(fileOrPayload: File | { filename: string; content: string }): Promise<KbUploadResponse> {
  if (fileOrPayload instanceof File) {
    const formData = new FormData();
    formData.append('file', fileOrPayload);
    return http.post('/kb/documents', formData);
  }
  return http.post('/kb/documents', fileOrPayload);
}

export function deleteKbDocument(filename: string): Promise<{ status: string; chunks_deleted: number }> {
  return http.delete(`/kb/documents/${encodeURIComponent(filename)}`);
}

export interface KbSearchResult {
  filename: string;
  doc_id?: string;
  chunks: Array<{ content: string; score: number; chunk_index?: number }>;
}

export async function searchKb(query: string, k = 8): Promise<KbSearchResult[]> {
  const res = await http.get<{ results: KbSearchResult[] }>('/kb/search', { query, k });
  return res.results;
}
