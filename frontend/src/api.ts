import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || '/v1';

// --- Fase 4: API key globale (localStorage, configurabile dall'utente) ---
const API_KEY_STORAGE = 'main_agent_api_key';

// Chiave iniettata a runtime da /config.json (generato dall'entrypoint Docker)
let _configApiKey = '';

/**
 * Carica la API key da /config.json (servito da nginx a runtime).
 * Deve essere chiamata una volta all'avvio dell'app, prima del primo render.
 * Se il file non esiste (es. dev locale senza Docker), fallisce silenziosamente.
 */
export async function initApiConfig(): Promise<void> {
  try {
    const res = await fetch('/config.json', { cache: 'no-store' });
    if (res.ok) {
      const cfg = await res.json();
      if (cfg.apiKey) _configApiKey = cfg.apiKey;
    }
  } catch {
    // In dev (Vite) /config.json non esiste — nessun problema
  }
}

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE) || _configApiKey;
}
export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key.trim());
}

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
});

// Interceptor: aggiunge X-API-Key a tutte le chiamate axios
api.interceptors.request.use((config) => {
  const key = getApiKey();
  if (key) config.headers['X-API-Key'] = key;
  return config;
});

export type AgentMode = 'chat' | 'ask' | 'act' | 'plan';

export interface WebPrefetchSource {
  title: string;
  url: string;
  snippet?: string;
  score?: number;
  engine?: string;
}

export interface WebPrefetchData {
  query: string;
  success: boolean;
  provider_used?: string;
  latency_ms?: number;
  sources?: WebPrefetchSource[];
  summary_text?: string;
  error?: string;
}

export interface ChatRequest {
  input: string;
  thread_id?: string;
  force_mode?: AgentMode;
  reasoning_budget?: number;
  reasoning_budget_tokens?: number;
  execute?: boolean;
  model?: string;
  incognito?: boolean;
  web_search?: boolean;
  images?: string[];
}

export interface ExecutionTraceItem {
  step_id?: number | string;
  tool_name: string;
  args?: Record<string, any>;
  output?: any;
  result?: any;
  error?: string;
  reasoning?: string;
  execution_time_ms?: number;
  sandboxed?: boolean;
  timestamp?: string;
}

export interface PlanNode {
  id: string;
  tool_name: string;
  args?: Record<string, any>;
  depends_on?: string[];
  description?: string;
  status?: 'pending' | 'running' | 'success' | 'failed' | 'rolled_back';
  output_var?: string;
}

export interface PlanStructure {
  goal?: string;
  nodes?: PlanNode[];
  edges?: Array<{ from: string; to: string }>;
}

export interface RollbackAction {
  tool_name: string;
  args?: Record<string, any>;
  status?: string;
  timestamp?: string;
  error?: string;
}

export interface StreamMetrics {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  duration_s?: number;
  tok_per_s?: number;
}

export interface ChatResponse {
  thread_id: string | null;
  mode: AgentMode | string;
  response: string;
  tool_used?: string;
  plan_steps?: string[];
  plan_structure?: PlanStructure;
  execution_trace?: ExecutionTraceItem[];
  rollback_trace?: RollbackAction[];
  reasoning_content?: string;
  web_prefetch?: WebPrefetchData;
  metrics?: StreamMetrics;
  thread_title?: string;
  error?: string;
}

export interface ThreadItem {
  thread_id: string;
  title?: string;
  last_message: string | null;
  checkpoint_count: number;
  is_active?: boolean;
}

export interface LettaMessage {
  id: string;
  date?: string;
  message_type: 'user_message' | 'assistant_message' | 'system_message' | 'reasoning_message' | 'tool_call_message' | 'tool_return_message' | string;
  content: string | null;
  tool_name?: string;
  metadata?: Record<string, any>;
}

export interface ThreadDetails {
  thread_id: string;
  title?: string;
  agent_id?: string;
  checkpoint_count?: number;
  messages?: FormattedMessage[];
  letta_messages?: LettaMessage[];
  is_active?: boolean;
  is_paused?: boolean;
  active_snapshot?: any;
}

