import React, { useEffect, useState } from 'react';
import { ArrowLeft, Calendar, Check, Code, Copy, Download, Eye, FileText, Lock, Maximize2, Minimize2, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import type { AutomationArtifact } from '../../../api/artifacts';
import { useCopyFeedback } from '../../../hooks/useCopyFeedback';
import type { Notify } from '../../../hooks/useFeedback';
import { MarkdownRenderer } from '../../MarkdownRenderer';

interface ArtifactDetailProps {
  artifact: AutomationArtifact | null;
  isLoading: boolean;
  /** C'è un artefatto selezionato: su mobile il dettaglio prende il posto dell'elenco. */
  hasSelection: boolean;
  onBack: () => void;
  onDelete: (artifact: AutomationArtifact) => void;
  notify: Notify;
}

const toolButton =
  'px-2.5 py-1.5 rounded-xl border border-border/80 bg-panel hover:bg-panel-header text-xs text-fg font-medium flex items-center gap-1 transition cursor-pointer';

function downloadMarkdown(artifact: AutomationArtifact): string {
  const filename = `${(artifact.name || 'report').replace(/\s+/g, '_')}.md`;
  const url = URL.createObjectURL(new Blob([artifact.content || ''], { type: 'text/markdown;charset=utf-8;' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return filename;
}

/** Contenuto di un artefatto (anteprima Markdown o testo grezzo) con copia, download, schermo intero ed eliminazione. */
export const ArtifactDetail: React.FC<ArtifactDetailProps> = ({ artifact, isLoading, hasSelection, onBack, onDelete, notify }) => {
  const [viewMode, setViewMode] = useState<'rendered' | 'raw'>('rendered');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const { copied, copy } = useCopyFeedback();

  useEffect(() => {
    if (!isFullscreen) return;
    const handleKeyDown = (e: KeyboardEvent) => e.key === 'Escape' && setIsFullscreen(false);
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  const containerClass = isFullscreen
    ? 'fixed inset-0 z-50 flex flex-col p-2 sm:p-5 overflow-hidden animate-in fade-in duration-200'
    : `${hasSelection ? 'flex' : 'hidden md:flex'} flex-1 flex-col bg-transparent overflow-hidden`;

  return (
    <div
      className={containerClass}
      style={isFullscreen ? { backgroundColor: 'var(--panel)', backdropFilter: 'blur(30px)', WebkitBackdropFilter: 'blur(30px)' } : undefined}
    >
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-fg-muted gap-2 text-xs p-6">
          <RefreshCw size={18} className="animate-spin text-accent" />
          <span>Caricamento anteprima artefatto...</span>
        </div>
      ) : artifact ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="p-3 sm:p-4 border-b border-border bg-panel/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap mb-1.5">
                <button
                  onClick={() => {
                    setIsFullscreen(false);
                    onBack();
                  }}
                  className="md:hidden flex items-center gap-1 px-2.5 py-1 rounded-lg bg-panel border border-border text-xs text-fg hover:text-accent font-medium transition cursor-pointer shadow-sm shrink-0"
                  title="Torna all'elenco dei report"
                >
                  <ArrowLeft size={13} />
                  <span>Elenco</span>
                </button>
                <span className="px-2 py-0.5 rounded-md bg-accent/15 border border-accent/30 text-accent font-semibold text-[11px] flex items-center gap-1 truncate max-w-[140px] sm:max-w-[180px]">
                  <Sparkles size={11} className="shrink-0" />
                  <span className="truncate">{artifact.automation_name || artifact.automation_id || 'Report'}</span>
                </span>
                <span className="text-[11px] text-fg-muted flex items-center gap-1 shrink-0">
                  <Calendar size={11} />
                  {artifact.created_at ? new Date(artifact.created_at).toLocaleDateString() : 'N/A'}
                </span>
                {artifact.is_preserved && (
                  <span className="px-1.5 py-0.5 rounded-md bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[10px] flex items-center gap-1 shrink-0">
                    <Lock size={10} /> Protetto
                  </span>
                )}
              </div>
              <h2 className="text-sm sm:text-lg font-bold text-fg leading-tight truncate">{artifact.title || artifact.name}</h2>
            </div>

            <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
              <div className="bg-panel border border-border rounded-xl p-0.5 flex text-xs shrink-0">
                {(
                  [
                    ['rendered', Eye, 'Anteprima'],
                    ['raw', Code, 'Raw'],
                  ] as const
                ).map(([mode, Icon, label]) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-2 py-1 rounded-lg transition flex items-center gap-1 cursor-pointer ${
                      viewMode === mode ? 'bg-accent text-white font-medium shadow-sm' : 'text-fg-muted hover:text-fg'
                    }`}
                  >
                    <Icon size={12} />
                    <span className="text-[11px]">{label}</span>
                  </button>
                ))}
              </div>

              <button
                onClick={() => setIsFullscreen(!isFullscreen)}
                className="p-1.5 rounded-xl border border-border/80 bg-panel hover:bg-panel-header text-fg-muted hover:text-fg text-xs transition cursor-pointer"
                title={isFullscreen ? 'Riduci visualizzazione' : 'Schermo intero'}
              >
                {isFullscreen ? <Minimize2 size={13} className="text-accent" /> : <Maximize2 size={13} />}
              </button>

              <button
                onClick={async () => {
                  if (!artifact.content) return;
                  await copy(artifact.content);
                  notify('success', 'Contenuto Markdown copiato negli appunti!');
                }}
                className={toolButton}
                title="Copia Markdown negli appunti"
              >
                {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                <span className="hidden sm:inline">{copied ? 'Copiato!' : 'Copia'}</span>
              </button>

              <button
                onClick={() => notify('success', `Scaricato ${downloadMarkdown(artifact)}`)}
                className={toolButton}
                title="Scarica file su disco locale"
              >
                <Download size={13} />
                <span className="hidden sm:inline">Download</span>
              </button>

              <button
                onClick={() => onDelete(artifact)}
                disabled={artifact.is_preserved}
                className={`p-1.5 rounded-xl border transition ${
                  artifact.is_preserved
                    ? 'border-border/40 text-fg-muted/40 cursor-not-allowed'
                    : 'border-rose-900/60 text-rose-400 hover:bg-rose-950/40 hover:border-rose-700 cursor-pointer'
                }`}
                title={artifact.is_preserved ? 'Sblocca prima il lucchetto per eliminare' : 'Elimina artefatto'}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>

          <div className={`flex-1 overflow-y-auto p-3 sm:p-6 w-full mx-auto ${isFullscreen ? 'max-w-7xl' : 'max-w-5xl'}`}>
            {viewMode === 'rendered' ? (
              <div className="bg-panel/40 border border-border/80 rounded-xl sm:rounded-2xl p-4 sm:p-6 shadow-sm overflow-x-auto break-words">
                <MarkdownRenderer content={artifact.content || '*Nessun contenuto nel report.*'} />
              </div>
            ) : (
              <pre className="font-mono text-xs p-4 sm:p-6 bg-black/60 border border-border/80 rounded-xl sm:rounded-2xl overflow-x-auto text-fg-muted whitespace-pre-wrap select-all leading-relaxed">
                {artifact.content || '*Vuoto*'}
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
  );
};
