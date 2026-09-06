import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Bot,
  User,
  Wrench,
  Sparkles,
  AlertTriangle,
  Play,
  Menu,
  Activity,
  Brain,
  Box,
  EyeOff,
  Globe,
  Square,
  Pause,
  Zap,
  Copy,
  Check,
  Pencil,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Paperclip,
  Image as ImageIcon,
  X,
  Maximize2,
} from 'lucide-react';
import { type FormattedMessage, type AgentMode, getProviders, getProviderModelsWithDetails, fileToDataUrl, type ModelDetail } from './api';
import { PlanViewer } from './components/PlanViewer';
import { ExecutionTraceViewer } from './components/ExecutionTraceViewer';
import { MarkdownRenderer } from './components/MarkdownRenderer';
import ReasoningBlock from './components/ReasoningBlock';
import { ThemeQuickSelector } from './components/ThemeQuickSelector';

interface ChatProps {
  currentThreadId: string | null;
  currentThreadTitle?: string | null;
  messages: FormattedMessage[];
  onSendMessage: (
    input: string,
    mode: AgentMode | undefined,
    execute: boolean,
    reasoningBudget?: number,
    model?: string,
    incognito?: boolean,
    webSearch?: boolean,
    images?: string[]
  ) => Promise<void>;
  onRegenerate?: (assistantMsgId: string) => Promise<void> | void;
  onEditPrompt?: (
    userMsgId: string,
    newContent: string,
    mode?: AgentMode,
    model?: string,
    reasoningBudget?: number
  ) => Promise<void> | void;
  onSwitchVersion?: (messageId: string, targetIndex: number) => void;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  isPaused?: boolean;
  isLoading: boolean;
  error: string | null;
  onClearError: () => void;
  onOpenMobileSidebar?: () => void;
  onOpenMobileToolLog?: () => void;
}

