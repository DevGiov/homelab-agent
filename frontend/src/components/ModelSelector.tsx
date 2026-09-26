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
} from 'lucide-react';
import { type ModelDetail, loadModel } from '../api';

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

export function calculateLlamaProgress(progressObj: any): number {
  if (!progressObj) return 0;
  const { current, stages = [], value = 0 } = progressObj;
  const C_e = 0.1;
  const a = 1 - Math.max(stages.length - 1, 0) * C_e;
  const s = stages.indexOf(current);
  const frac = s <= 0 ? value * a : a + (s - 1 + value) * C_e;
  return Math.min(100, Math.max(0, Math.round(frac * 100)));
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
  const [loadingProgressMap, setLoadingProgressMap] = useState<Record<string, number>>({});
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

  // Connect to SSE for real-time model loading progress
  useEffect(() => {
    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource('/v1/models/events');
      eventSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const modelId = payload.model || payload.id;
          const statusData = payload.data || payload;
          const statusVal = statusData.status || statusData.value;
          const progressObj = statusData.progress;

          if (modelId) {
            if (statusVal === 'loading') {
              const pct = calculateLlamaProgress(progressObj);
              setLoadingProgressMap((prev) => ({ ...prev, [modelId]: pct }));
            } else if (statusVal === 'loaded') {
              setLoadingProgressMap((prev) => {
                const next = { ...prev };
                delete next[modelId];
                return next;
              });
              onRefreshModels?.();
            } else if (statusVal === 'unloaded' || statusVal === 'failed') {
              setLoadingProgressMap((prev) => {
                const next = { ...prev };
                delete next[modelId];
                return next;
              });
              onRefreshModels?.();
            }
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
    onSelectModel(modelId);
    setIsOpen(false);

    if (modelId !== 'default' && activeProvider) {
      const detail = modelDetails.find((m) => m.id === modelId);
      // Pre-load model in VRAM if not loaded yet
      if (detail && !detail.is_loaded && !detail.is_loading) {
        try {
          setLoadingProgressMap((prev) => ({ ...prev, [modelId]: 5 }));
          await loadModel(activeProvider, modelId);
        } catch (e) {
          console.warn('Richiesta caricamento modello fallita:', e);
        }
      }
    }
  };

  // Find detail for currently selected model
  const currentDetail = modelDetails.find((m) => m.id === selectedModel);
  const isCurrentLoaded = Boolean(currentDetail?.is_loaded);
  const isCurrentLoading = Boolean(
    currentDetail?.is_loading ||
    (selectedModel !== 'default' && loadingProgressMap[selectedModel] !== undefined)
  );
  const currentProgress = selectedModel !== 'default' ? loadingProgressMap[selectedModel] : undefined;

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
        className="flex items-center glass-card border border-border rounded-lg px-2 py-1 text-[11px] gap-1.5 text-fg-muted hover:border-accent/40 hover:text-fg transition shadow-sm cursor-pointer select-none max-w-[200px] sm:max-w-[260px]"
        title={
          selectedModel === 'default'
            ? 'Modello LLM: Default'
            : `Modello LLM: ${selectedModel}${isCurrentLoaded ? ' (Caricato in VRAM)' : isCurrentLoading ? ' (In caricamento...)' : ' (Non caricato)'}`
        }
      >
        <Box size={12} className="text-emerald-400 shrink-0" />
        
        <span className="truncate font-mono text-[11px] text-fg">
          {selectedModel === 'default' ? 'Modello: Default' : selectedModel}
        </span>

        {/* Loaded VRAM dot indicator */}
        {selectedModel !== 'default' && isCurrentLoaded && (
          <span
            className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)] shrink-0"
            title="Caricato in VRAM"
          />
        )}

        {/* Loading spinner with percentage */}
        {isCurrentLoading && (
          <span className="inline-flex items-center gap-1 text-[10px] text-amber-400 font-sans font-semibold shrink-0">
            <Loader2 size={10} className="animate-spin text-amber-400" />
            {currentProgress !== undefined ? `${currentProgress}%` : ''}
          </span>
        )}

        <ChevronDown size={11} className={`text-fg-muted transition-transform shrink-0 ml-auto ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* Popover Dropdown Menu */}
      {isOpen && (
        <div className="absolute bottom-full mb-1.5 left-0 z-50 w-72 sm:w-84 max-h-96 glass-panel border border-border/80 shadow-2xl rounded-xl p-2 flex flex-col backdrop-blur-xl bg-panel/95 animate-in fade-in zoom-in-95 duration-100">
          {/* Search Header */}
          <div className="relative mb-2 shrink-0">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Cerca modello..."
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-panel-header/70 border border-border rounded-lg text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent"
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
                  <span className="truncate">Modello: Default</span>
                </div>
                {selectedModel === 'default' && <Check size={14} className="text-accent shrink-0" />}
              </div>
            )}

            {/* Pinned Favorites Section */}
            {favoriteModels.length > 0 && (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-semibold text-amber-400 uppercase tracking-wider">
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
                  <div className="px-2 pt-1 pb-0.5 text-[10px] font-semibold text-fg-muted uppercase tracking-wider">
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
    const isLoading = Boolean(m.is_loading || loadingProgressMap[m.id] !== undefined);
    const progress = loadingProgressMap[m.id];

    return (
      <div
        key={m.id}
        onClick={() => handleSelect(m.id)}
        className={`group flex items-center justify-between px-2.5 py-1.5 rounded-lg cursor-pointer transition ${
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
              className={isFav ? 'text-amber-400 fill-amber-400' : 'text-fg-muted/40 group-hover:text-fg-muted'}
            />
          </button>

          <span className="font-mono text-[11px] truncate" title={m.id}>
            {m.id}
          </span>
        </div>

        {/* Badges + Selection indicator */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* Loaded in VRAM Badge */}
          {inVram && (
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-sans font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1"
              title="Caricato in VRAM"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.8)]" />
              <span>In VRAM</span>
            </span>
          )}

          {/* Loading Progress Badge */}
          {isLoading && (
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-sans font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30 flex items-center gap-1 animate-pulse"
              title="Caricamento in corso..."
            >
              <Loader2 size={9} className="animate-spin text-amber-400" />
              <span>{progress !== undefined ? `${progress}%` : 'Caricamento...'}</span>
            </span>
          )}

          {/* Vision Modality Badge */}
          {m.is_vision && (
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-sans font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/25 flex items-center gap-0.5"
              title="Supporta visione multimodale"
            >
              <Eye size={9} />
              <span>Vision</span>
            </span>
          )}

          {/* Checkmark if selected */}
          {isSelected && <Check size={13} className="text-accent ml-1" />}
        </div>
      </div>
    );
  }
};
