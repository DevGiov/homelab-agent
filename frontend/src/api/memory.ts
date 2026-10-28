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
  created_at: string | null;
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
  facts: number;
  threads: number;
  entities: number;
  /** Fatti mai analizzati per le entità (salvati prima delle entità o a mano senza entità). */
  facts_without_entities: number;
}

export interface FactFilters {
  query?: string;
  thread_id?: string;
  entity_id?: number;
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
