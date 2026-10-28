import { http } from './http';

/** Velocità dalle chiamate con i tempi di llama.cpp: null se nella finestra non ce ne sono. */
export interface LlmSpeeds {
  /** Token del prompt elaborati al secondo, esclusi quelli riusati dalla cache. */
  prompt_tok_s: number | null;
  gen_tok_s: number | null;
  cache_hit_pct: number | null;
}

export type TurnStatus = 'ok' | 'error' | 'stopped';
export type TurnSource = 'chat' | 'automation';

export interface ModelStats extends LlmSpeeds {
  model: string;
  calls: number;
  errors: number;
  p50_ms: number | null;
  completion_tokens: number;
}

export interface ToolStats {
  tool: string;
  calls: number;
  errors: number;
  avg_ms: number | null;
  p95_ms: number | null;
}

export interface ServiceHealth {
  service: string;
  samples: number;
  uptime_pct: number;
  /** Esito dell'ultimo campione. */
  ok: boolean;
  last_error: string | null;
  last_checked: string;
  avg_latency_ms: number | null;
}

export interface MetricsSummary {
  window_hours: number;
  turns: {
    total: number;
    by_status: Partial<Record<TurnStatus, number>>;
    by_source: Partial<Record<TurnSource, number>>;
    p50_ms: number | null;
    p95_ms: number | null;
    max_ms: number | null;
    tool_calls: number;
    tool_errors: number;
  };
  llm: LlmSpeeds & {
    calls: number;
    errors: number;
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
  };
  models: ModelStats[];
  tools: ToolStats[];
  health: ServiceHealth[];
}

export interface MetricsPoint extends LlmSpeeds {
  start: string;
  turns: number;
  errors: number;
  stopped: number;
  p50_ms: number | null;
  tool_errors: number;
  llm_calls: number;
}

export interface HealthPoint {
  /** null: nessun campione nell'intervallo. */
  uptime_pct: number | null;
  avg_latency_ms: number | null;
}

export interface MetricsTimeseries {
  window_hours: number;
  bucket_minutes: number;
  points: MetricsPoint[];
  health: Record<string, HealthPoint[]>;
}

export interface TurnRecord {
  id: number;
  ts: string;
  turn_key: string;
  source: TurnSource;
  /** Modalità del grafo per la chat, id dell'automazione per le run. */
  mode: string | null;
  model: string | null;
  status: TurnStatus;
  duration_ms: number;
  llm_ms: number;
  llm_calls: number;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  tool_calls: number;
  tool_errors: number;
  error: string | null;
}

export function getMetricsSummary(hours: number): Promise<MetricsSummary> {
  return http.get('/metrics/summary', { hours });
}

export function getMetricsTimeseries(hours: number, buckets: number): Promise<MetricsTimeseries> {
  return http.get('/metrics/timeseries', { hours, buckets });
}

export function listTurns(limit: number, source?: TurnSource): Promise<TurnRecord[]> {
  return http.get('/metrics/turns', { limit, source });
}
