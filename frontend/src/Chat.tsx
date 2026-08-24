import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Wrench, Sparkles, AlertTriangle, Play, Menu, Activity, Brain, Box, EyeOff } from 'lucide-react';
import { type FormattedMessage, type AgentMode, getProviders, getProviderModels } from './api';
import { PlanViewer } from './components/PlanViewer';
import { ExecutionTraceViewer } from './components/ExecutionTraceViewer';
import { MarkdownRenderer } from './components/MarkdownRenderer';
import ReasoningBlock from './components/ReasoningBlock';

interface ChatProps {
  currentThreadId: string | null;
  messages: FormattedMessage[];
  onSendMessage: (
    input: string,
    mode: AgentMode | undefined,
    execute: boolean,
    reasoningBudget?: number,
    model?: string,
    incognito?: boolean
  ) => Promise<void>;
  isLoading: boolean;
  error: string | null;
  onClearError: () => void;
  onOpenMobileSidebar?: () => void;
  onOpenMobileToolLog?: () => void;
}

export const Chat: React.FC<ChatProps> = ({
  currentThreadId,
  messages,
  onSendMessage,
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

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getProviders()
      .then((data) => {
        const activeProv = data.active_provider;
        if (activeProv) {
          getProviderModels(activeProv)
            .then((mList) => {
              setAvailableModels(mList);
            })
            .catch((err) => console.warn('Errore caricamento modelli chat:', err));
        }
      })
      .catch((err) => console.warn('Errore caricamento provider chat:', err));
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || isLoading) return;

    const modeToPass = selectedMode === 'auto' ? undefined : selectedMode;
    const modelToPass = selectedModel === 'default' ? undefined : selectedModel;
    onSendMessage(input.trim(), modeToPass, execute, reasoningBudget, modelToPass, isIncognito);
    setInput('');
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

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950 text-slate-100 overflow-hidden relative">
      {/* Incognito Banner */}
      {isIncognito && (
        <div className="bg-purple-950/80 border-b border-purple-800/50 px-3 sm:px-6 py-1.5 flex items-center justify-between text-[11px] text-purple-200 z-20 shrink-0">
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
      <div className="h-14 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-3 sm:px-6 flex items-center justify-between z-10 shrink-0">
        <div className="flex items-center gap-2.5">
          {onOpenMobileSidebar && (
            <button
              onClick={onOpenMobileSidebar}
              className="md:hidden p-1.5 text-slate-300 hover:text-white hover:bg-slate-800 rounded-lg transition"
              title="Open threads sidebar"
            >
              <Menu size={20} />
            </button>
          )}

          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white shadow-md shadow-blue-500/20 shrink-0">
            <Bot size={18} />
          </div>
          <div className="truncate max-w-[120px] sm:max-w-xs">
            <h2 className="text-xs sm:text-sm font-semibold text-slate-200 truncate">
              {currentThreadId ? `Thread: ${currentThreadId}` : 'New Session'}
            </h2>
            <p className="text-[10px] sm:text-[11px] text-slate-400 truncate">Main Agent Engine</p>
          </div>
        </div>

        {/* Mode Selector Controls */}
        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Desktop Mode Pills */}
          <div className="hidden sm:flex bg-slate-900 border border-slate-800 rounded-lg p-1 items-center gap-1 text-xs">
            <span className="text-slate-400 text-[11px] px-2 font-medium">Mode:</span>
            {(['auto', 'chat', 'ask', 'act', 'plan'] as const).map((modeOption) => (
              <button
                key={modeOption}
                onClick={() => setSelectedMode(modeOption)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium capitalize transition ${
                  selectedMode === modeOption
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
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
              className="bg-slate-900 border border-slate-800 rounded-lg px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-blue-500 capitalize"
            >
              <option value="auto">Auto Mode</option>
              <option value="chat">Chat</option>
              <option value="ask">Ask</option>
              <option value="act">Act</option>
              <option value="plan">Plan</option>
            </select>
          </div>

          <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer bg-slate-900 border border-slate-800 px-2 sm:px-2.5 py-1.5 rounded-lg hover:border-slate-700">
            <input
              type="checkbox"
              checked={execute}
              onChange={(e) => setExecute(e.target.checked)}
              className="rounded bg-slate-950 border-slate-700 text-blue-600 focus:ring-0"
            />
            <Play size={12} className={execute ? 'text-emerald-400' : 'text-slate-500'} />
            <span className="text-[10px] sm:text-[11px] hidden xs:inline">Execute</span>
          </label>



          {/* Mobile Diagnostics Button */}
          {onOpenMobileToolLog && (
            <button
              onClick={onOpenMobileToolLog}
              className="md:hidden p-1.5 text-slate-300 hover:text-white hover:bg-slate-800 rounded-lg transition relative"
              title="Open Diagnostics"
            >
              <Activity size={18} className="text-blue-400" />
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
            className="text-rose-400 hover:text-rose-200 font-bold px-2 py-0.5"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Messages Scroll Container */}
      <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500 space-y-4">
            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center text-blue-400">
              <Sparkles size={24} />
            </div>
            <div className="max-w-md space-y-1">
              <h3 className="text-slate-300 font-semibold text-sm">Main Agent Ready</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Type a prompt to interact with the main agent API. Switch between <span className="text-blue-400 font-mono">chat</span>, <span className="text-blue-400 font-mono">ask</span>, <span className="text-blue-400 font-mono">act</span>, or <span className="text-blue-400 font-mono">plan</span> modes.
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
                      ? 'bg-blue-600'
                      : msg.isError
                      ? 'bg-rose-600'
                      : 'bg-slate-800 border border-slate-700'
                  }`}
                >
                  {isUser ? <User size={14} /> : <Bot size={14} />}
                </div>

                {/* Message Content Bubble */}
                <div className="flex flex-col space-y-1.5 max-w-[85vw] sm:max-w-xl">
                  <div
                    className={`px-3.5 py-2.5 sm:px-4 sm:py-3 rounded-2xl text-xs sm:text-sm leading-relaxed ${
                      isUser
                        ? 'bg-blue-600 text-white rounded-tr-none shadow-md shadow-blue-600/10'
                        : msg.isError
                        ? 'bg-rose-950/60 border border-rose-800/80 text-rose-200 rounded-tl-none'
                        : 'bg-slate-900 border border-slate-800 text-slate-100 rounded-tl-none shadow-sm'
                    }`}
                  >
                    {isUser ? (
                      <div className="whitespace-pre-wrap font-sans break-words">{msg.content}</div>
                    ) : (
                      <>
                        {msg.reasoning_content && (
                          <ReasoningBlock content={msg.reasoning_content} isStreaming={isLoading && index === messages.length - 1} />
                        )}
                        <MarkdownRenderer content={msg.content} />
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
                      </>
                    )}
                  </div>

                  {/* Sub-bubble Metadata Badges */}
                  <div
                    className={`flex items-center gap-1.5 sm:gap-2 px-1 text-[10px] sm:text-[11px] text-slate-500 ${
                      isUser ? 'justify-end' : 'justify-start'
                    }`}
                  >
                    <span>{msg.timestamp}</span>
                    {msg.mode && (
                      <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 font-mono text-[9px] sm:text-[10px] text-slate-400 uppercase">
                        {msg.mode}
                      </span>
                    )}
                    {msg.tool_used && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-[9px] sm:text-[10px]">
                        <Wrench size={10} />
                        {msg.tool_used}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}

        {/* Loading Indicator */}
        {isLoading && (
          <div className="flex gap-2.5 sm:gap-3 max-w-3xl mr-auto items-center">
            <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-blue-400 animate-pulse">
              <Bot size={14} />
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-none px-3.5 py-2.5 sm:px-4 sm:py-3 text-slate-400 text-xs flex items-center gap-2">
              <div className="flex space-x-1">
                <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
              <span className="ml-1 text-[11px] sm:text-xs">Thinking & executing...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="p-3 sm:p-4 border-t border-slate-800 bg-slate-900/80 backdrop-blur-md shrink-0 flex flex-col gap-2">
        <div className="max-w-4xl mx-auto w-full flex justify-end gap-2 items-center flex-wrap">
          {/* Incognito Mode Toggle */}
          <button
            type="button"
            onClick={() => setIsIncognito(!isIncognito)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition cursor-pointer shadow-sm ${
              isIncognito
                ? 'bg-purple-950 border-purple-500 text-purple-200 shadow-purple-950/50 ring-1 ring-purple-500/50'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
            }`}
            title={isIncognito ? 'Modalità Incognito attiva (nessun fatto salvato)' : 'Attiva Modalità Incognito (disabilita estrazione e memoria)'}
          >
            <EyeOff size={12} className={isIncognito ? 'text-purple-400' : 'text-slate-400 shrink-0'} />
            <span className="text-[11px] font-sans">{isIncognito ? 'Incognito ON' : 'Incognito'}</span>
          </button>

          {/* Model Selector Dropdown */}
          <div className="flex items-center bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-[11px] gap-1.5 text-slate-400 hover:border-slate-700 w-max shadow-sm">
            <Box size={12} className="text-emerald-400 shrink-0" />
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="bg-transparent text-[11px] text-slate-300 focus:outline-none cursor-pointer max-w-[140px] sm:max-w-[200px] truncate font-mono"
              title="Modello LLM Override"
            >
              <option value="default" className="bg-slate-900 text-slate-200 font-sans">Modello: Default</option>
              {availableModels.map((m) => (
                <option key={m} value={m} className="bg-slate-900 text-slate-200 font-mono">
                  {m}
                </option>
              ))}
            </select>
          </div>

          {/* Reasoning Budget Dropdown */}
          <div className="flex items-center bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-[11px] gap-1.5 text-slate-400 hover:border-slate-700 w-max shadow-sm">
            <Brain size={12} className="text-purple-400 shrink-0" />
            <select
              value={reasoningBudget === undefined ? 'default' : reasoningBudget}
              onChange={(e) => {
                const val = e.target.value;
                setReasoningBudget(val === 'default' ? undefined : Number(val));
              }}
              className="bg-transparent text-[11px] text-slate-300 focus:outline-none cursor-pointer"
              title="Reasoning Token Budget"
            >
              <option value="default" className="bg-slate-900 text-slate-200">Budget: Default</option>
              <option value="0" className="bg-slate-900 text-slate-200">Disable (0t)</option>
              <option value="2048" className="bg-slate-900 text-slate-200">Balanced (2048t)</option>
              <option value="8192" className="bg-slate-900 text-slate-200">Deep Think (8192t)</option>
              <option value="-1" className="bg-slate-900 text-slate-200">Unlimited (-1)</option>
            </select>
          </div>
        </div>
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto w-full relative flex items-center">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send message..."
            className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-3.5 pr-11 py-2.5 sm:py-3 text-xs sm:text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none transition"
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="absolute right-1.5 sm:right-2 p-1.5 sm:p-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 text-white rounded-lg transition active:scale-95 shadow-md shadow-blue-600/20"
            title="Send Message"
          >
            <Send size={15} />
          </button>
        </form>
      </div>
    </div>
  );
};