export interface MessageVersion {
  id: string;
  content: string;
  timestamp: string;
  mode?: AgentMode | string;
  tool_used?: string;
  reasoning?: string;
  plan_steps?: string[];
  plan_structure?: PlanStructure;
  execution_trace?: ExecutionTraceItem[];
  rollback_trace?: RollbackAction[];
  reasoning_content?: string;
  web_prefetch?: WebPrefetchData;
  metrics?: StreamMetrics;
  isError?: boolean;
  model?: string;
  reasoningBudget?: number;
  images?: string[];
}

export interface FormattedMessage extends MessageVersion {
  sender: 'user' | 'assistant';
  versions?: MessageVersion[];
  versionIndex?: number;
}

export async function sendMessage(req: ChatRequest): Promise<ChatResponse> {
  const res = await api.post<ChatResponse>('/invoke', req);
  return res.data;
}

export async function sendStreamMessage(
  req: ChatRequest,
  onReasoningDelta?: (delta: string) => void,
  onContentDelta?: (delta: string) => void,
  onFinalResponse?: (response: ChatResponse) => void,
  onError?: (error: string) => void,
  onRetrievalEvent?: (event: string, data: any) => void,
  onMetrics?: (metrics: StreamMetrics) => void,
  signal?: AbortSignal
): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/invoke_stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(getApiKey() ? { 'X-API-Key': getApiKey() } : {}),
      },
      body: JSON.stringify(req),
      signal,
    });

    if (!response.body) throw new Error('ReadableStream not yet supported in this browser.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');

      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');

        if (chunk.startsWith('data: ')) {
          const dataStr = chunk.slice(6);
          if (dataStr === '[DONE]') {
            break;
          }
          try {
            const data = JSON.parse(dataStr);
            if (data.type === 'sync') {
              if (data.reasoning_content && onReasoningDelta) onReasoningDelta(data.reasoning_content);
              if (data.content && onContentDelta) onContentDelta(data.content);
              if (data.metrics && onMetrics) onMetrics(data.metrics);
            } else if (data.type === 'reasoning' && onReasoningDelta) {
              onReasoningDelta(data.delta);
            } else if (data.type === 'content' && onContentDelta) {
              onContentDelta(data.delta);
            } else if (data.type === 'retrieval' && onRetrievalEvent) {
              onRetrievalEvent(data.event, data.data);
            } else if (data.type === 'metrics' && onMetrics) {
              onMetrics(data.metrics);
            } else if (data.type === 'final' && onFinalResponse) {
              onFinalResponse(data.response);
            } else if (data.type === 'error' && onError) {
              onError(data.error);
            }
          } catch (e) {
            console.error('Error parsing SSE JSON', e);
          }
        }
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      console.log('Stream request was aborted by user');
      return;
    }
    if (onError) onError(err.message || 'Stream error');
  }
}

