import { useCallback, useEffect, useRef, useState } from 'react';
import {
  clearFacts,
  createFact,
  deleteEntity,
  deleteFact,
  extractEntities,
  getEntity,
  getMemoryStats,
  listEntities,
  listFacts,
  mergeEntity,
  updateEntity,
  updateFact,
  type Entity,
  type EntityDetail,
  type EntityRef,
  type EntityType,
  type Fact,
  type FactInput,
  type MemoryStats,
} from '../api/memory';
import { formatApiError } from '../utils/error';
import type { Notify } from './useFeedback';

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 350;

/** Stato dell'explorer della memoria: fatti (elenco o ricerca per significato), entità, entità selezionata e azioni. */
export function useMemoryExplorer(notify: Notify) {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [entityQuery, setEntityQuery] = useState('');
  const [entityType, setEntityType] = useState<EntityType | ''>('');
  const [selected, setSelected] = useState<EntityDetail | null>(null);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [searchText, setSearchText] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isExtracting, setIsExtracting] = useState(false);
  const selectedId = selected?.id;

  // La ricerca parte quando l'utente smette di scrivere
  useEffect(() => {
    const timer = setTimeout(() => setSearchText(query.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const loadFacts = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await listFacts({ query: searchText || undefined, entity_id: selectedId, limit: PAGE_SIZE });
      setFacts(res.facts);
      setTotal(res.total);
    } catch (err) {
      notify('error', `Fatti non caricati: ${formatApiError(err)}`);
    } finally {
      setIsLoading(false);
    }
  }, [searchText, selectedId, notify]);

  const loadEntities = useCallback(async () => {
    try {
      setEntities(await listEntities(entityQuery.trim() || undefined, entityType || undefined));
    } catch (err) {
      notify('error', `Entità non caricate: ${formatApiError(err)}`);
    }
  }, [entityQuery, entityType, notify]);

  const loadStats = useCallback(async () => {
    try {
      setStats(await getMemoryStats());
    } catch {
      setStats(null);
    }
  }, []);

  useEffect(() => {
    loadFacts();
  }, [loadFacts]);
  useEffect(() => {
    loadEntities();
  }, [loadEntities]);
  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const selectEntity = useCallback(
    async (id: number | null) => {
      if (id == null) {
        setSelected(null);
        return;
      }
      try {
        setSelected(await getEntity(id));
      } catch (err) {
        notify('error', formatApiError(err));
      }
    },
    [notify]
  );

  // Dopo una modifica: contatori, entità ed entità selezionata (che può essere sparita) tornano allineati
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const refreshAll = useCallback(async () => {
    await Promise.all([loadFacts(), loadEntities(), loadStats()]);
    const current = selectedRef.current;
    if (current != null) {
      try {
        setSelected(await getEntity(current));
      } catch {
        setSelected(null);
      }
    }
  }, [loadFacts, loadEntities, loadStats]);

  const loadMore = useCallback(async () => {
    try {
      const res = await listFacts({ entity_id: selectedId, limit: PAGE_SIZE, offset: facts.length });
      setFacts((prev) => [...prev, ...res.facts]);
    } catch (err) {
      notify('error', formatApiError(err));
    }
  }, [selectedId, facts.length, notify]);

  /** Esegue un'azione, mostra l'esito e riallinea la vista; false se è fallita. */
  const run = useCallback(
    async (action: () => Promise<unknown>, success: string) => {
      try {
        await action();
        notify('success', success);
        await refreshAll();
        return true;
      } catch (err) {
        notify('error', formatApiError(err));
        return false;
      }
    },
    [notify, refreshAll]
  );

  const saveFact = (id: number | null, input: FactInput) =>
    run(() => (id == null ? createFact(input) : updateFact(id, input)), id == null ? 'Fatto aggiunto.' : 'Fatto aggiornato.');
  const removeFact = (id: number) => run(() => deleteFact(id), 'Fatto eliminato.');
  const editEntity = (id: number, input: EntityRef) => run(() => updateEntity(id, input), `Entità '${input.name}' aggiornata.`);
  const removeEntity = (entity: Entity) =>
    run(async () => {
      await deleteEntity(entity.id);
      setSelected(null);
    }, `Entità '${entity.name}' eliminata: i suoi fatti restano.`);
  const mergeInto = (source: Entity, target: Entity) =>
    run(async () => {
      await mergeEntity(source.id, target.id);
      setSelected(await getEntity(target.id));
    }, `'${source.name}' unita in '${target.name}'.`);

  const clearAll = () =>
    run(async () => {
      await clearFacts();
      setSelected(null);
    }, 'Memoria a lungo termine svuotata.');

  const extract = async () => {
    setIsExtracting(true);
    try {
      const res = await extractEntities();
      notify('success', `Entità assegnate a ${res.tagged} fatti su ${res.processed} analizzati${res.remaining ? `, ${res.remaining} ancora da analizzare` : ''}.`);
      await refreshAll();
    } catch (err) {
      notify('error', `Estrazione non riuscita: ${formatApiError(err)}`);
    } finally {
      setIsExtracting(false);
    }
  };

  return {
    stats,
    entities,
    entityQuery,
    setEntityQuery,
    entityType,
    setEntityType,
    selected,
    selectEntity,
    facts,
    total,
    query,
    setQuery,
    isSearching: searchText !== '',
    isLoading,
    isExtracting,
    loadMore,
    reload: refreshAll,
    refreshStats: loadStats,
    saveFact,
    removeFact,
    editEntity,
    removeEntity,
    mergeInto,
    clearAll,
    extract,
  };
}

export type MemoryExplorer = ReturnType<typeof useMemoryExplorer>;
