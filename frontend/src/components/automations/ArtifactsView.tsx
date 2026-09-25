import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FileText,
  Calendar,
  Star,
  Lock,
  Unlock,
  Trash2,
  Download,
  Copy,
  Check,
  Search,
  Clock,
  RefreshCw,
  Eye,
  Code,
  Sparkles,
  AlertCircle,
  ArrowLeft,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import {
  fetchAllArtifacts,
  getArtifactDetails,
  toggleArtifactFavorite,
  toggleArtifactPreserve,
  deleteArtifact,
  type AutomationArtifact,
} from '../../api';
import { MarkdownRenderer } from '../MarkdownRenderer';

interface ArtifactsViewProps {
  initialArtifactId?: string | null;
  onOpenAutomation?: (autoId: string) => void;
  onFeedback?: (type: 'success' | 'error', text: string) => void;
}

export const ArtifactsView: React.FC<ArtifactsViewProps> = ({
  initialArtifactId,
  onOpenAutomation,
  onFeedback,
}) => {
  const [artifacts, setArtifacts] = useState<AutomationArtifact[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialArtifactId || null);
  const [selectedArtifact, setSelectedArtifact] = useState<AutomationArtifact | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(false);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [automationFilter, setAutomationFilter] = useState<string>('all');
  const [favoriteOnly, setFavoriteOnly] = useState<boolean>(false);
  const [preservedOnly, setPreservedOnly] = useState<boolean>(false);

  // View state
  const [viewMode, setViewMode] = useState<'rendered' | 'raw'>('rendered');
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  const showFeedback = (type: 'success' | 'error', text: string) => {
    setFeedback({ type, text });
    if (onFeedback) onFeedback(type, text);
    setTimeout(() => setFeedback(null), 3500);
  };

  const loadArtifacts = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await fetchAllArtifacts({
        automation_id: automationFilter !== 'all' ? automationFilter : undefined,
        query: searchQuery.trim() || undefined,
        favorite_only: favoriteOnly || undefined,
        preserved_only: preservedOnly || undefined,
        limit: 200,
      });
      setArtifacts(data);

      // Se c'è un initialArtifactId o selectedId, mantienilo, altrimenti su desktop seleziona il primo (su mobile mostra prima la lista)
      if (initialArtifactId && data.some((a) => a.artifact_id === initialArtifactId)) {
        setSelectedId(initialArtifactId);
      } else if (!selectedId && data.length > 0) {
        if (typeof window !== 'undefined' && window.innerWidth >= 768) {
          setSelectedId(data[0].artifact_id);
        }
      }
    } catch (err: any) {
      console.error('Errore caricamento lista artefatti:', err);
      showFeedback('error', 'Impossibile caricare gli artefatti.');
    } finally {
      setIsLoading(false);
    }
  }, [automationFilter, searchQuery, favoriteOnly, preservedOnly, initialArtifactId]);

  useEffect(() => {
    loadArtifacts();
  }, [loadArtifacts]);

  // Caricamento dettaglio artefatto selezionato (con contenuto completo)
  useEffect(() => {
    if (!selectedId) {
      setSelectedArtifact(null);
      return;
    }
    let isCancelled = false;
    setIsLoadingDetail(true);

    getArtifactDetails(selectedId)
      .then((detail) => {
        if (!isCancelled) {
          setSelectedArtifact(detail);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          console.error('Errore caricamento dettaglio artefatto:', err);
          showFeedback('error', 'Impossibile caricare il contenuto dell\'artefatto.');
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsLoadingDetail(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [selectedId]);

  // Toggles
  const handleToggleFavorite = async (artId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      const res = await toggleArtifactFavorite(artId);
      setArtifacts((prev) =>
        prev.map((a) => (a.artifact_id === artId ? { ...a, is_favorite: res.is_favorite } : a))
      );
      if (selectedArtifact && selectedArtifact.artifact_id === artId) {
        setSelectedArtifact({ ...selectedArtifact, is_favorite: res.is_favorite });
      }
    } catch (err: any) {
      showFeedback('error', 'Errore aggiornamento preferito.');
    }
  };

  const handleTogglePreserve = async (artId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      const res = await toggleArtifactPreserve(artId);
      setArtifacts((prev) =>
        prev.map((a) => (a.artifact_id === artId ? { ...a, is_preserved: res.is_preserved } : a))
      );
      if (selectedArtifact && selectedArtifact.artifact_id === artId) {
        setSelectedArtifact({ ...selectedArtifact, is_preserved: res.is_preserved });
      }
      showFeedback(
        'success',
        res.is_preserved ? 'Artefatto protetto da cancellazione' : 'Protezione cancellazione rimossa'
      );
    } catch (err: any) {
      showFeedback('error', 'Errore aggiornamento protezione.');
    }
  };

  const handleDelete = async (artId: string, isPreserved?: boolean) => {
    if (isPreserved) {
      alert('Questo report è protetto da cancellazione (bloccato con lucchetto). Sbloccalo prima di eliminarlo.');
      return;
    }
    if (!confirm('Sei sicuro di voler eliminare definitivamente questo artefatto/report?')) return;
    try {
      await deleteArtifact(artId);
      setArtifacts((prev) => prev.filter((a) => a.artifact_id !== artId));
      if (selectedId === artId) {
        setSelectedId(null);
        setSelectedArtifact(null);
      }
      showFeedback('success', 'Artefatto eliminato.');
    } catch (err: any) {
      showFeedback('error', 'Errore eliminazione artefatto.');
    }
  };

  const handleCopyMarkdown = () => {
    if (!selectedArtifact?.content) return;
    navigator.clipboard.writeText(selectedArtifact.content);
    setCopied(true);
    showFeedback('success', 'Contenuto Markdown copiato negli appunti!');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!selectedArtifact) return;
    const filename = `${(selectedArtifact.name || 'report').replace(/\s+/g, '_')}.md`;
    const blob = new Blob([selectedArtifact.content || ''], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showFeedback('success', `Scaricato ${filename}`);
  };

  // Extract distinct automation names for dropdown filter
  const automationOptions = useMemo(() => {
    const map = new Map<string, string>();
    artifacts.forEach((a) => {
      if (a.automation_id && !map.has(a.automation_id)) {
        map.set(a.automation_id, a.automation_name || a.automation_id);
      }
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [artifacts]);

  // Group artifacts chronologically: "Oggi", "Ieri", "Ultimi 7 Giorni", "Questo Mese", "Precedenti"
  const groupedArtifacts = useMemo(() => {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startOfYesterday = startOfToday - 86400000;
    const startOf7DaysAgo = startOfToday - 7 * 86400000;
    const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1).getTime();

    const groups: Record<'today' | 'yesterday' | 'last7Days' | 'thisMonth' | 'older', AutomationArtifact[]> = {
      today: [],
      yesterday: [],
      last7Days: [],
      thisMonth: [],
      older: [],
    };

    artifacts.forEach((art) => {
      const d = art.created_at ? new Date(art.created_at).getTime() : 0;
      if (d >= startOfToday) {
        groups.today.push(art);
      } else if (d >= startOfYesterday) {
        groups.yesterday.push(art);
      } else if (d >= startOf7DaysAgo) {
        groups.last7Days.push(art);
      } else if (d >= firstOfMonth) {
        groups.thisMonth.push(art);
      } else {
        groups.older.push(art);
      }
    });

    return [
      { key: 'today', title: 'Oggi', items: groups.today },
      { key: 'yesterday', title: 'Ieri', items: groups.yesterday },
      { key: 'last7Days', title: 'Ultimi 7 Giorni', items: groups.last7Days },
      { key: 'thisMonth', title: 'Questo Mese', items: groups.thisMonth },
      { key: 'older', title: 'Precedenti', items: groups.older },
    ].filter((g) => g.items.length > 0);
  }, [artifacts]);

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent text-fg overflow-hidden relative font-sans">
      {/* Top Filter & Search Bar: Visible on desktop always, on mobile only when browsing the master list */}
      <div className={`p-2.5 sm:p-3 border-b border-border bg-panel-header/35 backdrop-blur-md flex flex-wrap items-center justify-between gap-2.5 shrink-0 ${
        selectedId ? 'hidden md:flex' : 'flex'
      }`}>
        <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-md">
          <div className="relative w-full">
            <Search className="absolute left-3 top-2.5 text-fg-muted" size={14} />
            <input
              type="text"
              placeholder="Cerca artefatto, report o automazione..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-panel border border-border/80 pl-8 pr-3 py-1.5 rounded-xl text-xs text-fg focus:outline-none focus:border-accent"
            />
          </div>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap text-xs">
          {/* Automation Filter */}
          <select
            value={automationFilter}
            onChange={(e) => setAutomationFilter(e.target.value)}
            className="bg-panel border border-border/80 px-2 py-1.5 rounded-xl text-xs text-fg focus:outline-none focus:border-accent max-w-[170px] sm:max-w-xs truncate"
          >
            <option value="all">Tutte le automazioni ({artifacts.length})</option>
            {automationOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.name}
              </option>
            ))}
          </select>

          {/* Favorite Toggle */}
          <button
            onClick={() => setFavoriteOnly(!favoriteOnly)}
            className={`px-2 py-1.5 rounded-xl border flex items-center gap-1 transition cursor-pointer ${
              favoriteOnly
                ? 'bg-amber-500/15 border-amber-500/40 text-amber-300 font-semibold'
                : 'bg-panel border-border/80 text-fg-muted hover:text-fg'
            }`}
            title="Mostra solo preferiti con stella"
          >
            <Star size={13} className={favoriteOnly ? 'fill-amber-400 text-amber-400' : ''} />
            <span className="hidden sm:inline">Preferiti</span>
          </button>

          {/* Preserved Toggle */}
          <button
            onClick={() => setPreservedOnly(!preservedOnly)}
            className={`px-2 py-1.5 rounded-xl border flex items-center gap-1 transition cursor-pointer ${
              preservedOnly
                ? 'bg-indigo-500/15 border-indigo-500/40 text-indigo-300 font-semibold'
                : 'bg-panel border-border/80 text-fg-muted hover:text-fg'
            }`}
            title="Mostra solo artefatti protetti da cancellazione"
          >
            <Lock size={13} className={preservedOnly ? 'text-indigo-400' : ''} />
            <span className="hidden sm:inline">Protetti</span>
          </button>

          <button
            onClick={loadArtifacts}
            disabled={isLoading}
            className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-xl border border-border transition cursor-pointer"
            title="Aggiorna lista"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Action message toast */}
      {feedback && (
        <div
          className={`absolute top-16 right-6 z-50 px-3 py-1.5 rounded-xl text-xs font-medium flex items-center gap-2 shadow-lg animate-in fade-in duration-200 ${
            feedback.type === 'success'
              ? 'bg-emerald-950/90 text-emerald-200 border border-emerald-800'
              : 'bg-rose-950/90 text-rose-200 border border-rose-800'
          }`}
        >
          {feedback.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
          <span>{feedback.text}</span>
        </div>
      )}

      {/* Main Split Layout: Responsive master-detail */}
      <div className="flex-1 flex overflow-hidden w-full">
        {/* Left Pane: Grouped Artifacts Master List (Full width on mobile when no selection or in list mode) */}
        <div className={`w-full md:w-80 lg:w-96 border-r border-border bg-panel-header/10 flex flex-col overflow-hidden shrink-0 ${
          selectedId ? 'hidden md:flex' : 'flex'
        }`}>
          <div className="p-3 border-b border-border/60 bg-panel/30 flex items-center justify-between text-xs text-fg-muted">
            <span>{artifacts.length} artefatti archiviati</span>
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="text-[11px] text-accent hover:underline cursor-pointer"
              >
                Azzera ricerca
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-border/40 p-2 space-y-4">
            {groupedArtifacts.length === 0 ? (
              <div className="text-center py-12 px-4">
                <FileText className="mx-auto text-fg-muted/40 mb-3" size={32} />
                <p className="text-xs text-fg-muted font-medium">Nessun artefatto trovato</p>
                <p className="text-[11px] text-fg-muted/70 mt-1">
                  I report generati dalle automazioni (come briefing o audit) compariranno qui automaticamente.
                </p>
              </div>
            ) : (
              groupedArtifacts.map((group) => (
                <div key={group.key} className="space-y-1.5 pt-1">
                  <div className="flex items-center gap-1.5 px-2 text-[11px] font-bold text-fg-muted uppercase tracking-wider">
                    <Calendar size={12} className="text-accent/70" />
                    <span>{group.title}</span>
                    <span className="text-[10px] text-fg-muted/60 font-normal">({group.items.length})</span>
                  </div>

                  <div className="space-y-1">
                    {group.items.map((art) => {
                      const isSelected = selectedId === art.artifact_id;
                      const timeStr = art.created_at
                        ? new Date(art.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        : '';

                      return (
                        <div
                          key={art.artifact_id}
                          onClick={() => setSelectedId(art.artifact_id)}
                          className={`p-2.5 rounded-xl border text-xs transition cursor-pointer flex flex-col gap-1.5 relative group ${
                            isSelected
                              ? 'bg-accent/15 border-accent text-fg shadow-sm'
                              : 'bg-panel/60 hover:bg-panel border-border/60 hover:border-border text-fg-muted hover:text-fg'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="font-semibold text-xs text-fg leading-snug line-clamp-2">
                              {art.title || art.name}
                            </span>
                            <div className="flex items-center gap-1 shrink-0">
                              {/* Star icon button */}
                              <button
                                onClick={(e) => handleToggleFavorite(art.artifact_id, e)}
                                className={`p-1 rounded-md transition hover:scale-110 cursor-pointer ${
                                  art.is_favorite
                                    ? 'text-amber-400'
                                    : 'text-fg-muted/40 hover:text-amber-400'
                                }`}
                                title={art.is_favorite ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'}
                              >
                                <Star size={13} className={art.is_favorite ? 'fill-amber-400' : ''} />
                              </button>

                              {/* Lock icon button */}
                              <button
                                onClick={(e) => handleTogglePreserve(art.artifact_id, e)}
                                className={`p-1 rounded-md transition hover:scale-110 cursor-pointer ${
                                  art.is_preserved
                                    ? 'text-indigo-400'
                                    : 'text-fg-muted/40 hover:text-indigo-400'
                                }`}
                                title={art.is_preserved ? 'Protetto da pulizia' : 'Blocca per non eliminare'}
                              >
                                {art.is_preserved ? <Lock size={13} /> : <Unlock size={13} />}
                              </button>
                            </div>
                          </div>

                          <div className="flex items-center justify-between text-[11px] text-fg-muted mt-0.5">
                            <span className="px-2 py-0.5 rounded-md bg-bg/80 border border-border/50 text-[10px] truncate max-w-[170px]">
                              {art.automation_name || art.automation_id || 'Automazione'}
                            </span>
                            <span className="flex items-center gap-1 text-[10px]">
                              <Clock size={10} />
                              {timeStr}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Pane: Artifact Detail View (Full width on mobile when artifact is selected, or full screen when toggled) */}
        <div
          className={
            isFullscreen
              ? 'fixed inset-0 z-50 flex flex-col p-2 sm:p-5 overflow-hidden animate-in fade-in duration-200'
              : selectedId
              ? 'flex-1 flex flex-col bg-transparent overflow-hidden'
              : 'hidden md:flex flex-1 flex-col bg-transparent overflow-hidden'
          }
          style={
            isFullscreen
              ? {
                  backgroundColor: 'var(--panel)',
                  backdropFilter: 'blur(30px)',
                  WebkitBackdropFilter: 'blur(30px)',
                }
              : undefined
          }
        >
          {isLoadingDetail ? (
            <div className="flex-1 flex items-center justify-center text-fg-muted gap-2 text-xs p-6">
              <RefreshCw size={18} className="animate-spin text-accent" />
              <span>Caricamento anteprima artefatto...</span>
            </div>
          ) : selectedArtifact ? (
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Detail Header with Back Button on Mobile */}
              <div className="p-3 sm:p-4 border-b border-border bg-panel/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap mb-1.5">
                    {/* Mobile Back Button to return to list */}
                    <button
                      onClick={() => {
                        setIsFullscreen(false);
                        setSelectedId(null);
                      }}
                      className="md:hidden flex items-center gap-1 px-2.5 py-1 rounded-lg bg-panel border border-border text-xs text-fg hover:text-accent font-medium transition cursor-pointer shadow-sm shrink-0"
                      title="Torna all'elenco dei report"
                    >
                      <ArrowLeft size={13} />
                      <span>Elenco</span>
                    </button>

                    {onOpenAutomation && selectedArtifact.automation_id ? (
                      <button
                        onClick={() => onOpenAutomation(selectedArtifact.automation_id!)}
                        className="px-2 py-0.5 rounded-md bg-accent/15 hover:bg-accent/25 border border-accent/30 text-accent font-semibold text-[11px] flex items-center gap-1 transition cursor-pointer truncate max-w-[140px] sm:max-w-[180px]"
                        title="Apri automazione"
                      >
                        <Sparkles size={11} className="shrink-0" />
                        <span className="truncate">{selectedArtifact.automation_name || selectedArtifact.automation_id}</span>
                      </button>
                    ) : (
                      <span className="px-2 py-0.5 rounded-md bg-accent/15 border border-accent/30 text-accent font-semibold text-[11px] flex items-center gap-1 truncate max-w-[140px] sm:max-w-[180px]">
                        <Sparkles size={11} className="shrink-0" />
                        <span className="truncate">{selectedArtifact.automation_name || selectedArtifact.automation_id || 'Report'}</span>
                      </span>
                    )}
                    <span className="text-[11px] text-fg-muted flex items-center gap-1 shrink-0">
                      <Calendar size={11} />
                      {selectedArtifact.created_at
                        ? new Date(selectedArtifact.created_at).toLocaleDateString()
                        : 'N/A'}
                    </span>
                    {selectedArtifact.is_preserved && (
                      <span className="px-1.5 py-0.5 rounded-md bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[10px] flex items-center gap-1 shrink-0">
                        <Lock size={10} /> Protetto
                      </span>
                    )}
                  </div>
                  <h2 className="text-sm sm:text-lg font-bold text-fg leading-tight truncate">
                    {selectedArtifact.title || selectedArtifact.name}
                  </h2>
                </div>

                {/* Actions Toolbar */}
                <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
                  {/* Mode Toggle (Rendered vs Raw) */}
                  <div className="bg-panel border border-border rounded-xl p-0.5 flex text-xs shrink-0">
                    <button
                      onClick={() => setViewMode('rendered')}
                      className={`px-2 py-1 rounded-lg transition flex items-center gap-1 cursor-pointer ${
                        viewMode === 'rendered' ? 'bg-accent text-white font-medium shadow-sm' : 'text-fg-muted hover:text-fg'
                      }`}
                    >
                      <Eye size={12} />
                      <span className="text-[11px]">Anteprima</span>
                    </button>
                    <button
                      onClick={() => setViewMode('raw')}
                      className={`px-2 py-1 rounded-lg transition flex items-center gap-1 cursor-pointer ${
                        viewMode === 'raw' ? 'bg-accent text-white font-medium shadow-sm' : 'text-fg-muted hover:text-fg'
                      }`}
                    >
                      <Code size={12} />
                      <span className="text-[11px]">Raw</span>
                    </button>
                  </div>

                  {/* Fullscreen Button */}
                  <button
                    onClick={() => setIsFullscreen(!isFullscreen)}
                    className="p-1.5 rounded-xl border border-border/80 bg-panel hover:bg-panel-header text-fg-muted hover:text-fg text-xs transition cursor-pointer"
                    title={isFullscreen ? 'Riduci visualizzazione' : 'Schermo intero'}
                  >
                    {isFullscreen ? <Minimize2 size={13} className="text-accent" /> : <Maximize2 size={13} />}
                  </button>

                  {/* Copy Button */}
                  <button
                    onClick={handleCopyMarkdown}
                    className="px-2.5 py-1.5 rounded-xl border border-border/80 bg-panel hover:bg-panel-header text-xs text-fg font-medium flex items-center gap-1 transition cursor-pointer"
                    title="Copia Markdown negli appunti"
                  >
                    {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                    <span className="hidden sm:inline">{copied ? 'Copiato!' : 'Copia'}</span>
                  </button>

                  {/* Download Button */}
                  <button
                    onClick={handleDownload}
                    className="px-2.5 py-1.5 rounded-xl border border-border/80 bg-panel hover:bg-panel-header text-xs text-fg font-medium flex items-center gap-1 transition cursor-pointer"
                    title="Scarica file su disco locale"
                  >
                    <Download size={13} />
                    <span className="hidden sm:inline">Download</span>
                  </button>

                  {/* Delete Button */}
                  <button
                    onClick={() => handleDelete(selectedArtifact.artifact_id, selectedArtifact.is_preserved)}
                    disabled={selectedArtifact.is_preserved}
                    className={`p-1.5 rounded-xl border transition ${
                      selectedArtifact.is_preserved
                        ? 'border-border/40 text-fg-muted/40 cursor-not-allowed'
                        : 'border-rose-900/60 text-rose-400 hover:bg-rose-950/40 hover:border-rose-700 cursor-pointer'
                    }`}
                    title={selectedArtifact.is_preserved ? 'Sblocca prima il lucchetto per eliminare' : 'Elimina artefatto'}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Detail Content Viewer: Optimized padding & scroll for mobile */}
              <div className={`flex-1 overflow-y-auto p-3 sm:p-6 w-full mx-auto ${isFullscreen ? 'max-w-7xl' : 'max-w-5xl'}`}>
                {viewMode === 'rendered' ? (
                  <div className="bg-panel/40 border border-border/80 rounded-xl sm:rounded-2xl p-4 sm:p-6 shadow-sm overflow-x-auto break-words">
                    <MarkdownRenderer content={selectedArtifact.content || '*Nessun contenuto nel report.*'} />
                  </div>
                ) : (
                  <pre className="font-mono text-xs p-4 sm:p-6 bg-black/60 border border-border/80 rounded-xl sm:rounded-2xl overflow-x-auto text-fg-muted whitespace-pre-wrap select-all leading-relaxed">
                    {selectedArtifact.content || '*Vuoto*'}
                  </pre>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-6 sm:p-8 text-fg-muted">
              <FileText className="text-fg-muted/30 mb-3" size={48} />
              <h3 className="text-sm font-semibold text-fg">Nessun artefatto selezionato</h3>
              <p className="text-xs text-fg-muted mt-1 max-w-sm">
                Seleziona un report o documento dalla colonna a sinistra per leggerne il testo formattato, scaricarlo o copiarne il contenuto.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
