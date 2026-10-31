import React, { useState } from 'react';
import { AlertTriangle, EyeOff, Image as ImageIcon } from 'lucide-react';
import type { FormattedMessage } from '../../api/chat';
import type { PromptEdit, SendOptions } from '../../hooks/useChat';
import { useChatOptions } from '../../hooks/useChatOptions';
import { useImageAttachments } from '../../hooks/useImageAttachments';
import { useModelCatalog } from '../../hooks/useModelCatalog';
import { ChatComposer } from './ChatComposer';
import { ChatHeader } from './ChatHeader';
import type { MessageActions } from './ChatMessage';
import { ChatOptionsBar } from './ChatOptionsBar';
import { ImageLightbox } from './ImageLightbox';
import { MessageList } from './MessageList';

interface ChatProps {
  currentThreadId: string | null;
  currentThreadTitle?: string | null;
  messages: FormattedMessage[];
  onSendMessage: (input: string, options: SendOptions) => Promise<void>;
  onRegenerate?: (assistantMsgId: string) => Promise<void> | void;
  onEditPrompt?: (userMsgId: string, edit: PromptEdit) => Promise<void> | void;
  onSwitchVersion?: (messageId: string, targetIndex: number) => void;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onApprovalResolved?: (action: string, res?: any) => void;
  isPaused?: boolean;
  isLoading: boolean;
  error: string | null;
  onClearError: () => void;
  onOpenMobileSidebar?: () => void;
  onOpenMobileToolLog?: () => void;
  onInspectMessage?: (assistantMsgId: string) => void;
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
  onApprovalResolved,
  isPaused = false,
  isLoading,
  error,
  onClearError,
  onOpenMobileSidebar,
  onOpenMobileToolLog,
  onInspectMessage,
}) => {
  const models = useModelCatalog();
  const options = useChatOptions(currentThreadId, models.loadedModel);
  const attachments = useImageAttachments();
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  const title = currentThreadTitle || (currentThreadId ? `Thread: ${currentThreadId}` : 'Nuova Sessione');
  const textOnlyModel = options.model !== 'default' && !models.isVisionModel(options.model) ? options.model : null;

  const send = (text: string) => {
    const images = attachments.images.map((img) => img.dataUrl);
    onSendMessage(text, options.toSendOptions(images.length > 0 ? images : undefined));
    attachments.clear();
  };

  const actions: MessageActions = {
    onExecutePlan: (summary) => onSendMessage(summary, { mode: 'act', execute: true, securityMode: options.securityMode }),
    onOpenImage: setLightboxUrl,
    onRegenerate,
    onEditPrompt,
    onSwitchVersion,
    onApprovalResolved,
    onInspect: onInspectMessage,
  };

  return (
    <div
      {...attachments.dropZoneProps}
      className="flex-1 flex flex-col h-full bg-transparent text-fg overflow-hidden relative"
    >
      {attachments.isDragging && (
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

      {options.incognito && (
        <div className="bg-purple-950/70 border-b border-purple-800/50 backdrop-blur-md px-3 sm:px-6 py-1.5 flex items-center justify-between text-[11px] text-purple-200 z-20 shrink-0">
          <div className="flex items-center gap-2 truncate">
            <EyeOff size={13} className="text-purple-400 shrink-0 animate-pulse" />
            <span className="truncate">
              <strong>Modalità Incognito attiva:</strong> memoria a lungo termine disabilitata. Nessun fatto verrà richiamato né
              salvato.
            </span>
          </div>
          <button
            type="button"
            onClick={() => options.setIncognito(false)}
            className="text-purple-300 hover:text-white underline text-[10px] ml-2 shrink-0 cursor-pointer"
          >
            Disattiva
          </button>
        </div>
      )}

      <ChatHeader
        title={title}
        mode={options.mode}
        onModeChange={options.setMode}
        execute={options.execute}
        onExecuteChange={options.setExecute}
        onOpenMobileSidebar={onOpenMobileSidebar}
        onOpenMobileToolLog={onOpenMobileToolLog}
      />

      {error && (
        <div className="bg-rose-950/80 border-b border-rose-800 px-4 sm:px-6 py-2.5 flex items-center justify-between text-xs text-rose-200 shrink-0">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-rose-400 shrink-0" />
            <span className="truncate">{error}</span>
          </div>
          <button onClick={onClearError} className="text-rose-400 hover:text-rose-200 font-bold px-2 py-0.5 cursor-pointer">
            Dismiss
          </button>
        </div>
      )}

      <MessageList
        messages={messages}
        threadId={currentThreadId}
        isLoading={isLoading}
        isPaused={isPaused}
        actions={actions}
        models={models}
        editDefaults={{ mode: options.mode, model: options.model }}
        scrollKey={attachments.images}
      />

      <div className="p-3 sm:p-4 border-t border-border glass-input-bar shrink-0 flex flex-col gap-2">
        <ChatOptionsBar options={options} models={models} />
        <ChatComposer
          attachments={attachments}
          isLoading={isLoading}
          isPaused={isPaused}
          textOnlyModel={textOnlyModel}
          onSend={send}
          onStop={onStop}
          onPause={onPause}
          onResume={onResume}
          onOpenImage={setLightboxUrl}
        />
      </div>

      {lightboxUrl && <ImageLightbox url={lightboxUrl} onClose={() => setLightboxUrl(null)} />}
    </div>
  );
};
