import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  deleteArtifact,
  fetchAllArtifacts,
  getArtifactDetails,
  toggleArtifactFavorite,
  toggleArtifactPreserve,
  type AutomationArtifact,
} from '../../../api/artifacts';
import type { Notify } from '../../../hooks/useFeedback';
import { ArtifactDetail } from './ArtifactDetail';
import { ArtifactFilters, type ArtifactFilterState } from './ArtifactFilters';
import { ArtifactList } from './ArtifactList';

const DESKTOP_BREAKPOINT = 768;

interface ArtifactsViewProps {
  /** Artefatto da aprire subito (es. "ultimo report" di un'automazione). */
  initialArtifactId?: string | null;
  onFeedback: Notify;
}

/** Report e artefatti delle automazioni: filtri, elenco per età e dettaglio affiancato (su mobile alternati). */
export const ArtifactsView: React.FC<ArtifactsViewProps> = ({ initialArtifactId, onFeedback: notify }) => {
  const [artifacts, setArtifacts] = useState<AutomationArtifact[]>([]);
  const [filters, setFilters] = useState<ArtifactFilterState>({ query: '', automationId: 'all', favoriteOnly: false, preservedOnly: false });
  const [isLoading, setIsLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(initialArtifactId || null);
  const [selected, setSelected] = useState<AutomationArtifact | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await fetchAllArtifacts({
        automation_id: filters.automationId !== 'all' ? filters.automationId : undefined,
        query: filters.query.trim() || undefined,
        favorite_only: filters.favoriteOnly || undefined,
        preserved_only: filters.preservedOnly || undefined,
        limit: 200,
      });
      setArtifacts(data);
      // Su desktop si apre subito il primo artefatto; su mobile si parte dall'elenco
      if (initialArtifactId && data.some((a) => a.artifact_id === initialArtifactId)) {
        setSelectedId(initialArtifactId);
      } else if (data.length > 0 && window.innerWidth >= DESKTOP_BREAKPOINT) {
        setSelectedId((current) => current ?? data[0].artifact_id);
      }
    } catch (err) {
      console.error('Errore caricamento lista artefatti:', err);
      notify('error', 'Impossibile caricare gli artefatti.');
    } finally {
      setIsLoading(false);
    }
  }, [filters, initialArtifactId, notify]);

  useEffect(() => {
    load();
  }, [load]);

  // Il dettaglio porta anche il contenuto completo, che l'elenco non include
  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    let active = true;
    setIsLoadingDetail(true);
    getArtifactDetails(selectedId)
      .then((detail) => active && setSelected(detail))
      .catch((err) => {
        if (!active) return;
        console.error('Errore caricamento dettaglio artefatto:', err);
        notify('error', "Impossibile caricare il contenuto dell'artefatto.");
      })
      .finally(() => active && setIsLoadingDetail(false));
    return () => {
      active = false;
    };
  }, [selectedId, notify]);

  const patch = (artifactId: string, changes: Partial<AutomationArtifact>) => {
    setArtifacts((prev) => prev.map((a) => (a.artifact_id === artifactId ? { ...a, ...changes } : a)));
    setSelected((current) => (current?.artifact_id === artifactId ? { ...current, ...changes } : current));
  };

  const toggleFavorite = async (art: AutomationArtifact) => {
    try {
      const res = await toggleArtifactFavorite(art.artifact_id);
      patch(art.artifact_id, { is_favorite: res.is_favorite });
    } catch {
      notify('error', 'Errore aggiornamento preferito.');
    }
  };

  const togglePreserve = async (art: AutomationArtifact) => {
    try {
      const res = await toggleArtifactPreserve(art.artifact_id);
      patch(art.artifact_id, { is_preserved: res.is_preserved });
      notify('success', res.is_preserved ? 'Artefatto protetto da cancellazione' : 'Protezione cancellazione rimossa');
    } catch {
      notify('error', 'Errore aggiornamento protezione.');
    }
  };

  const remove = async (art: AutomationArtifact) => {
    if (art.is_preserved) {
      alert('Questo report è protetto da cancellazione (bloccato con lucchetto). Sbloccalo prima di eliminarlo.');
      return;
    }
    if (!confirm('Sei sicuro di voler eliminare definitivamente questo artefatto/report?')) return;
    try {
      await deleteArtifact(art.artifact_id);
      setArtifacts((prev) => prev.filter((a) => a.artifact_id !== art.artifact_id));
      if (selectedId === art.artifact_id) setSelectedId(null);
      notify('success', 'Artefatto eliminato.');
    } catch {
      notify('error', 'Errore eliminazione artefatto.');
    }
  };

  const automations = useMemo(() => {
    const names = new Map<string, string>();
    for (const a of artifacts) {
      if (a.automation_id && !names.has(a.automation_id)) names.set(a.automation_id, a.automation_name || a.automation_id);
    }
    return Array.from(names, ([id, name]) => ({ id, name }));
  }, [artifacts]);

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent text-fg overflow-hidden relative font-sans">
      <ArtifactFilters
        filters={filters}
        onChange={(changes) => setFilters((prev) => ({ ...prev, ...changes }))}
        automations={automations}
        total={artifacts.length}
        isLoading={isLoading}
        onRefresh={load}
        hiddenOnMobile={selectedId !== null}
      />

      <div className="flex-1 flex overflow-hidden w-full">
        <ArtifactList
          artifacts={artifacts}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onToggleFavorite={toggleFavorite}
          onTogglePreserve={togglePreserve}
          query={filters.query}
          onClearQuery={() => setFilters((prev) => ({ ...prev, query: '' }))}
        />
        <ArtifactDetail
          artifact={selected}
          isLoading={isLoadingDetail}
          hasSelection={selectedId !== null}
          onBack={() => setSelectedId(null)}
          onDelete={remove}
          notify={notify}
        />
      </div>
    </div>
  );
};
