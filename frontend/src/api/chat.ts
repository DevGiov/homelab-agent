import { apiUrl, authHeaders, errorFromResponse, http } from './http';
import { readSseEvents } from './sse';

export type AgentMode = 'chat' | 'ask' | 'act' | 'plan';

export type SecurityMode = 'safest' | 'normal' | 'dangerous';

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
  web_search?: 'auto' | 'on' | 'off' | boolean;
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
    const response = await fetch(apiUrl('/invoke_stream'), {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(req),
      signal,
    });
    if (!response.ok) throw await errorFromResponse(response);
    if (!response.body) throw new Error('ReadableStream non supportato da questo browser.');

    for await (const data of readSseEvents(response.body)) {
      if (data.type === 'sync') {
        if (data.reasoning_content) onReasoningDelta?.(data.reasoning_content);
        if (data.content) onContentDelta?.(data.content);
        if (data.metrics) onMetrics?.(data.metrics);
      } else if (data.type === 'reasoning') {
        onReasoningDelta?.(data.delta);
      } else if (data.type === 'content') {
        onContentDelta?.(data.delta);
      } else if (data.type === 'retrieval') {
        onRetrievalEvent?.(data.event, data.data);
      } else if (data.type === 'metrics') {
        onMetrics?.(data.metrics);
      } else if (data.type === 'final') {
        onFinalResponse?.(data.response);
      } else if (data.type === 'error') {
        onError?.(data.error);
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') return;
    onError?.(err.message || 'Errore dello stream');
    throw err;
  }
}

/** Si riaggancia allo stream di un turno ancora in corso (es. dopo un reload della pagina). */
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
    const response = await fetch(apiUrl(`/threads/${encodeURIComponent(threadId)}/stream`), {
      headers: authHeaders(),
      signal,
    });
    if (!response.ok) throw await errorFromResponse(response);
    if (!response.body) throw new Error('ReadableStream non supportato da questo browser.');

    for await (const data of readSseEvents(response.body)) {
      if (data.type === 'sync') {
        onSync?.(data);
      } else if (data.type === 'reasoning') {
        onReasoningDelta?.(data.delta);
      } else if (data.type === 'content') {
        onContentDelta?.(data.delta);
      } else if (data.type === 'retrieval') {
        onRetrievalEvent?.(data.event, data.data);
      } else if (data.type === 'metrics') {
        onMetrics?.(data.metrics);
      } else if (data.type === 'final') {
        onFinalResponse?.(data.response);
      } else if (data.type === 'error') {
        onError?.(data.error);
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') return;
    onError?.(err.message || 'Errore nel riaggancio allo stream');
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
