import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpen, Upload, Trash2, Search, FileText, RefreshCw, Loader2, Brain, Plus, Tag } from 'lucide-react';
import {
  listKbDocuments,
  uploadKbDocument,
  deleteKbDocument,
  getMemories,
  addMemory,
  deleteMemory,
  searchMemories,
  type KbDocument,
  type MemoryItem,
  type MemorySearchResult,
} from '../api';

type Tab = 'facts' | 'docs' | 'search';

export const KnowledgePanel: React.FC = () => {
  const [tab, setTab] = useState<Tab>('facts');
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [facts, setFacts] = useState<MemoryItem[]>([]);
  const [totalFacts, setTotalFacts] = useState<number>(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  // New fact quick add
  const [quickFact, setQuickFact] = useState('');
  const [isAddingFact, setIsAddingFact] = useState(false);

  // Search state
  const [query, setQuery] = useState('');
  const [searchKind, setSearchKind] = useState<string>('all');
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const [docsData, memoriesData] = await Promise.all([
        listKbDocuments().catch(() => []),
        getMemories('fact').catch(() => ({ memories: [], total: 0 })),
      ]);
      setDocs(docsData);
      setFacts(memoriesData.memories);
      setTotalFacts(memoriesData.total);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleFileUpload = async (file: File) => {
    if (!file) return;
    const validExt = ['.md', '.txt', '.pdf'];
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!validExt.includes(ext)) {
      setUploadMsg(`Formato non supportato: ${ext}. Usa .md, .txt o .pdf`);
      setTimeout(() => setUploadMsg(null), 4000);
      return;
    }
    setIsUploading(true);
    setUploadMsg(null);
    try {
      let content: string;
      if (ext === '.pdf') {
        setUploadMsg('PDF: usa il testo estratto o converti in .md/.txt per ora');
        setTimeout(() => setUploadMsg(null), 5000);
        return;
      }
      content = await file.text();
      const res = await uploadKbDocument(file.name, content);
      setUploadMsg(`✓ ${file.name}: ${res.chunks_indexed} chunk indicizzati`);
      await refresh();
    } catch (e: any) {
      setUploadMsg(`Errore: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadMsg(null), 5000);
    }
  };

  const handleDeleteDoc = async (filename: string) => {
    try {
      await deleteKbDocument(filename);
      await refresh();
    } catch (e: any) {
      console.error('Delete document failed', e);
    }
  };

  const handleAddQuickFact = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!quickFact.trim() || isAddingFact) return;
    setIsAddingFact(true);
    try {
      await addMemory(quickFact.trim(), 'fact');
      setQuickFact('');
      await refresh();
    } catch (e) {
      console.error('Add fact failed', e);
    } finally {
      setIsAddingFact(false);
    }
  };

  const handleDeleteFact = async (id: number) => {
    try {
      await deleteMemory(id);
      await refresh();
    } catch (e) {
      console.error('Delete fact failed', e);
    }
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setIsSearching(true);
    try {
      const kindParam = searchKind === 'all' ? undefined : searchKind;
      const res = await searchMemories(query.trim(), kindParam, 8);
      setSearchResults(res);
    } catch {
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-400 text-xs">
          <BookOpen size={14} className="text-purple-400" />
          <span className="font-medium text-slate-300">Memoria & Knowledge</span>
        </div>
        <button onClick={refresh} className="p-1 text-slate-500 hover:text-slate-300 transition rounded" title="Refresh">
          <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5">
        <button
          onClick={() => setTab('facts')}
          className={`flex-1 px-1.5 py-1 rounded-md text-[10px] font-semibold transition flex items-center justify-center gap-1 ${
            tab === 'facts' ? 'bg-purple-950/80 text-purple-300 border border-purple-800/60 shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Brain size={10} />
          Fatti ({totalFacts})
        </button>
        <button
          onClick={() => setTab('docs')}
          className={`flex-1 px-1.5 py-1 rounded-md text-[10px] font-semibold transition flex items-center justify-center gap-1 ${
            tab === 'docs' ? 'bg-slate-800 text-slate-200 shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <FileText size={10} />
          Docs ({docs.length})
        </button>
        <button
          onClick={() => setTab('search')}
          className={`flex-1 px-1.5 py-1 rounded-md text-[10px] font-semibold transition flex items-center justify-center gap-1 ${
            tab === 'search' ? 'bg-blue-950/80 text-blue-300 border border-blue-800/60 shadow-sm' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Search size={10} />
          Cerca
        </button>
      </div>

      {/* 1. FACTS TAB */}
      {tab === 'facts' && (
        <div className="space-y-2.5">
          {/* Quick add */}
          <form onSubmit={handleAddQuickFact} className="flex gap-1.5">
            <input
              type="text"
              value={quickFact}
              onChange={(e) => setQuickFact(e.target.value)}
              placeholder="Aggiungi fatto (es. 'Gateway 192.168.1.1')..."
              className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-2 py-1 text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-purple-500"
            />
            <button
              type="submit"
              disabled={!quickFact.trim() || isAddingFact}
              className="px-2 py-1 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white rounded-lg text-[10px] font-semibold transition flex items-center gap-1"
              title="Aggiungi fatto"
            >
              {isAddingFact ? <Loader2 size={10} className="animate-spin" /> : <Plus size={11} />}
            </button>
          </form>

          {/* Facts list */}
          <div className="max-h-60 overflow-y-auto space-y-1.5 pr-0.5">
            {facts.length === 0 && !isLoading && (
              <p className="text-[11px] text-slate-500 italic py-2 text-center">Nessun fatto memorizzato.</p>
            )}
            {facts.map((f) => (
              <div
                key={f.id}
                className="group flex items-start justify-between gap-1.5 bg-slate-900/60 border border-slate-800/80 rounded-lg p-2 text-[11px] text-slate-300 hover:border-slate-700 transition"
              >
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="leading-snug text-slate-200">{f.content}</p>
                  <div className="flex items-center gap-1 text-[9px] text-slate-500">
                    {f.thread_id && <span className="truncate">Thread: {f.thread_id}</span>}
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteFact(f.id)}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-rose-400 transition shrink-0"
                  title="Elimina fatto"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 2. DOCUMENTS TAB */}
      {tab === 'docs' && (
        <div className="space-y-2">
          {/* Upload */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".md,.txt,.pdf"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg border border-dashed border-slate-700 text-[10px] text-slate-400 hover:border-cyan-500/50 hover:text-cyan-300 transition disabled:opacity-50 cursor-pointer"
          >
            {isUploading ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
            Upload .md / .txt / .pdf
          </button>
          {uploadMsg && <p className="text-[10px] text-slate-400 italic">{uploadMsg}</p>}

          {/* Document list */}
          <div className="max-h-60 overflow-y-auto space-y-1.5 pr-0.5">
            {docs.length === 0 && !isLoading && (
              <p className="text-[11px] text-slate-500 italic py-2 text-center">Nessun documento indicizzato.</p>
            )}
            {docs.map((doc) => (
              <div
                key={doc.filename}
                className="flex items-center justify-between gap-2 bg-slate-900/60 border border-slate-800 rounded-lg px-2.5 py-1.5 group"
              >
                <div className="min-w-0 flex-1 flex items-center gap-1.5">
                  <FileText size={12} className="text-cyan-400 shrink-0" />
                  <span className="text-[11px] font-mono text-slate-300 truncate">{doc.filename}</span>
                  <span className="text-[9px] text-slate-600 shrink-0">{doc.chunks}ch</span>
                </div>
                <button
                  onClick={() => handleDeleteDoc(doc.filename)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-slate-600 hover:text-red-400 transition"
                  title="Elimina documento"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3. SEMANTIC SEARCH TAB */}
      {tab === 'search' && (
        <div className="space-y-2">
          {/* Kind Filter & Search bar */}
          <div className="flex gap-1 items-center">
            <select
              value={searchKind}
              onChange={(e) => setSearchKind(e.target.value)}
              className="bg-slate-900 border border-slate-800 rounded-lg px-1.5 py-1 text-[10px] text-slate-300 focus:outline-none focus:border-blue-500"
            >
              <option value="all">Tutto</option>
              <option value="fact">Solo Fatti</option>
              <option value="kb">Solo KB</option>
            </select>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Cerca per significato (es. Debian, IP)..."
              className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-2 py-1 text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={handleSearch}
              disabled={isSearching || !query.trim()}
              className="px-2 py-1 rounded-lg bg-blue-600/30 border border-blue-500/50 text-blue-300 hover:bg-blue-600/50 transition disabled:opacity-50 cursor-pointer"
            >
              {isSearching ? <Loader2 size={11} className="animate-spin" /> : <Search size={11} />}
            </button>
          </div>

          {/* Search Results */}
          <div className="max-h-60 overflow-y-auto space-y-1.5 pr-0.5">
            {searchResults.map((r) => (
              <div key={r.id} className="bg-slate-900/70 border border-slate-800 rounded-lg p-2 space-y-1">
                <div className="flex items-center justify-between gap-1 text-[10px]">
                  <span
                    className={`px-1.5 py-0.2 rounded text-[9px] font-semibold uppercase ${
                      r.kind === 'fact' ? 'bg-purple-950 text-purple-300 border border-purple-800' : 'bg-cyan-950 text-cyan-300 border border-cyan-800'
                    }`}
                  >
                    {r.kind === 'fact' ? 'Fatto' : 'Documento'}
                  </span>
                  <span className="text-emerald-400 font-mono text-[10px] font-medium">
                    {(r.score * 100).toFixed(0)}% match
                  </span>
                </div>
                <p className="text-[11px] text-slate-300 leading-snug">{r.content}</p>
                {r.metadata?.filename && (
                  <p className="text-[9px] font-mono text-slate-500">File: {r.metadata.filename}</p>
                )}
              </div>
            ))}
            {searchResults.length === 0 && !isSearching && query && (
              <p className="text-xs text-slate-500 italic py-2 text-center">Nessun risultato per "{query}".</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
