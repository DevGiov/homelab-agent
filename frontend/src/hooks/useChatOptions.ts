import { useState } from 'react';
import type { AgentMode, WebSearchMode } from '../api/chat';
import { useSecurityMode } from './useSecurityMode';
import type { SendOptions } from './useChat';

const WEB_SEARCH_KEY = 'homelab_web_search_mode';
const NEXT_WEB_SEARCH: Record<WebSearchMode, WebSearchMode> = { auto: 'on', on: 'off', off: 'auto' };

function storedWebSearch(): WebSearchMode {
  const saved = localStorage.getItem(WEB_SEARCH_KEY);
  return saved === 'on' || saved === 'off' ? saved : 'auto';
}

/** Opzioni del prossimo invio scelte nella UI; web search e modalità di sicurezza persistono in localStorage. */
export function useChatOptions() {
  const [mode, setMode] = useState<AgentMode | 'auto'>('auto');
  const [execute, setExecute] = useState(true);
  const [reasoningBudget, setReasoningBudget] = useState<number | undefined>(undefined);
  const [model, setModel] = useState('default');
  const [incognito, setIncognito] = useState(false);
  const [webSearch, setWebSearch] = useState<WebSearchMode>(storedWebSearch);
  const [securityMode, setSecurityMode] = useSecurityMode();

  const cycleWebSearch = () => {
    const next = NEXT_WEB_SEARCH[webSearch];
    localStorage.setItem(WEB_SEARCH_KEY, next);
    setWebSearch(next);
  };

  /** 'auto' e 'default' lasciano la scelta al backend. */
  const toSendOptions = (images?: string[]): SendOptions => ({
    mode: mode === 'auto' ? undefined : mode,
    execute,
    reasoningBudget,
    model: model === 'default' ? undefined : model,
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
    model,
    setModel,
    incognito,
    setIncognito,
    webSearch,
    cycleWebSearch,
    securityMode,
    setSecurityMode,
    toSendOptions,
  };
}

export type ChatOptions = ReturnType<typeof useChatOptions>;
