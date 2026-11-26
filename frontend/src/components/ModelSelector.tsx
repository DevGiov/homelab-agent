import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Star,
  Eye,
  Check,
  Search,
  ChevronDown,
  Loader2,
  AlertTriangle,
  Ban,
  Cloud,
  Server,
  WifiOff,
} from 'lucide-react';
import { type CatalogProvider, type ModelDetail, type ModelRef, loadModel } from '../api/providers';
import { LABEL_HINTS } from '../utils/sensitivity';

const FAVORITES_STORAGE_KEY = 'homelab_favorite_models';

function getFavoriteModels(): string[] {
  try {
    const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveFavoriteModels(favs: string[]) {
  try {
    localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(favs));
  } catch {}
}

/** Livello effettivo del provider, nel testo del gruppo. */
const CLEARANCE_TEXT = { public: 'pubblici', internal: 'interni', private: 'privati' } as const;

interface ModelSelectorProps {
  /** La coppia (provider, modello) scelta; null finché il catalogo non l'ha data. */
  selected: ModelRef | null;
  onSelect: (ref: ModelRef) => void;
  /** I provider attivi con i loro modelli (`GET /v1/models`). */
  providers: CatalogProvider[];
  onRefreshModels?: () => void;
  className?: string;
}

/**
 * Selettore del modello: i modelli di ogni provider attivo, raggruppati sotto il nome del provider con l'indicazione
 * locale o cloud e il livello dei dati che può ricevere. Un provider non raggiungibile resta nell'elenco, segnato. Se il
 * provider della scelta non è più nel catalogo (disattivato o eliminato) la scelta resta visibile e segnata non disponibile.
 */
export const ModelSelector: React.FC<ModelSelectorProps> = ({
  selected,
  onSelect,
  providers,
  onRefreshModels,
  className = '',
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [favorites, setFavorites] = useState<string[]>(getFavoriteModels);
  const [loadingModels, setLoadingModels] = useState<string[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close dropdown on click outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      setTimeout(() => searchInputRef.current?.focus(), 50);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  // Connect to SSE for real-time model status
  useEffect(() => {
    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource('/v1/models/events');
      eventSource.onmessage = (event) => {
        try {
          const { model, status } = JSON.parse(event.data);
          setLoadingModels((prev) => {
            const others = prev.filter((id) => id !== model);
            return status === 'loading' ? [...others, model] : others;
          });
          if (status !== 'loading') {
            onRefreshModels?.();
          }
        } catch {}
      };
      eventSource.onerror = () => {
        // Fallback polling if SSE disconnects
      };
    } catch {}

    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [onRefreshModels]);

  const toggleFavorite = (e: React.MouseEvent, modelId: string) => {
    e.stopPropagation();
    setFavorites((prev) => {
      const next = prev.includes(modelId)
        ? prev.filter((id) => id !== modelId)
        : [...prev, modelId];
      saveFavoriteModels(next);
      return next;
    });
  };

  const handleSelect = async (provider: CatalogProvider, modelId: string) => {
    const detail = provider.models.find((m) => m.id === modelId);
    if (detail?.available === false) return;
    onSelect({ provider: provider.name, model: modelId });
    setIsOpen(false);

    // Il caricamento in VRAM esiste solo per i motori locali compatibili OpenAI (llama.cpp)
    if (provider.kind === 'openai_compat' && !provider.cloud) {
      // Pre-load model in VRAM if not loaded yet
      if (detail && !detail.is_loaded && !detail.is_loading) {
        setLoadingModels((prev) => [...prev.filter((id) => id !== modelId), modelId]);
        try {
          await loadModel(provider.name, modelId);
        } catch (e) {
          console.warn('Richiesta caricamento modello fallita:', e);
        }
        // Da qui in poi lo stato lo dice il server: se il caricamento non è partito il badge sparisce
        setLoadingModels((prev) => prev.filter((id) => id !== modelId));
        onRefreshModels?.();
      }
    }
  };

  const selectedModel = selected?.model ?? null;
  const selectedProvider = selected ? providers.find((p) => p.name === selected.provider) : undefined;
  // La scelta punta a un provider che il catalogo non ha più: va detto, non cambiato di nascosto
  const isProviderGone = Boolean(selected && !selectedProvider);
  const currentDetail = selectedProvider?.models.find((m) => m.id === selectedModel);
  // La VRAM esiste solo per i provider locali: un modello cloud non è mai "caricato"
  const isCurrentLoaded = Boolean(selectedProvider && !selectedProvider.cloud && currentDetail?.is_loaded);
  const isCurrentLoading = Boolean(currentDetail?.is_loading || (selectedModel && loadingModels.includes(selectedModel)));
  const isCurrentBlocked = currentDetail?.available === false;
  const selectedLabel = selected ? (providers.length > 1 || isProviderGone ? `${selectedProvider?.display_name ?? selected.provider} · ${selected.model}` : selected.model) : null;

  // Filter models based on search term
  const query = search.trim().toLowerCase();
  const groups = providers
    .map((provider) => ({ provider, models: provider.models.filter((m) => m.id.toLowerCase().includes(query)) }))
    .filter((g) => g.models.length > 0);
  const totalFound = groups.reduce((n, g) => n + g.models.length, 0);

  // Preferiti: in cima, di qualunque provider; poi i gruppi senza di loro
  const favoriteEntries = groups.flatMap((g) => g.models.filter((m) => favorites.includes(m.id)).map((m) => ({ provider: g.provider, model: m })));
  const otherGroups = groups
    .map((g) => ({ ...g, models: g.models.filter((m) => !favorites.includes(m.id)) }))
    .filter((g) => g.models.length > 0);

  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center glass-card border border-border rounded-lg px-2 py-1 text-xs gap-1.5 text-fg-muted hover:border-accent/40 hover:text-fg transition shadow-xs cursor-pointer select-none max-w-[200px] sm:max-w-[260px]"
        aria-haspopup="true"
        aria-expanded={isOpen}
        title={
          !selected
            ? 'Modello LLM: predefinito'
            : isProviderGone
            ? `Modello LLM: ${selected.model} — il provider "${selected.provider}" non è più disponibile`
            : `Modello LLM: ${selected.model}${isCurrentLoaded ? ' (Caricato in VRAM)' : isCurrentLoading ? ' (In caricamento...)' : ''}`
        }
      >
        <Box size={12} className="text-emerald-400 shrink-0" />

        <span className={`truncate text-xs text-fg ${selected ? 'font-mono' : ''}`}>
          {selectedLabel ?? 'Modello: predefinito'}
        </span>

        {/* Il provider della scelta è stato disattivato o eliminato: la prossima richiesta fallirebbe */}
        {isProviderGone && (
          <span className="inline-flex items-center gap-1 text-xs text-red-300 font-sans shrink-0">
            <Ban size={11} aria-hidden="true" />
            non disponibile
          </span>
        )}

        {/* Loaded VRAM dot indicator */}
        {selected && isCurrentLoaded && (
          <span
            className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)] shrink-0"
            title="Caricato in VRAM"
          />
        )}

        {/* Il modello scelto è stato bloccato dopo la selezione: la prossima richiesta fallirebbe */}
        {isCurrentBlocked && (
          <span title={currentDetail?.availability_note ?? 'Modello non disponibile'} className="shrink-0">
            <Ban size={11} className="text-red-400" aria-label="Modello non disponibile" />
          </span>
        )}

        {/* Loading spinner with percentage */}
        {isCurrentLoading && (
          <span className="inline-flex items-center gap-1 text-xs text-amber-400 font-sans font-semibold shrink-0">
            <Loader2 size={10} className="animate-spin text-amber-400" />
          </span>
        )}

        <ChevronDown size={11} className={`text-fg-muted transition-transform shrink-0 ml-auto ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* Popover Dropdown Menu */}
      {isOpen && (
        <div className="absolute bottom-full mb-1.5 left-0 z-50 w-80 sm:w-[28rem] max-h-96 glass-panel border border-border/80 shadow-2xl rounded-xl p-2 flex flex-col backdrop-blur-xl bg-panel/95 animate-in fade-in zoom-in-95 duration-100">
          {/* Search Header */}
          <div className="relative mb-2 shrink-0">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Cerca modello..."
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-panel-header/70 border border-border rounded-lg text-fg focus:border-accent"
            />
          </div>

          {/* Model Items List */}
          <div className="overflow-y-auto stack-y-2 flex-1 pr-0.5 custom-scrollbar text-xs">
            {isProviderGone && selected && (
              <div role="alert" className="flex items-start gap-2 px-2.5 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300">
                <Ban size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
                <span>
                  <span className="font-mono">{selected.provider} · {selected.model}</span> non è disponibile: il provider è
                  disattivato o eliminato. Scegli un altro modello.
                </span>
              </div>
            )}

            {/* Pinned Favorites Section */}
            {favoriteEntries.length > 0 && (
              <div className="stack-y-1">
                <div className="flex items-center gap-1.5 px-2 py-0.5 text-xs font-semibold text-amber-400 uppercase tracking-wider">
                  <Star size={10} className="fill-amber-400" />
                  <span>Preferiti</span>
                </div>
                {favoriteEntries.map(({ provider, model }) => renderModelRow(provider, model, true))}
              </div>
            )}

            {/* Un gruppo per provider */}
            {otherGroups.map(({ provider, models }) => (
              <div key={provider.name} role="group" aria-label={provider.display_name} className="stack-y-1">
                {renderGroupHeader(provider)}
                {models.map((m) => renderModelRow(provider, m))}
              </div>
            ))}

            {providers.length === 0 && (
              <div className="p-4 text-center text-xs text-fg-muted italic">Nessun provider disponibile</div>
            )}

            {providers.length > 0 && totalFound === 0 && query !== '' && (
              <div className="p-4 text-center text-xs text-fg-muted italic">
                Nessun modello trovato per "{search}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  function renderGroupHeader(provider: CatalogProvider) {
    const unreachable = provider.healthy === false;
    return (
      <div className="flex flex-wrap items-center gap-1.5 px-2 pt-1 pb-0.5 text-xs">
        <span className="font-semibold text-fg-muted uppercase tracking-wider">{provider.display_name}</span>
        <span
          className="px-1.5 py-0.5 rounded-sm font-sans font-medium bg-panel-header/70 text-fg-muted border border-border flex items-center gap-1"
          title={provider.cloud ? 'Provider cloud: i dati escono dal homelab' : 'Provider locale'}
        >
          {provider.cloud ? <Cloud size={9} aria-hidden="true" /> : <Server size={9} aria-hidden="true" />}
          <span>{provider.cloud ? 'cloud' : 'locale'}</span>
        </span>
        <span
          className="px-1.5 py-0.5 rounded-sm font-sans font-medium bg-sky-500/10 text-sky-300 border border-sky-500/25"
          title={LABEL_HINTS[provider.clearance]}
        >
          riceve dati {CLEARANCE_TEXT[provider.clearance]}
        </span>
        {unreachable && (
          <span
            className="px-1.5 py-0.5 rounded-sm font-sans font-medium bg-amber-500/10 text-amber-300 border border-amber-500/25 flex items-center gap-1"
            title="L'ultima prova di connessione è fallita: i modelli restano in elenco ma una richiesta potrebbe non andare a buon fine"
          >
            <WifiOff size={9} aria-hidden="true" />
            <span>non raggiungibile</span>
          </span>
        )}
      </div>
    );
  }

  function renderModelRow(provider: CatalogProvider, m: ModelDetail, showProvider = false) {
    const isSelected = selected?.provider === provider.name && selectedModel === m.id;
    const isFav = favorites.includes(m.id);
    const inVram = !provider.cloud && Boolean(m.is_loaded);
    const isLoading = Boolean(m.is_loading || loadingModels.includes(m.id));
    const isBlocked = m.available === false;

    return (
      <div
        key={`${provider.name}/${m.id}`}
        onClick={() => handleSelect(provider, m.id)}
        aria-disabled={isBlocked}
        title={m.availability_note ?? undefined}
        className={`group flex items-center justify-between px-2.5 py-1.5 rounded-lg transition ${
          isBlocked ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
        } ${
          isSelected
            ? 'bg-accent/15 border border-accent/40 text-fg'
            : inVram
            ? 'hover:bg-panel-header/90 border border-emerald-500/20 bg-emerald-500/5 text-fg'
            : 'hover:bg-panel-header/70 border border-transparent text-fg-muted hover:text-fg'
        }`}
      >
        {/* Star Button + Model Name */}
        <div className="flex items-center gap-2 min-w-0 mr-2">
          <button
            type="button"
            onClick={(e) => toggleFavorite(e, m.id)}
            className="p-0.5 text-fg-muted hover:text-amber-400 transition cursor-pointer shrink-0"
            title={isFav ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'}
          >
            <Star
              size={12}
              className={isFav ? 'text-amber-400 fill-amber-400' : 'text-fg-muted group-hover:text-fg'}
            />
          </button>

          <span className="font-mono text-xs truncate" title={m.id}>
            {m.id}
          </span>
          {showProvider && <span className="text-xs text-fg-muted shrink-0">{provider.display_name}</span>}
        </div>

        {/* Badges + Selection indicator */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* Loaded in VRAM Badge */}
          {inVram && (
            <span
              className="px-1.5 py-0.5 rounded-sm text-xs font-sans font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex items-center gap-1"
              title="Caricato in VRAM"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.8)]" />
              <span>In VRAM</span>
            </span>
          )}

          {/* Loading Badge */}
          {isLoading && (
            <span
              className="px-1.5 py-0.5 rounded-sm text-xs font-sans font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30 flex items-center gap-1 animate-tint-pulse"
              title="Caricamento in corso..."
            >
              <Loader2 size={9} className="animate-spin text-amber-400" />
              <span>Caricamento...</span>
            </span>
          )}

          {/* Disponibilità secondo il watchdog */}
          {isBlocked && (
            <span
              className="px-1.5 py-0.5 rounded-sm text-xs font-sans font-medium bg-red-500/10 text-red-300 border border-red-500/20 flex items-center gap-1"
              title={m.availability_note ?? 'Modello non disponibile'}
            >
              <Ban size={9} />
              <span>Bloccato</span>
            </span>
          )}
          {m.would_block && (
            <span
              className="px-1.5 py-0.5 rounded-sm text-xs font-sans font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center gap-1"
              title={m.availability_note ?? 'Sconsigliato ora'}
            >
              <AlertTriangle size={9} />
              <span>Usa RAM</span>
            </span>
          )}

          {/* Vision Modality Badge */}
          {m.is_vision && (
            <span
              className="px-1.5 py-0.5 rounded-sm text-xs font-sans font-medium bg-cyan-500/10 text-cyan-300 border border-cyan-500/25 flex items-center gap-0.5"
              title="Supporta visione multimodale"
            >
              <Eye size={9} />
              <span>Visione</span>
            </span>
          )}

          {/* Checkmark if selected */}
          {isSelected && <Check size={13} className="text-accent-text ml-1" />}
        </div>
      </div>
    );
  }
};
