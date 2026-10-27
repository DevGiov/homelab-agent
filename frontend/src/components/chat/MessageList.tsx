import React, { useEffect, useRef } from 'react';
import { Bot, Sparkles } from 'lucide-react';
import type { AgentMode, FormattedMessage } from '../../api/chat';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { ChatMessage, type MessageActions } from './ChatMessage';
import { ThinkingIndicator } from './ThinkingIndicator';

interface MessageListProps {
  messages: FormattedMessage[];
  threadId: string | null;
  isLoading: boolean;
  isPaused: boolean;
  actions: MessageActions;
  models: ModelCatalog;
  editDefaults: { mode: AgentMode | 'auto'; model: string };
  /** Cambia quando la vista va riportata in fondo oltre ai nuovi messaggi (es. immagini allegate). */
  scrollKey?: unknown;
}

const EmptyState = () => (
  <div className="h-full flex flex-col items-center justify-center text-center p-6 text-fg-muted space-y-4">
    <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl glass-card border border-border flex items-center justify-center text-accent shadow-lg shadow-accent/10">
      <Sparkles size={24} />
    </div>
    <div className="max-w-md space-y-1">
      <h3 className="text-fg font-semibold text-sm">Main Agent Ready</h3>
      <p className="text-xs text-fg-muted leading-relaxed">
        Type a prompt to interact with the main agent API. Switch between <span className="text-accent font-mono">chat</span>,{' '}
        <span className="text-accent font-mono">ask</span>, <span className="text-accent font-mono">act</span>, or{' '}
        <span className="text-accent font-mono">plan</span> modes.
      </p>
    </div>
  </div>
);

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  threadId,
  isLoading,
  isPaused,
  actions,
  models,
  editDefaults,
  scrollKey,
}) => {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, scrollKey]);

  return (
    <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6">
      {messages.length === 0 && !isLoading && <EmptyState />}

      {messages.map((msg, index) => (
        <ChatMessage
          key={msg.id}
          message={msg}
          threadId={threadId}
          isLast={index === messages.length - 1}
          isLoading={isLoading}
          isPaused={isPaused}
          actions={actions}
          models={models}
          editDefaults={editDefaults}
        />
      ))}

      {/* Caricamento iniziale del thread, prima che arrivi qualsiasi messaggio */}
      {isLoading && messages.length === 0 && (
        <div className="flex gap-2.5 sm:gap-3 max-w-3xl mr-auto items-center">
          <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-panel border border-border flex items-center justify-center text-accent animate-pulse">
            <Bot size={14} />
          </div>
          <div className="glass-card border border-border rounded-2xl rounded-tl-none px-3.5 py-2.5 sm:px-4 sm:py-3 text-xs">
            <ThinkingIndicator />
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
};