export const Chat: React.FC<ChatProps> = ({
  currentThreadId,
  currentThreadTitle,
  messages,
  onSendMessage,
  onRegenerate,
  onEditPrompt,
  onSwitchVersion,
  onStop,
  onPause,
  onResume,
  isPaused = false,
  isLoading,
  error,
  onClearError,
  onOpenMobileSidebar,
  onOpenMobileToolLog,
}) => {
  const [input, setInput] = useState('');
  const [selectedMode, setSelectedMode] = useState<AgentMode | 'auto'>('auto');
  const [execute, setExecute] = useState<boolean>(true);
  const [reasoningBudget, setReasoningBudget] = useState<number | undefined>(undefined);
  const [selectedModel, setSelectedModel] = useState<string>('default');
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [isIncognito, setIsIncognito] = useState<boolean>(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState<boolean>(false);

  // Copy & Inline Edit State
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editPromptText, setEditPromptText] = useState<string>('');
  const [editPromptMode, setEditPromptMode] = useState<AgentMode | 'auto'>('auto');
  const [editPromptModel, setEditPromptModel] = useState<string>('default');
  const [editPromptBudget, setEditPromptBudget] = useState<number | undefined>(undefined);

  // Vision & Multimodal State
  interface PendingImage {
    id: string;
    dataUrl: string;
    name: string;
    file?: File;
  }
  const [modelDetails, setModelDetails] = useState<ModelDetail[]>([]);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getProviders()
      .then((data) => {
        const activeProv = data.active_provider;
        if (activeProv) {
          getProviderModelsWithDetails(activeProv)
            .then((details) => {
              setModelDetails(details);
              setAvailableModels(details.map((d) => d.id));
            })
            .catch((err) => console.warn('Errore caricamento modelli chat:', err));
        }
      })
      .catch((err) => console.warn('Errore caricamento provider chat:', err));
  }, []);

  const isModelVision = (modelId: string): boolean => {
    const found = modelDetails.find((d) => d.id === modelId);
    if (found) return found.is_vision;
    return /qwen3\.6|vl|vision|llava|pixtral|gemma-4/i.test(modelId);
  };

  const processImageFiles = async (files: FileList | File[]) => {
    const newImgs: PendingImage[] = [];
    for (const file of Array.from(files)) {
      if (!file.type.startsWith('image/')) continue;
      try {
        const dataUrl = await fileToDataUrl(file);
        newImgs.push({
          id: `img_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          dataUrl,
          name: file.name,
          file,
        });
      } catch (e) {
        console.warn('Errore lettura immagine:', e);
      }
    }
    if (newImgs.length > 0) {
      setPendingImages((prev) => [...prev, ...newImgs]);
    }
  };

  const removePendingImage = (id: string) => {
    setPendingImages((prev) => prev.filter((img) => img.id !== id));
  };

  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const imageFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          const file = items[i].getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length > 0) {
        processImageFiles(imageFiles);
      }
    };

    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, []);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processImageFiles(e.dataTransfer.files);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, pendingImages]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if ((!input.trim() && pendingImages.length === 0) || isLoading) return;

    const modeToPass = selectedMode === 'auto' ? undefined : selectedMode;
    const modelToPass = selectedModel === 'default' ? undefined : selectedModel;
    const imagesToSend = pendingImages.map((img) => img.dataUrl);

    onSendMessage(
      input.trim(),
      modeToPass,
      execute,
      reasoningBudget,
      modelToPass,
      isIncognito,
      webSearchEnabled,
      imagesToSend.length > 0 ? imagesToSend : undefined
    );
    setInput('');
    setPendingImages([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleCopy = (text: string, id: string) => {
    if (!text) return;
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text);
    } else {
      const el = document.createElement('textarea');
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
    setCopiedId(id);
    setTimeout(() => {
      setCopiedId((curr) => (curr === id ? null : curr));
    }, 2000);
  };

  const startEditing = (msg: FormattedMessage) => {
    setEditingMsgId(msg.id);
    setEditPromptText(msg.content);
    setEditPromptMode((msg.mode as AgentMode) || selectedMode || 'auto');
    setEditPromptModel(msg.model || selectedModel || 'default');
    setEditPromptBudget(msg.reasoningBudget);
  };

  const cancelEditing = () => {
    setEditingMsgId(null);
    setEditPromptText('');
  };

  const submitEditing = (msgId: string) => {
    if (!editPromptText.trim() || !onEditPrompt) return;
    const modeToPass = editPromptMode === 'auto' ? undefined : editPromptMode;
    const modelToPass = editPromptModel === 'default' ? undefined : editPromptModel;
    onEditPrompt(msgId, editPromptText.trim(), modeToPass, modelToPass, editPromptBudget);
    setEditingMsgId(null);
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="flex-1 flex flex-col h-full bg-transparent text-fg overflow-hidden relative"
    >
      {/* Drag & Drop Visual Overlay */}
      {isDraggingOver && (
        <div className="absolute inset-0 z-40 bg-accent/20 backdrop-blur-xs border-2 border-dashed border-accent flex flex-col items-center justify-center pointer-events-none transition-all duration-150">
          <div className="p-5 rounded-2xl glass-card border border-accent/60 shadow-2xl flex items-center gap-3 bg-panel/95">
            <ImageIcon size={32} className="text-accent animate-bounce" />
            <div>
              <p className="text-sm font-semibold text-fg">Rilascia l'immagine qui</p>
              <p className="text-xs text-fg-muted">Verrà allegata alla richiesta multimodale</p>
            </div>
          </div>
        </div>
      )}
      {/* Incognito Banner */}
      {isIncognito && (
        <div className="bg-purple-950/70 border-b border-purple-800/50 backdrop-blur-md px-3 sm:px-6 py-1.5 flex items-center justify-between text-[11px] text-purple-200 z-20 shrink-0">
          <div className="flex items-center gap-2 truncate">
            <EyeOff size={13} className="text-purple-400 shrink-0 animate-pulse" />
            <span className="truncate">
              <strong>Modalità Incognito attiva:</strong> memoria a lungo termine disabilitata. Nessun fatto verrà richiamato né salvato.
            </span>
          </div>
          <button
            type="button"
            onClick={() => setIsIncognito(false)}
            className="text-purple-300 hover:text-white underline text-[10px] ml-2 shrink-0 cursor-pointer"
          >
            Disattiva
          </button>
        </div>
      )}

      {/* Top Header */}
      <div className="h-14 border-b border-border glass-header px-3 sm:px-6 flex items-center justify-between z-10 shrink-0">
        <div className="flex items-center gap-2.5">
          {onOpenMobileSidebar && (
            <button
              onClick={onOpenMobileSidebar}
              className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition"
              title="Open threads sidebar"
            >
              <Menu size={20} />
            </button>
          )}

          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-accent to-accent-hover flex items-center justify-center text-white shadow-md shadow-accent/20 shrink-0">
            <Bot size={18} />
          </div>
          <div className="truncate max-w-[120px] sm:max-w-xs">
            <h2 className="text-xs sm:text-sm font-semibold text-fg truncate" title={currentThreadTitle || (currentThreadId ? `Thread: ${currentThreadId}` : 'New Session')}>
              {currentThreadTitle || (currentThreadId ? `Thread: ${currentThreadId}` : 'New Session')}
            </h2>
            <p className="text-[10px] sm:text-[11px] text-fg-muted truncate">Main Agent Engine</p>
          </div>
        </div>

        {/* Mode Selector & Controls */}
        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Desktop Mode Pills */}
          <div className="hidden sm:flex bg-panel/80 border border-border rounded-lg p-1 items-center gap-1 text-xs">
            <span className="text-fg-muted text-[11px] px-2 font-medium">Mode:</span>
            {(['auto', 'chat', 'ask', 'act', 'plan'] as const).map((modeOption) => (
              <button
                key={modeOption}
                onClick={() => setSelectedMode(modeOption)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium capitalize transition ${
                  selectedMode === modeOption
                    ? 'bg-accent text-white shadow-md shadow-accent/25'
                    : 'text-fg-muted hover:text-fg hover:bg-border/40'
                }`}
              >
                {modeOption}
              </button>
            ))}
          </div>

          {/* Mobile Mode Dropdown */}
          <div className="sm:hidden">
            <select
              value={selectedMode}
              onChange={(e) => setSelectedMode(e.target.value as any)}
              className="bg-panel border border-border rounded-lg px-2 py-1 text-xs text-fg focus:outline-none focus:border-accent capitalize"
            >
              <option value="auto">Auto Mode</option>
              <option value="chat">Chat</option>
              <option value="ask">Ask</option>
              <option value="act">Act</option>
              <option value="plan">Plan</option>
            </select>
          </div>

          <label className="flex items-center gap-1 text-xs text-fg-muted cursor-pointer bg-panel/80 border border-border px-2 sm:px-2.5 py-1.5 rounded-lg hover:border-accent/40 transition">
            <input
              type="checkbox"
              checked={execute}
              onChange={(e) => setExecute(e.target.checked)}
              className="rounded bg-input-bg border-border text-accent focus:ring-0"
            />
            <Play size={12} className={execute ? 'text-emerald-400' : 'text-fg-muted'} />
            <span className="text-[10px] sm:text-[11px] hidden xs:inline">Execute</span>
          </label>

          {/* Quick Theme Selector */}
          <ThemeQuickSelector />

          {/* Mobile Diagnostics Button */}
          {onOpenMobileToolLog && (
            <button
              onClick={onOpenMobileToolLog}
              className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition relative"
              title="Open Diagnostics"
            >
              <Activity size={18} className="text-accent" />
            </button>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-rose-950/80 border-b border-rose-800 px-4 sm:px-6 py-2.5 flex items-center justify-between text-xs text-rose-200 shrink-0">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-rose-400 shrink-0" />
            <span className="truncate">{error}</span>
          </div>
          <button
            onClick={onClearError}
            className="text-rose-400 hover:text-rose-200 font-bold px-2 py-0.5 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Messages Scroll Container */}
      <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-fg-muted space-y-4">
            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl glass-card border border-border flex items-center justify-center text-accent shadow-lg shadow-accent/10">
              <Sparkles size={24} />
            </div>
            <div className="max-w-md space-y-1">
              <h3 className="text-fg font-semibold text-sm">Main Agent Ready</h3>
              <p className="text-xs text-fg-muted leading-relaxed">
                Type a prompt to interact with the main agent API. Switch between <span className="text-accent font-mono">chat</span>, <span className="text-accent font-mono">ask</span>, <span className="text-accent font-mono">act</span>, or <span className="text-accent font-mono">plan</span> modes.
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isUser = msg.sender === 'user';
            const modeName = msg.mode?.toLowerCase();

            return (
              <div
                key={msg.id}
                className={`flex gap-2.5 sm:gap-3 max-w-3xl ${
                  isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
                }`}
              >
                {/* Avatar */}
                <div
                  className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center shrink-0 text-white shadow-sm mt-0.5 ${
                    isUser
                      ? 'bg-accent shadow-md shadow-accent/25'
                      : msg.isError
                      ? 'bg-rose-600'
                      : 'bg-panel border border-border text-accent'
                  }`}
                >
                  {isUser ? <User size={14} /> : <Bot size={14} />}
                </div>

                {/* Message Content Bubble */}
                <div className="flex flex-col space-y-1.5 max-w-[85vw] sm:max-w-xl">
                  <div
                    className={`px-3.5 py-2.5 sm:px-4 sm:py-3 rounded-2xl text-xs sm:text-sm leading-relaxed ${
                      isUser
                        ? 'glass-bubble-user text-userBubbleText rounded-tr-none shadow-md'
                        : msg.isError
                        ? 'bg-rose-950/70 border border-rose-800/80 text-rose-200 rounded-tl-none'
                        : 'glass-bubble-agent text-fg border border-border rounded-tl-none shadow-sm'
                    }`}
                  >
                    {isUser ? (
                      editingMsgId === msg.id ? (
                        <div className="flex flex-col gap-2 min-w-[260px] sm:min-w-[340px] text-fg">
                          <textarea
                            value={editPromptText}
                            onChange={(e) => setEditPromptText(e.target.value)}
                            className="w-full bg-input-bg/90 border border-border rounded-xl p-2.5 text-xs sm:text-sm text-fg focus:outline-none focus:border-accent resize-y min-h-[60px]"
                            placeholder="Modifica prompt..."
                            autoFocus
                          />
                          <div className="flex items-center justify-between gap-2 flex-wrap pt-1 border-t border-border/40 text-[11px]">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <select
                                value={editPromptMode}
                                onChange={(e) => setEditPromptMode(e.target.value as any)}
                                className="bg-panel border border-border rounded-md px-1.5 py-0.5 text-[10px] text-fg focus:outline-none focus:border-accent"
                              >
                                <option value="auto">Mode: Auto</option>
                                <option value="chat">Mode: Chat</option>
                                <option value="ask">Mode: Ask</option>
                                <option value="act">Mode: Act</option>
                                <option value="plan">Mode: Plan</option>
                              </select>
                              {availableModels.length > 0 && (
                                <select
                                  value={editPromptModel}
                                  onChange={(e) => setEditPromptModel(e.target.value)}
                                  className="bg-panel border border-border rounded-md px-1.5 py-0.5 text-[10px] text-fg focus:outline-none focus:border-accent max-w-[120px] truncate"
                                >
                                  <option value="default">Default Model</option>
                                  {availableModels.map((m) => (
                                    <option key={m} value={m}>{m}</option>
                                  ))}
                                </select>
                              )}
                            </div>
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={cancelEditing}
                                className="px-2 py-1 rounded-md text-[10px] text-fg-muted hover:text-fg hover:bg-border/40 transition cursor-pointer"
                              >
                                Annulla
                              </button>
                              <button
                                type="button"
                                onClick={() => submitEditing(msg.id)}
                                className="px-2.5 py-1 rounded-md text-[10px] font-medium bg-accent text-white hover:bg-accent-hover shadow-sm transition cursor-pointer flex items-center gap-1"
                              >
                                <Send size={10} />
                                <span>Invia</span>
                              </button>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="relative group/userbubble">
                          {/* Attached Images Thumbnail Grid */}
                          {msg.images && msg.images.length > 0 && (
                            <div className="flex flex-wrap gap-2 mb-2">
                              {msg.images.map((img, iIdx) => (
                                <div
                                  key={iIdx}
                                  onClick={() => setLightboxUrl(img)}
                                  className="relative group/thumb cursor-pointer rounded-xl overflow-hidden border border-white/20 shadow-md hover:scale-[1.02] transition-transform duration-150 bg-black/20"
                                  title="Clicca per ingrandire"
                                >
                                  <img
                                    src={img}
                                    alt={`allegato-${iIdx}`}
                                    className="max-h-48 max-w-[220px] sm:max-w-[280px] object-cover rounded-xl"
                                  />
                                  <div className="absolute inset-0 bg-black/30 opacity-0 group-hover/thumb:opacity-100 transition-opacity flex items-center justify-center text-white">
                                    <Maximize2 size={16} className="drop-shadow" />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                          <div className="whitespace-pre-wrap font-sans break-words pr-12">{msg.content}</div>
                          {/* Hover action buttons on User prompt */}
                          <div className="absolute top-0 right-0 flex items-center gap-0.5 opacity-0 group-hover/userbubble:opacity-100 transition-opacity">
                            <button
                              type="button"
                              onClick={() => handleCopy(msg.content, msg.id)}
                              className="p-1 rounded text-userBubbleText/70 hover:text-userBubbleText hover:bg-white/10 transition cursor-pointer"
                              title="Copia prompt"
                            >
                              {copiedId === msg.id ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                            </button>
                            {!isLoading && onEditPrompt && (
                              <button
                                type="button"
                                onClick={() => startEditing(msg)}
                                className="p-1 rounded text-userBubbleText/70 hover:text-userBubbleText hover:bg-white/10 transition cursor-pointer"
                                title="Modifica prompt"
                              >
                                <Pencil size={12} />
                              </button>
                            )}
                          </div>
                        </div>
                      )
                    ) : (
                      <>
                        {!msg.content && !msg.reasoning_content && isLoading && index === messages.length - 1 ? (
                          <div className="flex items-center gap-2 text-fg-muted py-0.5">
                            <div className="flex space-x-1">
                              <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                              <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                              <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                            </div>
                            <span className="ml-1 text-[11px] sm:text-xs font-sans">Thinking & executing...</span>
                          </div>
                        ) : (
                          <>
                            {msg.reasoning_content && (
                              <ReasoningBlock
                                content={msg.reasoning_content}
                                isStreaming={isLoading && index === messages.length - 1 && (!msg.content || msg.content.length === 0)}
                              />
                            )}
                            {msg.content && <MarkdownRenderer content={msg.content} />}
                          </>
                        )}
                      </>
                    )}

                    {/* Mode Specific Inline Views (Act / Plan / Trace) */}
                    {!isUser && (
                      <>
                        {/* Plan View for Plan Mode */}
                        {(modeName === 'plan' || (msg.plan_steps && msg.plan_steps.length > 0)) && (
                          <PlanViewer
                            planSteps={msg.plan_steps}
                            planStructure={msg.plan_structure}
                            onExecutePlan={(summary) => onSendMessage(summary, 'act', true)}
                            isLoading={isLoading}
                          />
                        )}

                        {/* Inline Reasoning & Execution Trace */}
                        {(msg.reasoning || (msg.execution_trace && msg.execution_trace.length > 0) || (msg.rollback_trace && msg.rollback_trace.length > 0)) && (
                          <ExecutionTraceViewer
                            reasoning={msg.reasoning}
                            trace={msg.execution_trace}
                            rollbackTrace={msg.rollback_trace}
                            initialCollapsed={true}
                          />
                        )}

                        {/* Web Sources Citations */}
                        {msg.web_prefetch && msg.web_prefetch.sources && msg.web_prefetch.sources.length > 0 && (
                          <div className="mt-3 pt-2.5 border-t border-border/60">
                            <div className="flex items-center gap-1.5 text-[11px] font-medium text-accent mb-1.5">
                              <Globe size={12} className="text-accent" />
                              <span>Fonti web consultate:</span>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {msg.web_prefetch.sources.slice(0, 5).map((src, sIdx) => {
                                let domain = '';
                                try {
                                  domain = new URL(src.url).hostname.replace(/^www\./, '');
                                } catch {
                                  domain = src.url;
                                }
                                return (
                                  <a
                                    key={sIdx}
                                    href={src.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-panel/80 hover:bg-panel border border-border/80 hover:border-accent text-fg-muted hover:text-fg text-[10px] transition group"
                                    title={`${src.title}\n${src.url}`}
                                  >
                                    <span className="truncate max-w-[140px]">{domain}</span>
                                  </a>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>

                  {/* Metadata Indicators under Bubble */}
                  {(!isLoading || msg.content || msg.reasoning_content || index !== messages.length - 1) && (
                    <div className={`flex items-center gap-1.5 text-[10px] text-fg-muted px-1 flex-wrap ${isUser ? 'justify-end' : 'justify-start'}`}>
                      {/* Version Carousel < 1/N > (hidden if only 1 version) */}
                      {msg.versions && msg.versions.length > 1 && (
                        <div className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded-md bg-panel border border-border text-[9px] font-mono text-fg-muted shadow-sm select-none">
                          <button
                            type="button"
                            onClick={() => onSwitchVersion?.(msg.id, (msg.versionIndex ?? 0) - 1)}
                            disabled={(msg.versionIndex ?? 0) <= 0}
                            className="p-0.5 hover:text-fg disabled:opacity-25 disabled:hover:text-fg-muted transition cursor-pointer"
                            title="Versione precedente"
                          >
                            <ChevronLeft size={11} />
                          </button>
                          <span className="px-1 text-[9px] font-semibold text-fg">
                            {(msg.versionIndex ?? 0) + 1} / {msg.versions.length}
                          </span>
                          <button
                            type="button"
                            onClick={() => onSwitchVersion?.(msg.id, (msg.versionIndex ?? 0) + 1)}
                            disabled={(msg.versionIndex ?? 0) >= msg.versions.length - 1}
                            className="p-0.5 hover:text-fg disabled:opacity-25 disabled:hover:text-fg-muted transition cursor-pointer"
                            title="Versione successiva"
                          >
                            <ChevronRight size={11} />
                          </button>
                        </div>
                      )}

                      <span>{msg.timestamp}</span>

                      {/* Assistant Actions: Copy response & Regenerate */}
                      {!isUser && msg.content && (
                        <button
                          type="button"
                          onClick={() => handleCopy(msg.content, msg.id)}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-panel hover:bg-panel-header border border-border text-[9px] text-fg-muted hover:text-fg font-mono transition cursor-pointer"
                          title="Copia risposta"
                        >
                          {copiedId === msg.id ? (
                            <>
                              <Check size={10} className="text-emerald-400" />
                              <span className="text-emerald-400">Copiato</span>
                            </>
                          ) : (
                            <>
                              <Copy size={10} />
                              <span>Copia</span>
                            </>
                          )}
                        </button>
                      )}

                      {!isUser && onRegenerate && !isLoading && (
                        <button
                          type="button"
                          onClick={() => onRegenerate(msg.id)}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-panel hover:bg-panel-header border border-border hover:border-accent text-[9px] text-fg-muted hover:text-fg font-mono transition cursor-pointer shadow-sm"
                          title="Rigenera risposta dal prompt precedente"
                        >
                          <RefreshCw size={9} />
                          <span>Rigenera</span>
                        </button>
                      )}

                      {modeName && (
                        <span className="px-1.5 py-0.5 rounded bg-panel border border-border text-[9px] uppercase font-mono tracking-wider">
                          {modeName}
                        </span>
                      )}
                      {msg.tool_used && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-[9px] sm:text-[10px]">
                          <Wrench size={10} />
                          {msg.tool_used}
                        </span>
                      )}
                      {msg.web_prefetch && msg.web_prefetch.sources && msg.web_prefetch.sources.length > 0 && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 font-mono text-[9px] sm:text-[10px]">
                          <Globe size={10} />
                          {msg.web_prefetch.sources.length} fonti web
                        </span>
                      )}
                      {/* Performance & Token Metrics */}
                      {msg.metrics && (
                        <span
                          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-panel border border-border text-fg-muted font-mono text-[9px] sm:text-[10px]"
                          title={`Prompt: ${msg.metrics.prompt_tokens ?? 0} tok • Generati: ${msg.metrics.completion_tokens ?? 0} tok • Durata: ${msg.metrics.duration_s ?? 0}s`}
                        >
                          <Zap size={10} className="text-amber-400" />
                          <span>{msg.metrics.tok_per_s ?? 0} tok/s</span>
                          <span className="text-border">•</span>
                          <span>{msg.metrics.total_tokens ?? 0} tok</span>
                          {msg.metrics.duration_s !== undefined && (
                            <>
                              <span className="text-border">•</span>
                              <span>{msg.metrics.duration_s}s</span>
                            </>
                          )}
                        </span>
                      )}
                      {/* Paused Indicator during live generation */}
                      {isLoading && isPaused && index === messages.length - 1 && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 font-mono text-[9px] sm:text-[10px] animate-pulse">
                          <Pause size={10} />
                          In pausa...
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* Loading Indicator when messages are empty (e.g. initial load) */}
        {isLoading && messages.length === 0 && (
          <div className="flex gap-2.5 sm:gap-3 max-w-3xl mr-auto items-center">
            <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-panel border border-border flex items-center justify-center text-accent animate-pulse">
              <Bot size={14} />
            </div>
            <div className="glass-card border border-border rounded-2xl rounded-tl-none px-3.5 py-2.5 sm:px-4 sm:py-3 text-fg-muted text-xs flex items-center gap-2">
              <div className="flex space-x-1">
                <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
              <span className="ml-1 text-[11px] sm:text-xs">Thinking & executing...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="p-3 sm:p-4 border-t border-border glass-input-bar shrink-0 flex flex-col gap-2">
        <div className="max-w-4xl mx-auto w-full flex justify-end gap-2 items-center flex-wrap">
          {/* Incognito Mode Toggle */}
          <button
            type="button"
            onClick={() => setIsIncognito(!isIncognito)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition cursor-pointer shadow-sm ${
              isIncognito
                ? 'bg-purple-950/70 border-purple-500 text-purple-200 shadow-purple-950/50 ring-1 ring-purple-500/50'
                : 'glass-card border-border text-fg-muted hover:text-fg hover:border-accent/40'
            }`}
            title={isIncognito ? 'Modalità Incognito attiva (nessun fatto salvato)' : 'Attiva Modalità Incognito (disabilita estrazione e memoria)'}
          >
            <EyeOff size={12} className={isIncognito ? 'text-purple-400' : 'text-fg-muted shrink-0'} />
            <span className="text-[11px] font-sans">{isIncognito ? 'Incognito ON' : 'Incognito'}</span>
          </button>

          {/* Web Search Toggle */}
          <button
            type="button"
            onClick={() => setWebSearchEnabled(!webSearchEnabled)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition cursor-pointer shadow-sm ${
              webSearchEnabled
                ? 'bg-accent/20 border-accent text-accent shadow-accent/20 ring-1 ring-accent/50'
                : 'glass-card border-border text-fg-muted hover:text-fg hover:border-accent/40'
            }`}
            title={webSearchEnabled ? 'Ricerca Web attiva (prefetch pre-turn abilitato)' : 'Attiva Ricerca Web (effettua retrieval da web prima di rispondere)'}
          >
            <Globe size={12} className={webSearchEnabled ? 'text-accent' : 'text-fg-muted shrink-0'} />
            <span className="text-[11px] font-sans">{webSearchEnabled ? 'Web ON' : 'Web'}</span>
          </button>

          {/* Model Selector Dropdown */}
          <div className="flex items-center glass-card border border-border rounded-lg px-2 py-1 text-[11px] gap-1.5 text-fg-muted hover:border-accent/40 w-max shadow-sm">
            <Box size={12} className="text-emerald-400 shrink-0" />
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="bg-transparent text-[11px] text-fg focus:outline-none cursor-pointer max-w-[140px] sm:max-w-[200px] truncate font-mono"
              title="Modello LLM Override"
            >
              <option value="default" className="bg-panel text-fg font-sans">Modello: Default</option>
              {availableModels.map((m) => {
                const isVision = isModelVision(m);
                return (
                  <option key={m} value={m} className="bg-panel text-fg font-mono">
                    {m} {isVision ? '👁️ [Vision]' : ''}
                  </option>
                );
              })}
            </select>
          </div>

          {/* Reasoning Budget Dropdown */}
          <div className="flex items-center glass-card border border-border rounded-lg px-2 py-1 text-[11px] gap-1.5 text-fg-muted hover:border-accent/40 w-max shadow-sm">
            <Brain size={12} className="text-purple-400 shrink-0" />
            <select
              value={reasoningBudget === undefined ? 'default' : reasoningBudget}
              onChange={(e) => {
                const val = e.target.value;
                setReasoningBudget(val === 'default' ? undefined : Number(val));
              }}
              className="bg-transparent text-[11px] text-fg focus:outline-none cursor-pointer"
              title="Reasoning Token Budget"
            >
              <option value="default" className="bg-panel text-fg">Budget: Default</option>
              <option value="0" className="bg-panel text-fg">Disable (0t)</option>
              <option value="2048" className="bg-panel text-fg">Balanced (2048t)</option>
              <option value="8192" className="bg-panel text-fg">Deep Think (8192t)</option>
              <option value="-1" className="bg-panel text-fg">Unlimited (-1)</option>
            </select>
          </div>
        </div>

        {/* Helpful hint if image attached and selected model is text-only */}
        {pendingImages.length > 0 && selectedModel !== 'default' && !isModelVision(selectedModel) && (
          <div className="max-w-4xl mx-auto w-full px-1 text-[11px] text-amber-400/90 flex items-center gap-1.5">
            <AlertTriangle size={12} className="shrink-0" />
            <span>
              Il modello selezionato (<strong>{selectedModel}</strong>) potrebbe non supportare la visione. Ti consigliamo <strong>Qwen3.6-35B</strong>.
            </span>
          </div>
        )}

        {/* Pending Images Thumbnail Preview Strip */}
        {pendingImages.length > 0 && (
          <div className="max-w-4xl mx-auto w-full flex items-center gap-2 overflow-x-auto py-1 px-1">
            {pendingImages.map((img) => (
              <div
                key={img.id}
                className="relative group shrink-0 rounded-xl overflow-hidden border border-border bg-panel shadow-md flex items-center"
              >
                <img
                  src={img.dataUrl}
                  alt={img.name}
                  className="h-14 w-14 sm:h-16 sm:w-16 object-cover cursor-pointer hover:opacity-90 transition"
                  onClick={() => setLightboxUrl(img.dataUrl)}
                  title="Clicca per ingrandire"
                />
                <button
                  type="button"
                  onClick={() => removePendingImage(img.id)}
                  className="absolute top-1 right-1 p-0.5 rounded-full bg-black/70 text-white/90 hover:text-white hover:bg-rose-600 transition shadow cursor-pointer"
                  title="Rimuovi immagine"
                >
                  <X size={12} />
                </button>
                <div className="absolute bottom-0 inset-x-0 bg-black/60 px-1 py-0.5 text-[9px] text-white truncate max-w-[56px] sm:max-w-[64px]">
                  {img.name}
                </div>
              </div>
            ))}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="h-14 w-14 sm:h-16 sm:w-16 rounded-xl border border-dashed border-border hover:border-accent flex flex-col items-center justify-center text-fg-muted hover:text-accent transition shrink-0 bg-panel/40 cursor-pointer"
              title="Aggiungi altra immagine"
            >
              <Paperclip size={16} />
              <span className="text-[9px] mt-1">+ Altro</span>
            </button>
          </div>
        )}

        {/* Hidden File Input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          onChange={(e) => {
            if (e.target.files) processImageFiles(e.target.files);
            e.target.value = '';
          }}
          className="hidden"
        />

        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto w-full relative flex items-center">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            className="absolute left-2 sm:left-2.5 p-1.5 text-fg-muted hover:text-accent hover:bg-panel rounded-lg transition cursor-pointer z-10 disabled:opacity-40"
            title="Allega immagine (o trascina/incolla con Ctrl+V)"
          >
            <ImageIcon size={17} />
          </button>
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isLoading
                ? isPaused
                  ? 'Esecuzione in pausa...'
                  : 'Generazione in corso...'
                : pendingImages.length > 0
                ? "Aggiungi istruzioni per l'immagine o premi Invia per descriverla..."
                : 'Send message (incolla immagini con Ctrl+V)...'
            }
            disabled={isLoading}
            className="w-full bg-input-bg border border-input-border rounded-xl pl-9 sm:pl-10 pr-20 py-2.5 sm:py-3 text-xs sm:text-sm text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40 resize-none transition"
          />
          {isLoading ? (
            <div className="absolute right-1.5 sm:right-2 flex items-center gap-1">
              <button
                type="button"
                onClick={isPaused ? onResume : onPause}
                className={`p-1.5 sm:p-2 rounded-lg transition active:scale-95 shadow-md cursor-pointer ${
                  isPaused
                    ? 'bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 border border-amber-500/40 shadow-amber-500/20'
                    : 'glass-card border border-border text-fg-muted hover:text-fg hover:border-accent/40'
                }`}
                title={isPaused ? 'Riprendi esecuzione' : 'Metti in pausa'}
              >
                {isPaused ? <Play size={14} className="fill-current text-amber-400" /> : <Pause size={14} />}
              </button>
              <button
                type="button"
                onClick={onStop}
                className="p-1.5 sm:p-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg transition active:scale-95 shadow-md shadow-rose-600/30 cursor-pointer"
                title="Interrompi esecuzione"
              >
                <Square size={14} className="fill-current" />
              </button>
            </div>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() && pendingImages.length === 0}
              className="absolute right-1.5 sm:right-2 p-1.5 sm:p-2 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:hover:bg-accent text-white rounded-lg transition active:scale-95 shadow-md shadow-accent/25 cursor-pointer"
              title={pendingImages.length > 0 && !input.trim() ? "Invia immagine per l'analisi automatica" : "Send Message"}
            >
              <Send size={15} />
            </button>
          )}
        </form>
      </div>

      {/* Fullscreen Lightbox Modal */}
      {lightboxUrl && (
        <div
          className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200"
          onClick={() => setLightboxUrl(null)}
        >
          <div className="relative max-w-5xl max-h-[90vh] flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={() => setLightboxUrl(null)}
              className="absolute -top-10 right-0 p-1.5 rounded-full bg-panel text-fg hover:text-rose-400 hover:bg-panel-border transition cursor-pointer shadow-lg"
              title="Chiudi"
            >
              <X size={20} />
            </button>
            <img
              src={lightboxUrl}
              alt="Ingrandimento immagine"
              className="max-h-[85vh] max-w-full object-contain rounded-xl shadow-2xl border border-border"
            />
          </div>
        </div>
      )}
    </div>
  );
};