export async function attachToThreadStream(
  threadId: string,
  onReasoningDelta?: (delta: string) => void,
  onContentDelta?: (delta: string) => void,
  onFinalResponse?: (response: ChatResponse) => void,
  onError?: (error: string) => void,
  onRetrievalEvent?: (event: string, data: any) => void,
  onMetrics?: (metrics: StreamMetrics) => void,
  onSync?: (snapshot: any) => void,
  signal?: AbortSignal
): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/threads/${encodeURIComponent(threadId)}/stream`, {
      method: 'GET',
      headers: {
        ...(getApiKey() ? { 'X-API-Key': getApiKey() } : {}),
      },
      signal,
    });

    if (!response.body) throw new Error('ReadableStream not yet supported in this browser.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');

      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');

        if (chunk.startsWith('data: ')) {
          const dataStr = chunk.slice(6);
          if (dataStr === '[DONE]') {
            break;
          }
          try {
            const data = JSON.parse(dataStr);
            if (data.type === 'sync' && onSync) {
              onSync(data);
            } else if (data.type === 'reasoning' && onReasoningDelta) {
              onReasoningDelta(data.delta);
            } else if (data.type === 'content' && onContentDelta) {
              onContentDelta(data.delta);
            } else if (data.type === 'retrieval' && onRetrievalEvent) {
              onRetrievalEvent(data.event, data.data);
            } else if (data.type === 'metrics' && onMetrics) {
              onMetrics(data.metrics);
            } else if (data.type === 'final' && onFinalResponse) {
              onFinalResponse(data.response);
            } else if (data.type === 'error' && onError) {
              onError(data.error);
            }
          } catch (e) {
            console.error('Error parsing SSE JSON', e);
          }
        }
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      console.log('Stream attach request was aborted by user');
      return;
    }
    if (onError) onError(err.message || 'Stream attach error');
  }
}

export async function stopChatStream(threadId: string): Promise<{ status: string }> {
  const res = await api.post<{ status: string }>('/chat/stop', { thread_id: threadId });
  return res.data;
}

export async function pauseChatStream(threadId: string): Promise<{ status: string }> {
  const res = await api.post<{ status: string }>('/chat/pause', { thread_id: threadId });
  return res.data;
}

export async function resumeChatStream(threadId: string): Promise<{ status: string }> {
  const res = await api.post<{ status: string }>('/chat/resume', { thread_id: threadId });
  return res.data;
}

export async function listThreads(): Promise<ThreadItem[]> {
  const res = await api.get<ThreadItem[]>('/threads');
  return res.data;
}

export async function getThreadDetails(threadId: string): Promise<ThreadDetails> {
  const res = await api.get<ThreadDetails>(`/threads/${encodeURIComponent(threadId)}`);
  return res.data;
}

export async function checkHealth(): Promise<{ status: string }> {
  const res = await api.get<{ status: string }>('/health');
  return res.data;
}

export async function deleteThread(threadId: string): Promise<{ status: string }> {
  const res = await api.delete<{ status: string }>(`/threads/${encodeURIComponent(threadId)}`);
  return res.data;
}

export async function deleteAllThreads(): Promise<{ status: string }> {
  const res = await api.delete<{ status: string }>('/threads');
  return res.data;
}

// --- Fase 4.2: Approvals ---

export interface ApprovalItem {
  request_id: string;
  tool_name: string;
  arguments: Record<string, any>;
  thread_id: string | null;
  mode: string | null;
  age_seconds: number;
}

export async function listApprovals(threadId?: string): Promise<ApprovalItem[]> {
  const res = await api.get<{ pending: ApprovalItem[] }>('/approvals', {
    params: threadId ? { thread_id: threadId } : undefined,
  });
  return res.data.pending;
}

export async function approveRequest(requestId: string): Promise<{ request_id: string; status: string; result: any }> {
  const res = await api.post(`/approvals/${encodeURIComponent(requestId)}/approve`);
  return res.data;
}

export async function denyRequest(requestId: string): Promise<{ request_id: string; status: string; tool_name: string }> {
  const res = await api.post(`/approvals/${encodeURIComponent(requestId)}/deny`);
  return res.data;
}

// --- Fase 4.3/4.4: Knowledge Base ---

export interface KbDocument {
  filename: string;
  doc_id?: string;
  source?: string;
  chunks: number;
}

export interface KbSearchResult {
  filename: string;
  doc_id?: string;
  chunks: Array<{ content: string; score: number; chunk_index?: number }>;
}

export async function listKbDocuments(): Promise<KbDocument[]> {
  const res = await api.get<{ documents: KbDocument[] }>('/kb/documents');
  return res.data.documents;
}

export async function uploadKbDocument(fileOrPayload: File | { filename: string; content: string }): Promise<{ status: string; chunks_indexed: number; chunks_total?: number }> {
  if (fileOrPayload instanceof File) {
    const formData = new FormData();
    formData.append('file', fileOrPayload);
    const res = await api.post('/kb/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  } else {
    const res = await api.post('/kb/documents', fileOrPayload);
    return res.data;
  }
}

export async function deleteKbDocument(filename: string): Promise<{ status: string; chunks_deleted: number }> {
  const res = await api.delete<{ status: string; chunks_deleted: number }>(`/kb/documents/${encodeURIComponent(filename)}`);
  return res.data;
}

export async function searchKb(query: string, k: number = 5): Promise<KbSearchResult[]> {
  const res = await api.get<{ results: KbSearchResult[] }>('/kb/search', { params: { query, k } });
  return res.data.results;
}

// --- Provider & Model Management ---

export interface ProviderInfo {
  name: string;
  is_default: boolean;
  healthy: boolean;
  default_model: string;
}

export interface ProvidersResponse {
  active_provider: string;
  active_model: string;
  providers: ProviderInfo[];
}

export interface ModelDetail {
  id: string;
  is_vision: boolean;
  input_modalities: string[];
}

export interface ProviderModelsResponse {
  provider: string;
  models: string[];
  models_detail?: ModelDetail[];
}

export interface ImageUploadResponse {
  url: string;
  data_url: string;
  filename: string;
  width?: number;
  height?: number;
}

export async function uploadImage(file: File): Promise<ImageUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post<ImageUploadResponse>('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = (err) => reject(err);
    reader.readAsDataURL(file);
  });
}

/**
 * Riconosce se un file è di tipo immagine verificando il MIME type
 * o l'estensione del nome file (fondamentale per iOS che spesso passa MIME vuoto).
 */
export function isImageFile(file: File): boolean {
  if (file.type && file.type.startsWith('image/')) return true;
  return /\.(png|jpe?g|webp|gif|bmp|heic|heif|tiff?)$/i.test(file.name);
}

/**
 * Ottimizza e converte un'immagine prima dell'invio al modello multimodale:
 * 1. Prova prima la decodifica in-browser con createImageBitmap o Image element.
 * 2. Se ha successo, downscala l'immagine a max 1920px sul lato maggiore e la esporta
 *    come JPEG a qualità 0.85 (riducendo foto da 15MB a ~200-400KB ed evitando memory leak su iOS).
 * 3. Se la decodifica in-browser fallisce (es. formato HEIC non supportato dal browser),
 *    invia il file all'endpoint backend /v1/upload (che usa pillow-heif) per transcodificarlo in JPEG.
 */
export async function optimizeAndConvertImage(file: File): Promise<{ dataUrl: string; name: string }> {
  const isHeic = /\.(heic|heif)$/i.test(file.name) || file.type.includes('heic') || file.type.includes('heif');
  const isPng = file.type === 'image/png' || /\.png$/i.test(file.name);

  // Se è un piccolo PNG (< 1.5MB), lasciamo intatta la trasparenza e usiamo fileToDataUrl
  if (isPng && !isHeic && file.size < 1.5 * 1024 * 1024) {
    try {
      const dataUrl = await fileToDataUrl(file);
      return { dataUrl, name: file.name };
    } catch {
      // Procedi con decodifica canvas
    }
  }

  // 1. Prova decodifica nativa in-browser (createImageBitmap o HTMLImageElement)
  try {
    let bitmap: ImageBitmap | HTMLImageElement | null = null;
    let width = 0;
    let height = 0;

    if (typeof createImageBitmap === 'function') {
      try {
        bitmap = await createImageBitmap(file);
        width = bitmap.width;
        height = bitmap.height;
      } catch {
        bitmap = null;
      }
    }

    if (!bitmap) {
      const url = URL.createObjectURL(file);
      try {
        const img = new Image();
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject(new Error('Failed to load image element'));
          img.src = url;
        });
        bitmap = img;
        width = img.naturalWidth || img.width;
        height = img.naturalHeight || img.height;
      } finally {
        URL.revokeObjectURL(url);
      }
    }

    if (bitmap && width > 0 && height > 0) {
      const MAX_DIM = 1920;
      let targetW = width;
      let targetH = height;

      if (targetW > MAX_DIM || targetH > MAX_DIM) {
        if (targetW > targetH) {
          targetH = Math.round((targetH * MAX_DIM) / targetW);
          targetW = MAX_DIM;
        } else {
          targetW = Math.round((targetW * MAX_DIM) / targetH);
          targetH = MAX_DIM;
        }
      }

      const canvas = document.createElement('canvas');
      canvas.width = targetW;
      canvas.height = targetH;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        // Sfondo bianco per preservare contrasto se c'era trasparenza
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, targetW, targetH);
        ctx.drawImage(bitmap, 0, 0, targetW, targetH);

        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);

        if ('close' in bitmap && typeof (bitmap as ImageBitmap).close === 'function') {
          (bitmap as ImageBitmap).close();
        }

        const cleanName = file.name.replace(/\.(heic|heif)$/i, '.jpg');
        return { dataUrl, name: cleanName };
      }
    }
  } catch (clientErr) {
    console.warn("Decodifica client-side non riuscita, ricorso all'upload backend:", clientErr);
  }

  // 2. Fallback backend: usa /v1/upload con pillow-heif
  try {
    const uploadRes = await uploadImage(file);
    return { dataUrl: uploadRes.data_url, name: uploadRes.filename };
  } catch (uploadErr) {
    console.error("Anche l'upload backend è fallito:", uploadErr);
    // Ultima spiaggia: lettura diretta FileReader
    const rawDataUrl = await fileToDataUrl(file);
    return { dataUrl: rawDataUrl, name: file.name };
  }
}

export async function getProviders(): Promise<ProvidersResponse> {
  const res = await api.get<ProvidersResponse>('/providers');
  return res.data;
}

export async function getProviderModels(providerName: string): Promise<string[]> {
  const res = await api.get<ProviderModelsResponse>(`/providers/${encodeURIComponent(providerName)}/models`);
  return res.data.models;
}

export async function getProviderModelsWithDetails(providerName: string): Promise<ModelDetail[]> {
  const res = await api.get<ProviderModelsResponse>(`/providers/${encodeURIComponent(providerName)}/models`);
  if (res.data.models_detail && res.data.models_detail.length > 0) {
    return res.data.models_detail;
  }
  return res.data.models.map((m) => ({
    id: m,
    is_vision: /qwen3\.6|vl|vision|llava|pixtral|gemma-4/i.test(m),
    input_modalities: ['text'],
  }));
}

export async function setDefaultProvider(
  provider: string,
  model?: string
): Promise<{ status: string; active_provider: string; active_model: string }> {
  const res = await api.put('/providers/default', { provider, model });
  return res.data;
}

// --- Memory Management ---

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

export async function getMemories(kind: string = 'fact', limit: number = 100, offset: number = 0): Promise<MemoryListResponse> {
  const res = await api.get<MemoryListResponse>('/memory', {
    params: { kind, limit, offset },
  });
  return res.data;
}

export async function addMemory(content: string, kind: string = 'fact', thread_id?: string): Promise<MemoryItem> {
  const res = await api.post<MemoryItem>('/memory', {
    content,
    kind,
    thread_id,
  });
  return res.data;
}

export async function deleteMemory(memoryId: number): Promise<{ status: string; id: number }> {
  const res = await api.delete<{ status: string; id: number }>(`/memory/${memoryId}`);
  return res.data;
}

export async function clearAllMemory(kind?: string): Promise<ClearMemoryResponse> {
  const res = await api.delete<ClearMemoryResponse>('/memory', {
    params: kind ? { kind } : undefined,
  });
  return res.data;
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

export async function searchMemories(
  query: string,
  kind?: string,
  k: number = 5
): Promise<MemorySearchResult[]> {
  const res = await api.get<{ results: MemorySearchResult[] }>('/memory/search', {
    params: { query, kind, k },
  });
  return res.data.results || [];
}

export async function updateThreadTitle(threadId: string, title: string): Promise<void> {
  await api.patch(`/threads/${threadId}/title`, { title });
}

export async function generateThreadTitle(threadId: string): Promise<string> {
  const res = await api.post<{ status: string; thread_id: string; title: string }>(`/threads/${threadId}/title/generate`);
  return res.data.title;
}

export async function switchMessageVersion(threadId: string, messageId: string, versionIndex: number): Promise<void> {
  try {
    await api.post(`/threads/${threadId}/messages/${messageId}/version`, { version_index: versionIndex });
  } catch (err) {
    console.warn('Failed to persist version index on backend:', err);
  }
}

export async function saveMessageVersions(
  threadId: string,
  messageId: string,
  versions: MessageVersion[],
  versionIndex: number
): Promise<void> {
  try {
    await api.post(`/threads/${threadId}/messages/${messageId}/versions_data`, {
      versions,
      version_index: versionIndex,
    });
  } catch (err) {
    console.warn('Failed to persist versions on backend:', err);
  }
}
