import { useState, useCallback, useRef, useEffect } from 'react';
import {
  sendStreamMessage,
  attachToThreadStream,
  stopChatStream,
  pauseChatStream,
  resumeChatStream,
  type AgentMode,
  type ChatRequest,
  type FormattedMessage,
  type MessageVersion,
  type SecurityMode,
  type StreamHandlers,
  type WebSearchMode,
} from '../api/chat';
import { getThreadDetails, saveMessageVersions, switchMessageVersion } from '../api/threads';
import { formatApiError } from '../utils/error';
import {
  applySnapshot,
  diagnosticsOf,
  extractMessageVersion,
  finalizeMessage,
  lastAssistant,
  mirrorToVersion,
  nowTime,
  webPrefetchFromEvent,
  type ChatDiagnostics,
} from '../utils/chatMessages';

export interface SendOptions {
  mode?: AgentMode;
  execute: boolean;
  reasoningBudget?: number;
  model?: string;
  incognito?: boolean;
  webSearch?: WebSearchMode;
  images?: string[];
  securityMode?: SecurityMode;
}

export interface PromptEdit {
  content: string;
  mode?: AgentMode;
  model?: string;
  reasoningBudget?: number;
}

type MessageUpdate = (fn: (msg: FormattedMessage) => FormattedMessage) => void;

