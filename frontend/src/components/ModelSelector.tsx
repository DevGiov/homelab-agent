import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Star,
  Eye,
  Check,
  Search,
  ChevronDown,
  Loader2,
  Cpu,
  AlertTriangle,
  Ban,
} from 'lucide-react';
import { type ModelDetail, loadModel } from '../api/providers';

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

interface ModelSelectorProps {
  selectedModel: string;
  onSelectModel: (model: string) => void;
  modelDetails: ModelDetail[];
  activeProvider?: string;
  onRefreshModels?: () => void;
  className?: string;
}

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  selectedModel,
  onSelectModel,
  modelDetails,
  activeProvider = 'llamacpp',
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

  const handleSelect = async (modelId: string) => {
    if (modelDetails.find((m) => m.id === modelId)?.available === false) return;
    onSelectModel(modelId);
    setIsOpen(false);

    if (modelId !== 'default' && activeProvider) {
      const detail = modelDetails.find((m) => m.id === modelId);
      // Pre-load model in VRAM if not loaded yet
      if (detail && !detail.is_loaded && !detail.is_loading) {
        setLoadingModels((prev) => [...prev.filter((id) => id !== modelId), modelId]);
        try {
          await loadModel(activeProvider, modelId);
        } catch (e) {
          console.warn('Richiesta caricamento modello fallita:', e);
        }
        // Da qui in poi lo stato lo dice il server: se il caricamento non è partito il badge sparisce
        setLoadingModels((prev) => prev.filter((id) => id !== modelId));
        onRefreshModels?.();
      }
    }
  };

  // Find detail for currently selected model
  const currentDetail = modelDetails.find((m) => m.id === selectedModel);
  const isCurrentLoaded = Boolean(currentDetail?.is_loaded);
  const isCurrentLoading = Boolean(currentDetail?.is_loading || loadingModels.includes(selectedModel));
  const isCurrentBlocked = currentDetail?.available === false;

  // Filter models based on search term
  const query = search.trim().toLowerCase();
  const filteredModels = modelDetails.filter((m) =>
    m.id.toLowerCase().includes(query)
  );

  // Split into favorites and other models
  const favoriteModels = filteredModels.filter((m) => favorites.includes(m.id));
  const otherModels = filteredModels.filter((m) => !favorites.includes(m.id));

  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center glass-card border border-border rounded-lg px-2 py-1 text-xs gap-1.5 text-fg-muted hover:border-accent/40 hover:text-fg transition shadow-sm cursor-pointer select-none max-w-[200px] sm:max-w-[260px]"
        title={
          selectedModel === 'default'
            ? 'Modello LLM: predefinito'
            : `Modello LLM: ${selectedModel}${isCurrentLoaded ? ' (Caricato in VRAM)' : isCurrentLoading ? ' (In caricamento...)' : ' (Non caricato)'}`
        }
      >
        <Box size={12} className="text-emerald-400 shrink-0" />
        
        <span className={`truncate text-xs text-fg ${selectedModel === 'default' ? '' : 'font-mono'}`}>
          {selectedModel === 'default' ? 'Modello: predefinito' : selectedModel}
        </span>

        {/* Loaded VRAM dot indicator */}
        {selectedModel !== 'default' && isCurrentLoaded && (
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
          <div className="overflow-y-auto space-y-2 flex-1 pr-0.5 custom-scrollbar text-xs">
            {/* Default Model Option */}
            {('default'.includes(query) || query === '') && (
              <div
                onClick={() => handleSelect('default')}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg cursor-pointer transition ${
                  selectedModel === 'default'
                    ? 'bg-accent/15 border border-accent/30 text-fg font-medium'
                    : 'hover:bg-panel-header/80 text-fg-muted hover:text-fg'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Cpu size={13} className="text-fg-muted shrink-0" />
                  <span className="truncate">Modello: predefinito</span>
                </div>
                {selectedModel === 'default' && <Check size={14} className="text-accent shrink-0" />}
              </div>
            )}

            {/* Pinned Favorites Section */}
            {favoriteModels.length > 0 && (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 px-2 py-0.5 text-xs font-semibold text-amber-400 uppercase tracking-wider">
                  <Star size={10} className="fill-amber-400" />
                  <span>Preferiti</span>
                </div>
                {favoriteModels.map((m) => renderModelRow(m))}
              </div>
            )}

            {/* All / Other Models Section */}
            {otherModels.length > 0 && (
              <div className="space-y-1">
                {favoriteModels.length > 0 && (
                  <div className="px-2 pt-1 pb-0.5 text-xs font-semibold text-fg-muted uppercase tracking-wider">
                    Altri Modelli
                  </div>
                )}
                {otherModels.map((m) => renderModelRow(m))}
              </div>
            )}

            {filteredModels.length === 0 && query !== '' && (
              <div className="p-4 text-center text-xs text-fg-muted italic">
                Nessun modello trovato per "{search}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  function renderModelRow(m: ModelDetail) {
    const isSelected = selectedModel === m.id;
    const isFav = favorites.includes(m.id);
    const inVram = Boolean(m.is_loaded);
    const isLoading = Boolean(m.is_loading || loadingModels.includes(m.id));
    const isBlocked = m.available === false;

    return (
      <div
        key={m.id}
        onClick={() => handleSelect(m.id)}
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
        </div>

        {/* Badges + Selection indicator */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* Loaded in VRAM Badge */}
          {inVram && (
            <span
              className="px-1.5 py-0.5 rounded text-xs font-sans font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex items-center gap-1"
              title="Caricato in VRAM"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.8)]" />
              <span>In VRAM</span>
            </span>
          )}

          {/* Loading Badge */}
          {isLoading && (
            <span
              className="px-1.5 py-0.5 rounded text-xs font-sans font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30 flex items-center gap-1 animate-tint-pulse"
              title="Caricamento in corso..."
            >
              <Loader2 size={9} className="animate-spin text-amber-400" />
              <span>Caricamento...</span>
            </span>
          )}

          {/* Disponibilità secondo il watchdog */}
          {isBlocked && (
            <span
              className="px-1.5 py-0.5 rounded text-xs font-sans font-medium bg-red-500/10 text-red-300 border border-red-500/20 flex items-center gap-1"
              title={m.availability_note ?? 'Modello non disponibile'}
            >
              <Ban size={9} />
              <span>Bloccato</span>
            </span>
          )}
          {m.would_block && (
            <span
              className="px-1.5 py-0.5 rounded text-xs font-sans font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center gap-1"
              title={m.availability_note ?? 'Sconsigliato ora'}
            >
              <AlertTriangle size={9} />
              <span>Usa RAM</span>
            </span>
          )}

          {/* Vision Modality Badge */}
          {m.is_vision && (
            <span
              className="px-1.5 py-0.5 rounded text-xs font-sans font-medium bg-cyan-500/10 text-cyan-300 border border-cyan-500/25 flex items-center gap-0.5"
              title="Supporta visione multimodale"
            >
              <Eye size={9} />
              <span>Visione</span>
            </span>
          )}

          {/* Checkmark if selected */}
          {isSelected && <Check size={13} className="text-accent ml-1" />}
        </div>
      </div>
    );
  }
};
