import React, { useState } from 'react';
import { Bot, Check, Copy, Maximize2, Pencil, User } from 'lucide-react';
import type { AgentMode, FormattedMessage } from '../../api/chat';
import type { PromptEdit } from '../../hooks/useChat';
import { useCopyFeedback } from '../../hooks/useCopyFeedback';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { MarkdownRenderer } from '../MarkdownRenderer';
import ReasoningBlock from '../ReasoningBlock';
import { AssistantDetails } from './AssistantDetails';
import { MessageMeta } from './MessageMeta';
import { PromptEditor } from './PromptEditor';
import { ThinkingIndicator } from './ThinkingIndicator';

export interface MessageActions {
  onExecutePlan: (summary: string) => void;
  onOpenImage: (url: string) => void;
  onRegenerate?: (messageId: string) => void;
  onEditPrompt?: (messageId: string, edit: PromptEdit) => void;
  onSwitchVersion?: (messageId: string, index: number) => void;
  onApprovalResolved?: (action: string, res?: any) => void;
  onInspect?: (messageId: string) => void;
}

interface ChatMessageProps {
  message: FormattedMessage;
  threadId: string | null;
  /** Ultimo messaggio della conversazione, quello eventualmente in generazione. */
  isLast: boolean;
  isLoading: boolean;
  isPaused: boolean;
  actions: MessageActions;
  models: ModelCatalog;
  editDefaults: { mode: AgentMode | 'auto'; model: string };
}

const bubbleClass = (msg: FormattedMessage) =>
  msg.sender === 'user'
    ? 'glass-bubble-user text-userBubbleText rounded-tr-none shadow-md'
    : msg.isError
    ? 'bg-rose-950/70 border border-rose-800/80 text-rose-200 rounded-tl-none'
    : 'glass-bubble-agent text-fg border border-border rounded-tl-none shadow-sm';

const avatarClass = (msg: FormattedMessage) =>
  msg.sender === 'user'
    ? 'bg-accent shadow-md shadow-accent/25'
    : msg.isError
    ? 'bg-rose-600'
    : 'bg-panel border border-border text-accent';

export const ChatMessage: React.FC<ChatMessageProps> = ({
  message: msg,
  threadId,
  isLast,
  isLoading,
  isPaused,
  actions,
  models,
  editDefaults,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const { copied, copy } = useCopyFeedback();
  const isUser = msg.sender === 'user';
  const isGenerating = isLoading && isLast;
  const isWaiting = isGenerating && !msg.content && !msg.reasoning_content;

  const userContent = isEditing ? (
    <PromptEditor
      message={msg}
      defaults={editDefaults}
      models={models}
      onCancel={() => setIsEditing(false)}
      onSubmit={(edit) => {
        actions.onEditPrompt?.(msg.id, edit);
        setIsEditing(false);
      }}
    />
  ) : (
    <div className="relative group/userbubble">
      {msg.images && msg.images.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {msg.images.map((img, idx) => (
            <div
              key={idx}
              onClick={() => actions.onOpenImage(img)}
              className="relative group/thumb cursor-pointer rounded-xl overflow-hidden border border-white/20 shadow-md hover:scale-[1.02] transition-transform duration-150 bg-black/20"
              title="Clicca per ingrandire"
            >
              <img src={img} alt={`allegato-${idx}`} className="max-h-48 max-w-[220px] sm:max-w-[280px] object-cover rounded-xl" />
              <div className="absolute inset-0 bg-black/30 opacity-0 group-hover/thumb:opacity-100 transition-opacity flex items-center justify-center text-white">
                <Maximize2 size={16} className="drop-shadow" />
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="whitespace-pre-wrap font-sans break-words pr-12">{msg.content}</div>
      <div className="absolute top-0 right-0 flex items-center gap-0.5 opacity-0 group-hover/userbubble:opacity-100 transition-opacity">
        <button
          type="button"
          onClick={() => copy(msg.content)}
          className="p-1 rounded text-userBubbleText/70 hover:text-userBubbleText hover:bg-white/10 transition cursor-pointer"
          title="Copia prompt"
        >
          {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
        </button>
        {!isLoading && actions.onEditPrompt && (
          <button
            type="button"
            onClick={() => setIsEditing(true)}
            className="p-1 rounded text-userBubbleText/70 hover:text-userBubbleText hover:bg-white/10 transition cursor-pointer"
            title="Modifica prompt"
          >
            <Pencil size={12} />
          </button>
        )}
      </div>
    </div>
  );

  const assistantContent = isWaiting ? (
    <ThinkingIndicator />
  ) : (
    <>
      {msg.reasoning_content && (
        <ReasoningBlock content={msg.reasoning_content} isStreaming={isGenerating && !msg.content} />
      )}
      {msg.content && <MarkdownRenderer content={msg.content} />}
    </>
  );

  return (
    <div className={`flex gap-2.5 sm:gap-3 max-w-3xl ${isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'}`}>
      <div
        className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center shrink-0 text-white shadow-sm mt-0.5 ${avatarClass(msg)}`}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      <div className="flex flex-col space-y-1.5 max-w-[85vw] sm:max-w-xl">
        <div className={`px-3.5 py-2.5 sm:px-4 sm:py-3 rounded-2xl text-xs sm:text-sm leading-relaxed ${bubbleClass(msg)}`}>
          {isUser ? (
            userContent
          ) : (
            <>
              {assistantContent}
              <AssistantDetails
                message={msg}
                threadId={threadId}
                isLoading={isLoading}
                onExecutePlan={actions.onExecutePlan}
                onApprovalResolved={actions.onApprovalResolved}
              />
            </>
          )}
        </div>

        {!isWaiting && (
          <MessageMeta
            message={msg}
            showPaused={isGenerating && isPaused}
            isLoading={isLoading}
            copied={copied}
            onCopy={() => copy(msg.content)}
            onSwitchVersion={actions.onSwitchVersion}
            onRegenerate={actions.onRegenerate}
            onInspect={actions.onInspect}
          />
        )}
      </div>
    </div>
  );
};