export function useChat(currentThreadId: string | null, onThreadCreated?: (id: string) => void) {
  const [threadMessagesMap, setThreadMessagesMap] = useState<Record<string, FormattedMessage[]>>({});
  const [currentThreadTitle, setCurrentThreadTitle] = useState<string | null>(null);
  const [isLoadingChat, setIsLoadingChat] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<ChatDiagnostics>({});

  const isSendingRef = useRef<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeThreadIdRef = useRef<string | null>(null);

  const updateThread = useCallback((threadId: string, fn: (msgs: FormattedMessage[]) => FormattedMessage[]) => {
    setThreadMessagesMap((prev) => ({ ...prev, [threadId]: fn(prev[threadId] || []) }));
  }, []);

  const messageUpdater = useCallback(
    (threadId: string, msgId: string): MessageUpdate =>
      (fn) => updateThread(threadId, (msgs) => msgs.map((m) => (m.id === msgId ? fn(m) : m))),
    [updateThread]
  );

  /** Handler comuni per i delta in streaming del messaggio dell'assistente aggiornato da `update`. */
  const liveHandlers = useCallback(
    (update: MessageUpdate, query: string): StreamHandlers => ({
      onReasoning: (delta) => update((m) => ({ ...m, reasoning_content: (m.reasoning_content || '') + delta })),
      onContent: (delta) => update((m) => ({ ...m, content: (m.content || '') + delta })),
      onMetrics: (metrics) => update((m) => ({ ...m, metrics })),
      onSync: (snapshot) => {
        update((m) => applySnapshot(m, snapshot));
        if (snapshot.is_paused !== undefined) setIsPaused(Boolean(snapshot.is_paused));
      },
      onRetrieval: (event, data) =>
        setDiagnostics((d) => ({ ...d, activeWebPrefetch: webPrefetchFromEvent(d.activeWebPrefetch, event, data, query) })),
    }),
    []
  );

  const startStream = useCallback(() => {
    const controller = new AbortController();
    abortControllerRef.current = controller;
    isSendingRef.current = true;
    setIsLoadingChat(true);
    return controller.signal;
  }, []);

  const endStream = useCallback(() => {
    setIsLoadingChat(false);
    setIsPaused(false);
    isSendingRef.current = false;
    abortControllerRef.current = null;
  }, []);

  const loadThreadHistory = useCallback(
    async (threadId: string) => {
      if (isSendingRef.current && activeThreadIdRef.current === threadId) return;
      setIsLoadingChat(true);
      let details;
      try {
        details = await getThreadDetails(threadId);
      } catch (err) {
        console.warn(`Storico del thread ${threadId} non caricato:`, err);
        setIsLoadingChat(false);
        return;
      }

      const messages = details.messages ?? [];
      setCurrentThreadTitle(details.title || null);
      updateThread(threadId, () => messages);
      setDiagnostics(diagnosticsOf(lastAssistant(messages)));

      if (!details.is_active) {
        setIsLoadingChat(false);
        return;
      }

      // Turno ancora in esecuzione in background: ci si riaggancia allo stream live
      activeThreadIdRef.current = threadId;
      setIsPaused(Boolean(details.is_paused));
      const assistantMsgId = lastAssistant(messages)?.id ?? `ast_live_${threadId}`;
      const update = messageUpdater(threadId, assistantMsgId);
      const signal = startStream();
      attachToThreadStream(
        threadId,
        {
          ...liveHandlers(update, ''),
          onFinal: (response) => {
            update((m) => finalizeMessage(response, m.id, m.reasoning_content));
            setDiagnostics(diagnosticsOf(response));
          },
        },
        signal
      )
        .catch((err) => console.error('Errore nello stream riagganciato:', err))
        .finally(endStream);
    },
    [updateThread, messageUpdater, liveHandlers, startStream, endStream]
  );

  useEffect(() => {
    if (currentThreadId && !isSendingRef.current) {
      loadThreadHistory(currentThreadId);
    }
  }, [currentThreadId, loadThreadHistory]);

  const handleSendMessage = useCallback(
    async (input: string, options: SendOptions) => {
      setChatError(null);
      setIsPaused(false);

      const threadId = currentThreadId || `thread_${Date.now()}`;
      activeThreadIdRef.current = threadId;
      if (!currentThreadId) onThreadCreated?.(threadId);

      const images = options.images?.length ? options.images : undefined;
      const timestamp = nowTime();
      const assistantMsgId = `ast_${Date.now()}`;
      updateThread(threadId, (msgs) => [
        ...msgs,
        { id: `user_${Date.now()}`, sender: 'user', content: input, images, timestamp, security_mode: options.securityMode },
        { id: assistantMsgId, sender: 'assistant', content: '', reasoning_content: '', timestamp },
      ]);

      const request: ChatRequest = {
        input,
        thread_id: threadId,
        force_mode: options.mode,
        execute: options.execute,
        reasoning_budget: options.reasoningBudget,
        model: options.model,
        incognito: options.incognito,
        web_search: options.webSearch,
        images,
        security_mode: options.securityMode,
      };
      const update = messageUpdater(threadId, assistantMsgId);
      const signal = startStream();
      try {
        await sendStreamMessage(
          request,
          {
            ...liveHandlers(update, input),
            onFinal: (response) => {
              update((m) => finalizeMessage(response, m.id, m.reasoning_content));
              setDiagnostics(diagnosticsOf(response));
            },
          },
          signal
        );
      } catch (err) {
        console.error('Invio del messaggio fallito:', err);
        const errMsg = formatApiError(err, "Invio del messaggio all'agente non riuscito");
        setChatError(`API Error: ${errMsg}`);
        updateThread(threadId, (msgs) => [
          ...msgs.filter((m) => m.id !== assistantMsgId),
          { id: `err_${Date.now()}`, sender: 'assistant', content: `Error: ${errMsg}`, timestamp: nowTime(), isError: true },
        ]);
      } finally {
        endStream();
      }
    },
    [currentThreadId, onThreadCreated, updateThread, messageUpdater, liveHandlers, startStream, endStream]
  );

  const withActiveThread = useCallback(
    async (action: (threadId: string) => Promise<unknown>, label: string) => {
      const threadId = activeThreadIdRef.current || currentThreadId;
      if (!threadId) return false;
      try {
        await action(threadId);
        return true;
      } catch (err) {
        console.warn(`${label} non riuscito:`, err);
        return false;
      }
    },
    [currentThreadId]
  );

  const handleStop = useCallback(async () => {
    abortControllerRef.current?.abort();
    await withActiveThread(stopChatStream, 'Stop');
    endStream();
  }, [withActiveThread, endStream]);

  const handlePause = useCallback(async () => {
    if (await withActiveThread(pauseChatStream, 'Pausa')) setIsPaused(true);
  }, [withActiveThread]);

  const handleResume = useCallback(async () => {
    if (await withActiveThread(resumeChatStream, 'Ripresa')) setIsPaused(false);
  }, [withActiveThread]);

  const handleSwitchVersion = useCallback(
    (messageId: string, targetIndex: number) => {
      if (!currentThreadId) return;
      const msgs = threadMessagesMap[currentThreadId] || [];
      const updated = msgs.map((m) => {
        const target = m.versions?.[targetIndex];
        return m.id === messageId && target ? { ...m, ...target, versionIndex: targetIndex, versions: m.versions } : m;
      });
      updateThread(currentThreadId, () => updated);
      const last = lastAssistant(updated);
      if (last?.id === messageId) setDiagnostics(diagnosticsOf(last));
      switchMessageVersion(currentThreadId, messageId, targetIndex);
    },
    [currentThreadId, threadMessagesMap, updateThread]
  );

  /** Rigenera la risposta; `editedPrompt` è il prompt appena modificato, non ancora visibile nello stato. */
  const handleRegenerateMessage = useCallback(
    async (assistantMsgId: string, editedPrompt?: FormattedMessage) => {
      if (!currentThreadId || isLoadingChat) return;
      const threadId = currentThreadId;
      const msgs = threadMessagesMap[threadId] || [];
      const astIndex = msgs.findIndex((m) => m.id === assistantMsgId);
      if (astIndex === -1) return;
      const astMsg = msgs[astIndex];
      const userMsg = editedPrompt ?? msgs.slice(0, astIndex).reverse().find((m) => m.sender === 'user');
      if (!userMsg) return;

      // La rigenerazione diventa una nuova versione nel carosello del messaggio
      const versions: MessageVersion[] = [
        ...(astMsg.versions?.length ? astMsg.versions : [extractMessageVersion(astMsg)]),
        { id: `ast_regen_${Date.now()}`, content: '', reasoning_content: '', timestamp: nowTime(), mode: astMsg.mode },
      ];
      const versionIndex = versions.length - 1;
      const update = messageUpdater(threadId, assistantMsgId);
      update((m) => ({
        ...m,
        content: '',
        reasoning_content: '',
        execution_trace: undefined,
        plan_steps: undefined,
        plan_structure: undefined,
        metrics: undefined,
        isError: false,
        versionIndex,
        versions,
      }));
      const updateWithVersion: MessageUpdate = (fn) => update((m) => mirrorToVersion(fn(m), versionIndex));
      const live = liveHandlers(updateWithVersion, userMsg.content);
      let streamedReasoning = '';

      const signal = startStream();
      try {
        await sendStreamMessage(
          {
            input: userMsg.content,
            thread_id: threadId,
            force_mode: (userMsg.mode as AgentMode) || undefined,
            execute: true,
            reasoning_budget: userMsg.reasoningBudget,
            model: userMsg.model,
            images: userMsg.images,
            security_mode: userMsg.security_mode,
          },
          {
            ...live,
            onReasoning: (delta) => {
              streamedReasoning += delta;
              live.onReasoning?.(delta);
            },
            onFinal: (response) => {
              if (response.thread_title) setCurrentThreadTitle(response.thread_title);
              const final = finalizeMessage(response, assistantMsgId, streamedReasoning);
              const finalVersions = versions.map((v, idx) => (idx === versionIndex ? extractMessageVersion(final) : v));
              update((m) => ({ ...m, ...final, versions: finalVersions, versionIndex }));
              saveMessageVersions(threadId, assistantMsgId, finalVersions, versionIndex);
              setDiagnostics(diagnosticsOf(response));
            },
          },
          signal
        );
      } catch (err) {
        console.error('Rigenerazione fallita:', err);
        const errMsg = formatApiError(err, 'Errore durante la rigenerazione');
        setChatError(errMsg);
        update((m) => ({ ...m, content: `[Errore: ${errMsg}]`, isError: true }));
      } finally {
        endStream();
      }
    },
    [currentThreadId, isLoadingChat, threadMessagesMap, messageUpdater, liveHandlers, startStream, endStream]
  );

  const handleEditPrompt = useCallback(
    async (userMsgId: string, edit: PromptEdit) => {
      if (!currentThreadId || isLoadingChat) return;
      const msgs = threadMessagesMap[currentThreadId] || [];
      const userIndex = msgs.findIndex((m) => m.id === userMsgId);
      if (userIndex === -1) return;
      const userMsg = msgs[userIndex];

      // Il prompt modificato diventa una nuova versione del messaggio utente
      const timestamp = nowTime();
      const { content, mode, model, reasoningBudget } = edit;
      const versions: MessageVersion[] = [
        ...(userMsg.versions?.length ? userMsg.versions : [extractMessageVersion(userMsg)]),
        { id: `user_edit_${Date.now()}`, content, timestamp, mode, model, reasoningBudget, images: userMsg.images },
      ];
      const versionIndex = versions.length - 1;
      const editedMsg: FormattedMessage = { ...userMsg, content, mode, model, reasoningBudget, timestamp, versions, versionIndex };
      messageUpdater(currentThreadId, userMsgId)(() => editedMsg);
      saveMessageVersions(currentThreadId, userMsgId, versions, versionIndex);

      const nextMsg = msgs[userIndex + 1];
      if (nextMsg?.sender === 'assistant') {
        await handleRegenerateMessage(nextMsg.id, editedMsg);
      } else {
        await handleSendMessage(content, {
          mode,
          execute: true,
          reasoningBudget,
          model,
          images: userMsg.images,
          securityMode: userMsg.security_mode,
        });
      }
    },
    [currentThreadId, isLoadingChat, threadMessagesMap, messageUpdater, handleRegenerateMessage, handleSendMessage]
  );

  const handleApprovalResolved = useCallback(
    async (action: string, res?: any) => {
      if (!currentThreadId) return;

      // Aggiornamento ottimistico se la risoluzione restituisce già la risposta del tool
      if (res?.response) {
        const executionTrace = res.execution_trace || [
          {
            step_id: 1,
            tool_name: res.tool_name || 'tool',
            args: res.arguments,
            result: res.result,
            reasoning: `Tool approvato ed eseguito (${action})`,
          },
        ];
        updateThread(currentThreadId, (msgs) => [
          ...msgs,
          {
            id: `ast_res_${Date.now()}`,
            sender: 'assistant',
            content: res.response,
            timestamp: nowTime(),
            mode: 'act',
            tool_used: res.tool_name,
            execution_trace: executionTrace,
          },
        ]);
        setDiagnostics((d) => ({
          ...d,
          activeTool: res.tool_name || d.activeTool,
          activeExecutionTrace: res.execution_trace || d.activeExecutionTrace,
        }));
      }

      // Sincronizzazione completa con lo stato salvato dal backend
      await loadThreadHistory(currentThreadId);
    },
    [currentThreadId, updateThread, loadThreadHistory]
  );

  const currentMessages = currentThreadId ? threadMessagesMap[currentThreadId] || [] : [];

  return {
    currentMessages,
    currentThreadTitle,
    isLoadingChat,
    isPaused,
    chatError,
    setChatError,
    handleSendMessage,
    handleRegenerateMessage,
    handleEditPrompt,
    handleSwitchVersion,
    handleStop,
    handlePause,
    handleResume,
    loadThreadHistory,
    handleApprovalResolved,
    diagnostics,
  };
}
