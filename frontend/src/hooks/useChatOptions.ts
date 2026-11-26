import { useEffect, useRef, useState } from 'react';
import type { AgentMode, WebSearchMode } from '../api/chat';
import type { ModelRef } from '../api/providers';
import { useSecurityMode } from './useSecurityMode';
import type { SendOptions } from './useChat';

const WEB_SEARCH_KEY = 'homelab_web_search_mode';

function storedWebSearch(): WebSearchMode {
  try {
    const saved = localStorage.getItem(WEB_SEARCH_KEY);
    return saved === 'on' || saved === 'off' ? saved : 'auto';
  } catch {
    return 'auto';
  }
}

/**
 * Opzioni del prossimo invio scelte nella UI; web search e modalità di sicurezza persistono in localStorage.
 *
 * Il modello è la coppia (provider, modello) ed è per conversazione: vale la scelta fatta dall'utente nel thread, altrimenti
 * quella salvata nella conversazione aperta (`threadModel`), altrimenti la partenza del catalogo (`defaultModel`). Aprire un
 * altro thread, o una chat nuova, scarta la scelta. Il thread creato dal primo messaggio di una chat nuova (da null a un id)
 * è la stessa chat e tiene la scelta.
 */
export function useChatOptions(threadId: string | null = null, defaultModel: ModelRef | null = null, threadModel: ModelRef | null = null) {
  const [mode, setMode] = useState<AgentMode | 'auto'>('auto');
  const [execute, setExecute] = useState(true);
  const [reasoningBudget, setReasoningBudget] = useState<number | undefined>(undefined);
  const [chosen, setChosen] = useState<ModelRef | null>(null);
  const [incognito, setIncognito] = useState(false);
  const [webSearch, setWebSearchState] = useState<WebSearchMode>(storedWebSearch);
  const [securityMode, setSecurityMode] = useSecurityMode();

  const previousThread = useRef(threadId);
  useEffect(() => {
    if (previousThread.current !== null || threadId === null) setChosen(null);
    previousThread.current = threadId;
  }, [threadId]);

  const selection = chosen ?? (threadId ? threadModel : null) ?? defaultModel;
  const setSelection = (next: ModelRef) => setChosen(next);

  const setWebSearch = (next: WebSearchMode) => {
    try {
      localStorage.setItem(WEB_SEARCH_KEY, next);
    } catch {
      // La scelta vale per questa pagina
    }
    setWebSearchState(next);
  };

  /** 'auto' lascia la scelta al backend; senza un modello scelto il backend usa il provider predefinito. */
  const toSendOptions = (images?: string[]): SendOptions => ({
    mode: mode === 'auto' ? undefined : mode,
    execute,
    reasoningBudget,
    provider: selection?.provider,
    model: selection?.model,
    incognito,
    webSearch,
    images,
    securityMode,
  });

  return {
    mode,
    setMode,
    execute,
    setExecute,
    reasoningBudget,
    setReasoningBudget,
    selection,
    setSelection,
    incognito,
    setIncognito,
    webSearch,
    setWebSearch,
    securityMode,
    setSecurityMode,
    toSendOptions,
  };
}

export type ChatOptions = ReturnType<typeof useChatOptions>;
