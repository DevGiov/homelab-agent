import { http } from './http';

export const ENTITY_TYPES = ['person', 'organization', 'place', 'project', 'software', 'infrastructure', 'other'] as const;
export type EntityType = (typeof ENTITY_TYPES)[number];

export interface EntityRef {
  name: string;
  type: EntityType;
}

export interface FactEntity extends EntityRef {
  id: number;
}

export interface Fact {
  id: number;
  content: string;
  /** Thread in cui è emerso; null per i fatti aggiunti a mano. */
  thread_id: string | null;
  source: 'conversation' | 'manual' | string;
  /** Da quando vale (per i fatti consolidati, la data del messaggio da cui viene). */
  created_at: string | null;
  /** Da quando non vale più: smentito da un fatto più recente o non più vero. */
  invalid_at: string | null;
  /** Il fatto che lo sostituisce. */
  superseded_by: number | null;
  entities: FactEntity[];
  /** Somiglianza con la query, solo nei risultati di ricerca. */
  score?: number;
}

export interface Entity extends FactEntity {
  fact_count: number;
}

export interface EntityDetail extends Entity {
  /** Entità citate negli stessi fatti, con il numero di fatti in comune. */
  related: Array<FactEntity & { shared: number }>;
}

export interface MemoryStats {
  /** Fatti validi. */
  facts: number;
  superseded_facts: number;
  threads: number;
  entities: number;
  /** Fatti mai analizzati per le entità (salvati prima delle entità o a mano senza entità). */
  facts_without_entities: number;
  episodes: number;
  /** Procedure proposte in attesa di approvazione. */
  procedures_proposed: number;
}

export interface FactFilters {
  query?: string;
  thread_id?: string;
  entity_id?: number;
  include_superseded?: boolean;
  limit?: number;
  offset?: number;
}

export interface FactInput {
  content: string;
  entities: EntityRef[];
}

export function getMemoryStats(): Promise<MemoryStats> {
  return http.get('/memory/stats');
}

export function listFacts(filters: FactFilters = {}): Promise<{ facts: Fact[]; total: number }> {
  return http.get('/memory/facts', { ...filters });
}

export function createFact(input: FactInput): Promise<Fact> {
  return http.post('/memory/facts', input);
}

export function updateFact(id: number, input: FactInput): Promise<Fact> {
  return http.put(`/memory/facts/${id}`, input);
}

export function restoreFact(id: number): Promise<Fact> {
  return http.post(`/memory/facts/${id}/restore`);
}

export function deleteFact(id: number): Promise<void> {
  return http.delete(`/memory/facts/${id}`);
}

export function clearFacts(): Promise<{ deleted: number }> {
  return http.delete('/memory/facts');
}

export function listEntities(query?: string, type?: EntityType): Promise<Entity[]> {
  return http.get('/memory/entities', { query, type });
}

export function getEntity(id: number): Promise<EntityDetail> {
  return http.get(`/memory/entities/${id}`);
}

export function updateEntity(id: number, input: EntityRef): Promise<EntityDetail> {
  return http.put(`/memory/entities/${id}`, input);
}

export function mergeEntity(id: number, into: number): Promise<EntityDetail> {
  return http.post(`/memory/entities/${id}/merge`, { into });
}

export function deleteEntity(id: number): Promise<void> {
  return http.delete(`/memory/entities/${id}`);
}

/** Assegna con l'LLM le entità ai fatti mai analizzati. */
export function extractEntities(): Promise<{ processed: number; tagged: number; remaining: number }> {
  return http.post('/memory/entities/extract');
}

export interface UserProfile {
  /** Note stabili sull'utente, all'inizio della memoria di ogni turno. */
  content: string;
  updated_at: string | null;
}

export const PROFILE_MAX_CHARS = 4000;

export function getProfile(): Promise<UserProfile> {
  return http.get('/memory/profile');
}

export function updateProfile(content: string): Promise<UserProfile> {
  return http.put('/memory/profile', { content });
}

export interface EpisodeStep {
  tool: string;
  /** Argomenti in JSON, accorciati. */
  args: string;
  error: string | null;
  rolled_back: boolean;
}

/** Esecuzione passata di un turno act o plan, ricavata dalla traccia dei tool. */
export interface Episode {
  id: number;
  content: string;
  thread_id: string | null;
  mode: string | null;
  task: string | null;
  outcome: string | null;
  steps: EpisodeStep[];
  created_at: string | null;
  /** Somiglianza con la query, solo nei risultati di ricerca. */
  score?: number;
}

export function listEpisodes(filters: { query?: string; limit?: number; offset?: number } = {}): Promise<{ episodes: Episode[]; total: number }> {
  return http.get('/memory/episodes', { ...filters });
}

export function deleteEpisode(id: number): Promise<void> {
  return http.delete(`/memory/episodes/${id}`);
}

export function clearEpisodes(): Promise<{ deleted: number }> {
  return http.delete('/memory/episodes');
}

export type ProcedureKind = 'tool_note' | 'plan_template';
export type ProcedureStatus = 'proposed' | 'approved' | 'rejected';

/** Come si fanno le cose: nota sull'uso di un tool o piano modello. In uso solo se approvata. */
export interface Procedure {
  id: number;
  kind: ProcedureKind;
  title: string;
  content: string;
  tool_name: string | null;
  status: ProcedureStatus;
  /** user (scritta a mano), agent (tool propose_procedure) o execution (ricavata da un'esecuzione). */
  source: string;
  thread_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProcedureInput {
  kind: ProcedureKind;
  title: string;
  content: string;
  tool_name: string | null;
}

export function listProcedures(): Promise<Procedure[]> {
  return http.get('/memory/procedures');
}

export function listProcedureTools(): Promise<string[]> {
  return http.get('/memory/procedures/tools');
}

export function createProcedure(input: ProcedureInput): Promise<Procedure> {
  return http.post('/memory/procedures', input);
}

export function updateProcedure(id: number, input: Omit<ProcedureInput, 'kind'>): Promise<Procedure> {
  return http.put(`/memory/procedures/${id}`, input);
}

export function approveProcedure(id: number): Promise<Procedure> {
  return http.post(`/memory/procedures/${id}/approve`);
}

export function rejectProcedure(id: number): Promise<Procedure> {
  return http.post(`/memory/procedures/${id}/reject`);
}

export function deleteProcedure(id: number): Promise<void> {
  return http.delete(`/memory/procedures/${id}`);
}

export interface ConsolidationResult {
  trigger: string;
  messages?: number;
  added?: number;
  updated?: number;
  invalidated?: number;
  deduplicated?: number;
  error?: string;
  seconds: number;
}

/** Consolidamento della memoria: dai messaggi delle conversazioni ai fatti. */
export interface ConsolidationStatus {
  running: boolean;
  running_since: string | null;
  last_run: string | null;
  last_result: ConsolidationResult | null;
  pending: { messages: number; threads: number };
  /** Ora del consolidamento giornaliero, -1 se solo su richiesta. */
  schedule_hour: number;
}

export function getConsolidation(): Promise<ConsolidationStatus> {
  return http.get('/memory/consolidation');
}

export function startConsolidation(): Promise<{ started: boolean }> {
  return http.post('/memory/consolidation');
}
