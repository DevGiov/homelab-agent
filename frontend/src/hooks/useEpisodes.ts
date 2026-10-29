import { useCallback, useEffect, useState } from 'react';
import { clearEpisodes, deleteEpisode, listEpisodes, type Episode } from '../api/memory';
import { formatApiError } from '../utils/error';
import type { Notify } from './useFeedback';

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 350;

/** Episodi di esecuzione: elenco dal più recente o ricerca, con eliminazione. `onChange` riallinea i contatori. */
export function useEpisodes(notify: Notify, onChange: () => void) {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [searchText, setSearchText] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setSearchText(query.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await listEpisodes({ query: searchText || undefined, limit: PAGE_SIZE });
      setEpisodes(res.episodes);
      setTotal(res.total);
    } catch (err) {
      notify('error', `Episodi non caricati: ${formatApiError(err)}`);
    } finally {
      setIsLoading(false);
    }
  }, [searchText, notify]);

  useEffect(() => {
    load();
  }, [load]);

  const loadMore = useCallback(async () => {
    try {
      const res = await listEpisodes({ limit: PAGE_SIZE, offset: episodes.length });
      setEpisodes((prev) => [...prev, ...res.episodes]);
    } catch (err) {
      notify('error', formatApiError(err));
    }
  }, [episodes.length, notify]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      notify('success', success);
      await load();
      onChange();
    } catch (err) {
      notify('error', formatApiError(err));
    }
  };

  return {
    episodes,
    total,
    query,
    setQuery,
    isSearching: searchText !== '',
    isLoading,
    reload: load,
    loadMore,
    remove: (id: number) => run(() => deleteEpisode(id), 'Episodio eliminato.'),
    clearAll: () => run(clearEpisodes, 'Episodi eliminati.'),
  };
}

export type EpisodesState = ReturnType<typeof useEpisodes>;
