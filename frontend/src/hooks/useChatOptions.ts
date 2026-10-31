import { useEffect, useRef, useState } from 'react';
import type { AgentMode, WebSearchMode } from '../api/chat';
import { useSecurityMode } from './useSecurityMode';
import type { SendOptions } from './useChat';

const WEB_SEARCH_KEY = 'homelab_web_search_mode';
const NEXT_WEB_SEARCH: Record<WebSearchMode, WebSearchMode> = { auto: 'on', on: 'off', off: 'auto' };

function storedWebSearch(): WebSearchMode {
  const saved = localStorage.getItem(WEB_SEARCH_KEY);
  return saved === 'on' || saved === 'off' ? saved : 'auto';
}

/**
 * Opzioni del prossimo invio scelte nella UI; web search e modalità di sicurezza persistono in localStorage.
 *
 * Il modello segue quello caricato sul server (`loadedModel`, o 'default' se nessuno lo è) finché l'utente non ne
 * sceglie uno nel thread: aprire un altro thread, o una chat nuova, torna a seguire il modello caricato. Il thread creato
 * dal primo messaggio di una chat nuova (da null a un id) è la stessa chat e tiene la scelta.
 */
export function useChatOptions(threadId: string | null = null, loadedModel: string | null = null) {
  const [mode, setMode] = useState<AgentMode | 'auto'>('auto');
  const [execute, setExecute] = useState(true);
  const [reasoningBudget, setReasoningBudget] = useState<number | undefined>(undefined);
  const [model, setModelState] = useState(loadedModel ?? 'default');
  const [modelChosen, setModelChosen] = useState(false);
  const [incognito, setIncognito] = useState(false);
  const [webSearch, setWebSearch] = useState<WebSearchMode>(storedWebSearch);
  const [securityMode, setSecurityMode] = useSecurityMode();

  const previousThread = useRef(threadId);
  useEffect(() => {
    if (previousThread.current !== null || threadId === null) setModelChosen(false);
    previousThread.current = threadId;
  }, [threadId]);
  useEffect(() => {
    if (!modelChosen) setModelState(loadedModel ?? 'default');
  }, [modelChosen, loadedModel]);

  const setModel = (next: string) => {
    setModelChosen(true);
    setModelState(next);
  };

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
