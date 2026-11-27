import React, { useState } from 'react';
import { Send } from 'lucide-react';
import type { AgentMode, FormattedMessage } from '../../api/chat';
import type { ModelRef } from '../../api/providers';
import type { PromptEdit } from '../../hooks/useChat';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { USER_BUBBLE_BUTTON } from '../../theme/userBubble';
import { ModelSelector } from '../ModelSelector';

interface PromptEditorProps {
  message: FormattedMessage;
  /** Modalità e modello correnti della chat, usati se il messaggio non li ha registrati. */
  defaults: { mode: AgentMode | 'auto'; model: ModelRef | null };
  models: ModelCatalog;
  onSubmit: (edit: PromptEdit) => void;
  onCancel: () => void;
}

export const PromptEditor: React.FC<PromptEditorProps> = ({ message, defaults, models, onSubmit, onCancel }) => {
  const [text, setText] = useState(message.content);
  const [mode, setMode] = useState<AgentMode | 'auto'>((message.mode as AgentMode) || defaults.mode);
  const [selection, setSelection] = useState<ModelRef | null>(
    message.provider && message.model ? { provider: message.provider, model: message.model } : defaults.model
  );

  const submit = () => {
    if (!text.trim()) return;
    onSubmit({
      content: text.trim(),
      mode: mode === 'auto' ? undefined : mode,
      provider: selection?.provider,
      model: selection?.model,
      reasoningBudget: message.reasoningBudget,
    });
  };

  return (
    <div className="in-user-bubble flex flex-col gap-2 min-w-[260px] sm:min-w-[340px] text-fg">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="w-full bg-input-bg/90 border border-border rounded-xl p-2.5 text-xs sm:text-sm text-fg focus:border-accent resize-y min-h-[60px]"
        placeholder="Modifica prompt..."
        aria-label="Prompt"
        autoFocus
      />
      <div className="flex items-center justify-between gap-2 flex-wrap pt-1 border-t border-border/40 text-xs">
        <div className="flex items-center gap-1.5 flex-wrap">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as AgentMode | 'auto')}
            aria-label="Modalità"
            className="bg-panel border border-border rounded-md px-1.5 py-0.5 text-xs text-fg focus:border-accent"
          >
            <option value="auto">Modalità: auto</option>
            <option value="chat">Modalità: chat</option>
            <option value="ask">Modalità: ask</option>
            <option value="act">Modalità: act</option>
            <option value="plan">Modalità: plan</option>
          </select>
          {models.providers.length > 0 && (
            <ModelSelector
              selected={selection}
              onSelect={setSelection}
              providers={models.providers}
              onRefreshModels={models.refreshModels}
            />
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onCancel}
            className="px-2 py-1 rounded-md text-xs text-userBubble-text hover:bg-white/10 transition cursor-pointer"
          >
            Annulla
          </button>
          <button
            type="button"
            onClick={submit}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold ${USER_BUBBLE_BUTTON} shadow-xs transition cursor-pointer flex items-center gap-1`}
          >
            <Send size={10} />
            <span>Invia</span>
          </button>
        </div>
      </div>
    </div>
  );
};
