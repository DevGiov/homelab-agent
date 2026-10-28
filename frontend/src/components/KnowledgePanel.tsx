import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpen, FileText, Loader2, RefreshCw, Search, Trash2, Upload } from 'lucide-react';
import { deleteKbDocument, listKbDocuments, searchKb, uploadKbDocument, type KbDocument, type KbSearchResult } from '../api/kb';
import { formatApiError } from '../utils/error';

type Tab = 'docs' | 'search';

const SUPPORTED = ['.md', '.txt', '.pdf'];

/** Knowledge base: documenti caricati e ricerca per significato nei loro passaggi. I fatti stanno nella vista Memoria. */
export const KnowledgePanel: React.FC = () => {
  const [tab, setTab] = useState<Tab>('docs');
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<KbSearchResult[]>([]);
  const [searched, setSearched] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      setDocs(await listKbDocuments());
    } catch {
      setDocs([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleFileUpload = async (file: File) => {
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!SUPPORTED.includes(ext)) {
      setUploadMsg('Formato non supportato. Usa file .md, .txt o .pdf.');
      return;
    }
    setIsUploading(true);
    setUploadMsg(null);
    try {
      const res = await uploadKbDocument(file);
      setUploadMsg(`Documento caricato: ${res.chunks_indexed} chunk indicizzati.`);
      await refresh();
    } catch (e) {
      setUploadMsg(`Errore: ${formatApiError(e)}`);
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadMsg(null), 5000);
    }
  };

  const handleDeleteDoc = async (filename: string) => {
    try {
      await deleteKbDocument(filename);
      await refresh();
    } catch (e) {
      setUploadMsg(`Errore: ${formatApiError(e)}`);
    }
  };

  const handleSearch = async () => {
    const text = query.trim();
    if (!text) return;
    setIsSearching(true);
    try {
      setResults(await searchKb(text, 8));
    } catch {
      setResults([]);
    } finally {
      setSearched(text);
      setIsSearching(false);
    }
  };

  const tabClass = (active: boolean) =>
    `flex-1 px-1.5 py-1 rounded-md text-[10px] font-semibold transition flex items-center justify-center gap-1 cursor-pointer ${
      active ? 'bg-accent/20 text-accent border border-accent/30 shadow-sm' : 'text-fg-muted hover:text-fg'
    }`;

  return (
    <div className="glass-card border border-border rounded-xl p-3.5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-fg-muted text-xs">
          <BookOpen size={14} className="text-accent" />
          <span className="font-medium text-fg">Knowledge base</span>
        </div>
        <button onClick={refresh} className="p-1 text-fg-muted hover:text-fg transition rounded cursor-pointer" title="Aggiorna">
          <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex gap-1 bg-panel rounded-lg p-0.5 border border-border/60">
        <button onClick={() => setTab('docs')} className={tabClass(tab === 'docs')}>
          <FileText size={10} />
          Documenti ({docs.length})
        </button>
        <button onClick={() => setTab('search')} className={tabClass(tab === 'search')}>
          <Search size={10} />
          Cerca
        </button>
      </div>

      {tab === 'docs' && (
        <div className="space-y-2">
          <input
            ref={fileInputRef}
            type="file"
            accept={SUPPORTED.join(',')}
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg border border-dashed border-border text-[10px] text-fg-muted hover:border-accent hover:text-accent transition disabled:opacity-50 cursor-pointer"
          >
            {isUploading ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
            Upload .md / .txt / .pdf
          </button>
          {uploadMsg && <p className="text-[10px] text-fg-muted italic">{uploadMsg}</p>}

          <div className="max-h-60 overflow-y-auto space-y-1.5 pr-0.5 custom-scrollbar">
            {docs.length === 0 && !isLoading && <p className="text-[11px] text-fg-muted italic py-2 text-center">Nessun documento indicizzato.</p>}
            {docs.map((doc) => (
              <div key={doc.filename} className="flex items-center justify-between gap-2 bg-panel-header/50 border border-border rounded-lg px-2.5 py-1.5 group">
                <div className="min-w-0 flex-1 flex items-center gap-1.5">
                  <FileText size={12} className="text-accent shrink-0" />
                  <span className="text-[11px] font-mono text-fg truncate">{doc.filename}</span>
                  <span className="text-[9px] text-fg-muted shrink-0">{doc.chunks}ch</span>
                </div>
                <button
                  onClick={() => handleDeleteDoc(doc.filename)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-fg-muted hover:text-rose-400 transition cursor-pointer"
                  title="Elimina documento"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'search' && (
        <div className="space-y-2">
          <div className="flex gap-1 items-center">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Cerca nei documenti per significato…"
              className="flex-1 bg-input-bg border border-input-border rounded-lg px-2 py-1 text-[11px] text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent"
            />
            <button
              onClick={handleSearch}
              disabled={isSearching || !query.trim()}
              className="px-2 py-1 rounded-lg bg-accent/20 border border-accent/40 text-accent hover:bg-accent/30 transition disabled:opacity-50 cursor-pointer"
              title="Cerca"
            >
              {isSearching ? <Loader2 size={11} className="animate-spin" /> : <Search size={11} />}
            </button>
          </div>

          <div className="max-h-60 overflow-y-auto space-y-1.5 pr-0.5 custom-scrollbar">
            {results.map((r) => (
              <div key={r.filename} className="bg-panel-header/50 border border-border rounded-lg p-2 space-y-1">
                <div className="flex items-center justify-between gap-1 text-[10px]">
                  <span className="font-mono text-fg truncate">{r.filename}</span>
                  <span className="text-fg-muted tabular-nums shrink-0">{Math.round(r.chunks[0].score * 100)}%</span>
                </div>
                {r.chunks.slice(0, 2).map((c, i) => (
                  <p key={i} className="text-[11px] text-fg-muted leading-snug line-clamp-3">
                    {c.content}
                  </p>
                ))}
              </div>
            ))}
            {results.length === 0 && !isSearching && searched && (
              <p className="text-xs text-fg-muted italic py-2 text-center">Nessun risultato per "{searched}".</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
