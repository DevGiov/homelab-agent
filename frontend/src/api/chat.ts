import { apiUrl, authHeaders, errorFromResponse, http } from './http';
import { readSseEvents } from './sse';

export type AgentMode = 'chat' | 'ask' | 'act' | 'plan';

export type SecurityMode = 'safest' | 'normal' | 'dangerous';

export type WebSearchMode = 'auto' | 'on' | 'off';

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
  web_search?: WebSearchMode;
  images?: string[];
  security_mode?: SecurityMode;
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
  approval_required?: boolean;
  request_id?: string;
  approval_prompt?: string;
  command_preview?: string;
  command_prefix?: string;
  risk_reason?: string;
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
  llm_duration_s?: number;
  tok_per_s?: number;
}

export interface ChatResponse {
  thread_id: string | null;
  mode: AgentMode | string;
  model?: string;
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
  approval_required?: boolean;
  request_id?: string;
  approval_prompt?: string;
  command_preview?: string;
  command_prefix?: string;
  risk_reason?: string;
  security_mode?: SecurityMode;
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
  approval_required?: boolean;
  request_id?: string;
  approval_prompt?: string;
  command_preview?: string;
  command_prefix?: string;
  risk_reason?: string;
  approval_resolved?: boolean;
  approval_action?: string;
  security_mode?: SecurityMode;
}

export interface FormattedMessage extends MessageVersion {
  sender: 'user' | 'assistant';
  versions?: MessageVersion[];
  versionIndex?: number;
}

/** Stato accumulato del turno, inviato all'aggancio a uno stream già avviato. */
export interface StreamSnapshot {
  status?: string;
  mode?: string;
  tool_used?: string;
  reasoning_content?: string;
  content?: string;
  execution_trace?: ExecutionTraceItem[];
  plan_steps?: string[];
  plan_structure?: PlanStructure;
  is_paused?: boolean;
  metrics?: StreamMetrics;
}

export interface StreamHandlers {
  onReasoning?: (delta: string) => void;
  onContent?: (delta: string) => void;
  onFinal?: (response: ChatResponse) => void;
  onRetrieval?: (event: string, data: any) => void;
  onMetrics?: (metrics: StreamMetrics) => void;
  onSync?: (snapshot: StreamSnapshot) => void;
}

async function consumeStream(response: Response, handlers: StreamHandlers): Promise<void> {
  if (!response.ok) throw await errorFromResponse(response);
  if (!response.body) throw new Error('ReadableStream non supportato da questo browser.');

  for await (const event of readSseEvents(response.body)) {
    switch (event.type) {
      case 'sync':
        handlers.onSync?.(event);
        break;
      case 'reasoning':
        handlers.onReasoning?.(event.delta);
        break;
      case 'content':
        handlers.onContent?.(event.delta);
        break;
      case 'retrieval':
        handlers.onRetrieval?.(event.event, event.data);
        break;
      case 'metrics':
        handlers.onMetrics?.(event.metrics);
        break;
      case 'final':
        handlers.onFinal?.(event.response);
        break;
      case 'error':
        throw new Error(event.error || 'Errore durante la generazione');
    }
  }
}

const isAbort = (err: unknown) => err instanceof DOMException && err.name === 'AbortError';

/**
 * Avvia un turno in streaming. La promise fallisce su errore HTTP, di rete o evento `error`
 * del backend; un abort tramite `signal` la chiude senza errore.
 */
export async function sendStreamMessage(req: ChatRequest, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  try {
    const response = await fetch(apiUrl('/invoke_stream'), {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(req),
      signal,
    });
    await consumeStream(response, handlers);
  } catch (err) {
    if (!isAbort(err)) throw err;
  }
}

/** Si riaggancia allo stream di un turno ancora in corso (es. dopo un reload della pagina); stesso contratto di `sendStreamMessage`. */
export async function attachToThreadStream(threadId: string, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  try {
    const response = await fetch(apiUrl(`/threads/${encodeURIComponent(threadId)}/stream`), {
      headers: authHeaders(),
      signal,
    });
    await consumeStream(response, handlers);
  } catch (err) {
    if (!isAbort(err)) throw err;
  }
}

export function stopChatStream(threadId: string): Promise<{ status: string }> {
  return http.post('/chat/stop', { thread_id: threadId });
}

export function pauseChatStream(threadId: string): Promise<{ status: string }> {
  return http.post('/chat/pause', { thread_id: threadId });
}

export function resumeChatStream(threadId: string): Promise<{ status: string }> {
  return http.post('/chat/resume', { thread_id: threadId });
}
