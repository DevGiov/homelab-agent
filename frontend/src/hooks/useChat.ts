import { useState, useCallback, useRef, useEffect } from 'react';
import {
  sendStreamMessage,
  attachToThreadStream,
  stopChatStream,
  pauseChatStream,
  resumeChatStream,
  getThreadDetails,
  saveMessageVersions,
  switchMessageVersion,
  type FormattedMessage,
  type MessageVersion,
  type AgentMode,
  type ExecutionTraceItem,
  type PlanStructure,
  type RollbackAction,
  type WebPrefetchData,
  type StreamMetrics,
} from '../api';
import { adaptChatResponseToMessage, adaptLettaMessagesToMessages } from '../utils/messageAdapter';

function extractMessageVersion(msg: FormattedMessage): MessageVersion {
  return {
    id: msg.id,
    content: msg.content,
    timestamp: msg.timestamp,
    mode: msg.mode,
    tool_used: msg.tool_used,
    reasoning: msg.reasoning,
    plan_steps: msg.plan_steps,
    plan_structure: msg.plan_structure,
    execution_trace: msg.execution_trace,
    rollback_trace: msg.rollback_trace,
    reasoning_content: msg.reasoning_content,
    web_prefetch: msg.web_prefetch,
    metrics: msg.metrics,
    isError: msg.isError,
    model: msg.model,
    reasoningBudget: msg.reasoningBudget,
    images: msg.images,
    approval_required: msg.approval_required,
    request_id: msg.request_id,
    approval_prompt: msg.approval_prompt,
    command_preview: msg.command_preview,
    command_prefix: msg.command_prefix,
    risk_reason: msg.risk_reason,
    approval_resolved: msg.approval_resolved,
    approval_action: msg.approval_action,
  };
}

export function useChat(currentThreadId: string | null, onThreadCreated?: (id: string) => void) {
  const [threadMessagesMap, setThreadMessagesMap] = useState<Record<string, FormattedMessage[]>>({});
  const [currentThreadTitle, setCurrentThreadTitle] = useState<string | null>(null);
  const [isLoadingChat, setIsLoadingChat] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // Active diagnostics panel state
  const [activeTool, setActiveTool] = useState<string | undefined>(undefined);
  const [activePlan, setActivePlan] = useState<string[] | undefined>(undefined);
  const [activePlanStructure, setActivePlanStructure] = useState<PlanStructure | undefined>(undefined);
  const [activeExecutionTrace, setActiveExecutionTrace] = useState<ExecutionTraceItem[] | undefined>(undefined);
  const [activeRollbackTrace, setActiveRollbackTrace] = useState<RollbackAction[] | undefined>(undefined);
  const [activeMode, setActiveMode] = useState<string | undefined>(undefined);
  const [activeWebPrefetch, setActiveWebPrefetch] = useState<WebPrefetchData | undefined>(undefined);

  const isSendingRef = useRef<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeThreadIdRef = useRef<string | null>(null);

  // Load history for a thread
  const loadThreadHistory = useCallback(async (threadId: string) => {
    if (isSendingRef.current && activeThreadIdRef.current === threadId) return;
    setIsLoadingChat(true);
    let isActive = false;
    try {
      const details = await getThreadDetails(threadId);
      if (details) {
        setCurrentThreadTitle(details.title || null);
        isActive = Boolean(details.is_active);
        let parsedMsgs: FormattedMessage[] = [];
        if (details.messages && details.messages.length > 0) {
          parsedMsgs = details.messages;
        } else if (details.letta_messages && details.letta_messages.length > 0) {
          parsedMsgs = adaptLettaMessagesToMessages(details.letta_messages);
        }

        setThreadMessagesMap((prev) => ({
          ...prev,
          [threadId]: parsedMsgs,
        }));

        // Update diagnostic panel from last assistant message
        const lastAssistant = [...parsedMsgs].reverse().find((m) => m.sender === 'assistant');
        if (lastAssistant) {
          setActiveMode(lastAssistant.mode);
          setActiveTool(lastAssistant.tool_used);
          setActivePlan(lastAssistant.plan_steps);
          setActivePlanStructure(lastAssistant.plan_structure);
          setActiveExecutionTrace(lastAssistant.execution_trace);
          setActiveRollbackTrace(lastAssistant.rollback_trace);
          setActiveWebPrefetch(lastAssistant.web_prefetch);
        } else {
          setActiveMode(undefined);
          setActiveTool(undefined);
          setActivePlan(undefined);
          setActivePlanStructure(undefined);
          setActiveExecutionTrace(undefined);
          setActiveRollbackTrace(undefined);
          setActiveWebPrefetch(undefined);
        }

        // Se l'esecuzione è attiva in background su questo thread, ci agganciamo allo streaming live
        if (isActive) {
          isSendingRef.current = true;
          setIsPaused(Boolean(details.is_paused));
          activeThreadIdRef.current = threadId;

          const runningMsg = [...parsedMsgs].reverse().find((m) => m.sender === 'assistant');
          const assistantMsgId = runningMsg ? runningMsg.id : `ast_live_${threadId}`;

          const abortController = new AbortController();
          abortControllerRef.current = abortController;

          attachToThreadStream(
            threadId,
            (reasoningDelta) => {
              setThreadMessagesMap((prev) => {
                const msgs = prev[threadId] || [];
                return {
                  ...prev,
                  [threadId]: msgs.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, reasoning_content: (m.reasoning_content || '') + reasoningDelta }
                      : m
                  ),
                };
              });
            },
            (contentDelta) => {
              setThreadMessagesMap((prev) => {
                const msgs = prev[threadId] || [];
                return {
                  ...prev,
                  [threadId]: msgs.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: (m.content || '') + contentDelta }
                      : m
                  ),
                };
              });
            },
            (finalResponse) => {
              const assistantMsg = adaptChatResponseToMessage(finalResponse);
              assistantMsg.id = assistantMsgId;
              if (!assistantMsg.metrics && finalResponse.metrics) {
                assistantMsg.metrics = finalResponse.metrics;
              }
              setThreadMessagesMap((prev) => {
                const msgs = prev[threadId] || [];
                return {
                  ...prev,
                  [threadId]: msgs.map((m) => (m.id === assistantMsgId ? assistantMsg : m)),
                };
              });
              setActiveTool(finalResponse.tool_used);
              setActivePlan(finalResponse.plan_steps);
              setActivePlanStructure(finalResponse.plan_structure);
              setActiveExecutionTrace(finalResponse.execution_trace);
              setActiveRollbackTrace(finalResponse.rollback_trace);
              setActiveMode(finalResponse.mode);
              setActiveWebPrefetch(finalResponse.web_prefetch);
              setIsLoadingChat(false);
              isSendingRef.current = false;
              setIsPaused(false);
            },
            (err) => {
              console.error('Error in attached thread stream:', err);
              setIsLoadingChat(false);
              isSendingRef.current = false;
              setIsPaused(false);
            },
            (retrievalEvent, retrievalData) => {
              if (retrievalEvent === 'web_prefetch.started') {
                setActiveWebPrefetch({
                  query: retrievalData.query || '',
                  success: true,
                  sources: [],
                });
              } else if (retrievalEvent === 'web_prefetch.completed') {
                setActiveWebPrefetch((prev) => ({
                  ...(prev || { query: '', success: true }),
                  provider_used: retrievalData.provider,
                  latency_ms: retrievalData.latency_ms,
                }));
              }
            },
            (metricsData) => {
              setThreadMessagesMap((prev) => {
                const msgs = prev[threadId] || [];
                return {
                  ...prev,
                  [threadId]: msgs.map((m) =>
                    m.id === assistantMsgId ? { ...m, metrics: metricsData } : m
                  ),
                };
              });
            },
            (snapshot) => {
              setThreadMessagesMap((prev) => {
                const msgs = prev[threadId] || [];
                return {
                  ...prev,
                  [threadId]: msgs.map((m) =>
                    m.id === assistantMsgId
                      ? {
                          ...m,
                          reasoning_content: snapshot.reasoning_content || m.reasoning_content || '',
                          content: snapshot.content || m.content || '',
                          mode: snapshot.mode || m.mode,
                          tool_used: snapshot.tool_used || m.tool_used,
                          plan_steps: snapshot.plan_steps || m.plan_steps,
                          plan_structure: snapshot.plan_structure || m.plan_structure,
                          execution_trace: snapshot.execution_trace || m.execution_trace,
                          metrics: snapshot.metrics || m.metrics,
                        }
                      : m
                  ),
                };
              });
              if (snapshot.is_paused !== undefined) {
                setIsPaused(Boolean(snapshot.is_paused));
              }
            },
            abortController.signal
          ).finally(() => {
            setIsLoadingChat(false);
            isSendingRef.current = false;
          });
        }
      }
    } catch (err) {
      console.warn(`Could not load history for thread ${threadId}:`, err);
    } finally {
      if (!isActive) {
        setIsLoadingChat(false);
      }
    }
  }, []);

  useEffect(() => {
    if (currentThreadId && !isSendingRef.current) {
      loadThreadHistory(currentThreadId);
    }
  }, [currentThreadId, loadThreadHistory]);

  const handleSendMessage = useCallback(
    async (
      input: string,
      mode: AgentMode | undefined,
      execute: boolean,
      reasoningBudget?: number,
      model?: string,
      incognito?: boolean,
      webSearch?: boolean,
      images?: string[]
    ) => {
      setChatError(null);
      isSendingRef.current = true;
      setIsPaused(false);

      const targetThreadId = currentThreadId || `thread_${Date.now()}`;
      activeThreadIdRef.current = targetThreadId;
      if (!currentThreadId && onThreadCreated) {
        onThreadCreated(targetThreadId);
      }

      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const userMsg: FormattedMessage = {
        id: `user_${Date.now()}`,
        sender: 'user',
        content: input,
        images: images && images.length > 0 ? images : undefined,
        timestamp,
      };

      setThreadMessagesMap((prev) => ({
        ...prev,
        [targetThreadId]: [...(prev[targetThreadId] || []), userMsg],
      }));

      setIsLoadingChat(true);

      const assistantMsgId = `ast_${Date.now()}`;
      const placeholderMsg: FormattedMessage = {
        id: assistantMsgId,
        sender: 'assistant',
        content: '',
        reasoning_content: '',
        timestamp,
      };

      setThreadMessagesMap((prev) => ({
        ...prev,
        [targetThreadId]: [...(prev[targetThreadId] || []), placeholderMsg],
      }));

      try {
        await sendStreamMessage(
          {
            input,
            thread_id: targetThreadId,
            force_mode: mode,
            execute,
            reasoning_budget: reasoningBudget,
            model,
            incognito,
            web_search: webSearch,
            images: images && images.length > 0 ? images : undefined,
          },
          (reasoningDelta) => {
            setThreadMessagesMap((prev) => {
              const msgs = prev[targetThreadId] || [];
              return {
                ...prev,
                [targetThreadId]: msgs.map((m) =>
                  m.id === assistantMsgId ? { ...m, reasoning_content: (m.reasoning_content || '') + reasoningDelta } : m
                ),
              };
            });
          },
          (contentDelta) => {
            setThreadMessagesMap((prev) => {
              const msgs = prev[targetThreadId] || [];
              return {
                ...prev,
                [targetThreadId]: msgs.map((m) =>
                  m.id === assistantMsgId ? { ...m, content: m.content + contentDelta } : m
                ),
              };
            });
          },
          (finalResponse) => {
            const assistantMsg = adaptChatResponseToMessage(finalResponse);
            assistantMsg.id = assistantMsgId; // preserve id
            if (!assistantMsg.metrics && finalResponse.metrics) {
              assistantMsg.metrics = finalResponse.metrics;
            }
            const finalThreadId = finalResponse.thread_id || targetThreadId;

            setThreadMessagesMap((prev) => {
              const msgs = prev[targetThreadId] || [];
              const updatedMsgs = msgs.map((m) => (m.id === assistantMsgId ? assistantMsg : m));
              
              if (finalThreadId !== targetThreadId) {
                // If thread ID changed (e.g. newly created), move messages
                const { [targetThreadId]: _, ...rest } = prev;
                return { ...rest, [finalThreadId]: updatedMsgs };
              }
              return { ...prev, [finalThreadId]: updatedMsgs };
            });

            // Update Diagnostics
            setActiveTool(finalResponse.tool_used);
            setActivePlan(finalResponse.plan_steps);
            setActivePlanStructure(finalResponse.plan_structure);
            setActiveExecutionTrace(finalResponse.execution_trace);
            setActiveRollbackTrace(finalResponse.rollback_trace);
            setActiveMode(finalResponse.mode);
            setActiveWebPrefetch(finalResponse.web_prefetch);
          },
          (errorStr) => {
            throw new Error(errorStr);
          },
          (retrievalEvent, retrievalData) => {
            if (retrievalEvent === 'web_prefetch.started') {
              setActiveWebPrefetch({
                query: retrievalData.query || input,
                success: true,
                sources: [],
              });
            } else if (retrievalEvent === 'web_prefetch.completed') {
              setActiveWebPrefetch((prev) => ({
                ...(prev || { query: input, success: true }),
                provider_used: retrievalData.provider,
                latency_ms: retrievalData.latency_ms,
              }));
            }
          },
          (metricsData: StreamMetrics) => {
            setThreadMessagesMap((prev) => {
              const msgs = prev[targetThreadId] || [];
              return {
                ...prev,
                [targetThreadId]: msgs.map((m) =>
                  m.id === assistantMsgId ? { ...m, metrics: metricsData } : m
                ),
              };
            });
          },
          abortController.signal
        );
      } catch (err: any) {
        if (err.name === 'AbortError') {
          console.log('Chat execution aborted by user');
          return;
        }
        console.error('API call failed:', err);
        const errMsg = err.response?.data?.detail || err.message || 'Failed to send message to agent';
        setChatError(`API Error: ${errMsg}`);

        const errorMsgItem: FormattedMessage = {
          id: `err_${Date.now()}`,
          sender: 'assistant',
          content: `Error: ${errMsg}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          isError: true,
        };

        setThreadMessagesMap((prev) => {
          const msgs = prev[targetThreadId] || [];
          const filtered = msgs.filter((m) => m.id !== assistantMsgId);
          return {
            ...prev,
            [targetThreadId]: [...filtered, errorMsgItem],
          };
        });
      } finally {
        setIsLoadingChat(false);
        setIsPaused(false);
        isSendingRef.current = false;
        abortControllerRef.current = null;
      }
    },
    [currentThreadId, onThreadCreated]
  );

  const handleStop = useCallback(async () => {
    const threadId = activeThreadIdRef.current || currentThreadId;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (threadId) {
      try {
        await stopChatStream(threadId);
      } catch (e) {
        console.warn('Error sending stop signal to backend:', e);
      }
    }
    setIsPaused(false);
    setIsLoadingChat(false);
    isSendingRef.current = false;
  }, [currentThreadId]);

  const handlePause = useCallback(async () => {
    const threadId = activeThreadIdRef.current || currentThreadId;
    if (threadId) {
      try {
        await pauseChatStream(threadId);
        setIsPaused(true);
      } catch (e) {
        console.warn('Error pausing stream:', e);
      }
    }
  }, [currentThreadId]);

  const handleResume = useCallback(async () => {
    const threadId = activeThreadIdRef.current || currentThreadId;
    if (threadId) {
      try {
        await resumeChatStream(threadId);
        setIsPaused(false);
      } catch (e) {
        console.warn('Error resuming stream:', e);
      }
    }
  }, [currentThreadId]);

  const handleSwitchVersion = useCallback((messageId: string, targetIndex: number) => {
    if (!currentThreadId) return;
    setThreadMessagesMap((prev) => {
      const msgs = prev[currentThreadId] || [];
      return {
        ...prev,
        [currentThreadId]: msgs.map((m) => {
          if (m.id !== messageId || !m.versions || !m.versions[targetIndex]) return m;
          const targetVer = m.versions[targetIndex];
          return {
            ...m,
            ...targetVer,
            versionIndex: targetIndex,
            versions: m.versions,
          };
        }),
      };
    });
    switchMessageVersion(currentThreadId, messageId, targetIndex);
  }, [currentThreadId]);

  const handleRegenerateMessage = useCallback(
    async (assistantMsgId: string) => {
      if (!currentThreadId || isLoadingChat) return;
      const msgs = threadMessagesMap[currentThreadId] || [];
      const astIndex = msgs.findIndex((m) => m.id === assistantMsgId);
      if (astIndex === -1) return;

      const astMsg = msgs[astIndex];
      const userMsg = msgs.slice(0, astIndex).reverse().find((m) => m.sender === 'user');
      if (!userMsg) return;

      const currentVerList: MessageVersion[] =
        astMsg.versions && astMsg.versions.length > 0
          ? [...astMsg.versions]
          : [extractMessageVersion(astMsg)];

      const newVersionSlot: MessageVersion = {
        id: `ast_regen_${Date.now()}`,
        content: '',
        reasoning_content: '',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        mode: astMsg.mode,
      };

      const updatedVersions = [...currentVerList, newVersionSlot];
      const newVersionIndex = updatedVersions.length - 1;

      setThreadMessagesMap((prev) => ({
        ...prev,
        [currentThreadId]: (prev[currentThreadId] || []).map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: '',
                reasoning_content: '',
                execution_trace: undefined,
                plan_steps: undefined,
                plan_structure: undefined,
                metrics: undefined,
                isError: false,
                versionIndex: newVersionIndex,
                versions: updatedVersions,
              }
            : m
        ),
      }));

      setIsLoadingChat(true);
      isSendingRef.current = true;
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        await sendStreamMessage(
          {
            input: userMsg.content,
            thread_id: currentThreadId,
            force_mode: (userMsg.mode as AgentMode) || undefined,
            execute: true,
            reasoning_budget: userMsg.reasoningBudget,
            model: userMsg.model,
            images: userMsg.images,
          },
          (reasoningDelta) => {
            setThreadMessagesMap((prev) => {
              const currentList = prev[currentThreadId] || [];
              return {
                ...prev,
                [currentThreadId]: currentList.map((m) => {
                  if (m.id !== assistantMsgId) return m;
                  const newReasoning = (m.reasoning_content || '') + reasoningDelta;
                  const vers = m.versions ? [...m.versions] : [];
                  if (vers[newVersionIndex]) {
                    vers[newVersionIndex] = { ...vers[newVersionIndex], reasoning_content: newReasoning };
                  }
                  return { ...m, reasoning_content: newReasoning, versions: vers };
                }),
              };
            });
          },
          (contentDelta) => {
            setThreadMessagesMap((prev) => {
              const currentList = prev[currentThreadId] || [];
              return {
                ...prev,
                [currentThreadId]: currentList.map((m) => {
                  if (m.id !== assistantMsgId) return m;
                  const newContent = m.content + contentDelta;
                  const vers = m.versions ? [...m.versions] : [];
                  if (vers[newVersionIndex]) {
                    vers[newVersionIndex] = { ...vers[newVersionIndex], content: newContent };
                  }
                  return { ...m, content: newContent, versions: vers };
                }),
              };
            });
          },
          (finalResponse) => {
            const assistantMsg = adaptChatResponseToMessage(finalResponse);
            assistantMsg.id = assistantMsgId;
            if (!assistantMsg.metrics && finalResponse.metrics) {
              assistantMsg.metrics = finalResponse.metrics;
            }
            if (finalResponse.thread_title) {
              setCurrentThreadTitle(finalResponse.thread_title);
            }
            setThreadMessagesMap((prev) => {
              const currentList = prev[currentThreadId] || [];
              const finalVersions = (currentList.find((m) => m.id === assistantMsgId)?.versions || updatedVersions).map(
                (v, idx) => (idx === newVersionIndex ? extractMessageVersion(assistantMsg) : v)
              );
              saveMessageVersions(currentThreadId, assistantMsgId, finalVersions, newVersionIndex);

              return {
                ...prev,
                [currentThreadId]: currentList.map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        ...assistantMsg,
                        versions: finalVersions,
                        versionIndex: newVersionIndex,
                      }
                    : m
                ),
              };
            });
            setActiveTool(finalResponse.tool_used);
            setActivePlan(finalResponse.plan_steps);
            setActivePlanStructure(finalResponse.plan_structure);
            setActiveExecutionTrace(finalResponse.execution_trace);
            setActiveRollbackTrace(finalResponse.rollback_trace);
            setActiveMode(finalResponse.mode);
            setActiveWebPrefetch(finalResponse.web_prefetch);
          },
          (errorStr) => {
            console.error('Error during regeneration:', errorStr);
            setChatError(errorStr);
          },
          undefined,
          undefined,
          abortController.signal
        );
      } catch (err: any) {
        console.error('Failed to regenerate message:', err);
        const errMsg = err?.message || 'Errore durante la rigenerazione';
        setChatError(errMsg);
        setThreadMessagesMap((prev) => {
          const currentList = prev[currentThreadId] || [];
          return {
            ...prev,
            [currentThreadId]: currentList.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    content: `[Errore: ${errMsg}]`,
                    isError: true,
                  }
                : m
            ),
          };
        });
      } finally {
        setIsLoadingChat(false);
        isSendingRef.current = false;
      }
    },
    [currentThreadId, isLoadingChat, threadMessagesMap]
  );

  const handleEditPrompt = useCallback(
    async (
      userMsgId: string,
      newContent: string,
      mode?: AgentMode,
      model?: string,
      reasoningBudget?: number
    ) => {
      if (!currentThreadId || isLoadingChat) return;
      const msgs = threadMessagesMap[currentThreadId] || [];
      const userIndex = msgs.findIndex((m) => m.id === userMsgId);
      if (userIndex === -1) return;

      const userMsg = msgs[userIndex];
      const currentPromptVers: MessageVersion[] =
        userMsg.versions && userMsg.versions.length > 0
          ? [...userMsg.versions]
          : [extractMessageVersion(userMsg)];

      const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const newPromptVersion: MessageVersion = {
        id: `user_edit_${Date.now()}`,
        content: newContent,
        timestamp,
        mode,
        model,
        reasoningBudget,
        images: userMsg.images,
      };
      const updatedPromptVersions = [...currentPromptVers, newPromptVersion];
      const newPromptVersionIndex = updatedPromptVersions.length - 1;

      setThreadMessagesMap((prev) => ({
        ...prev,
        [currentThreadId]: (prev[currentThreadId] || []).map((m) =>
          m.id === userMsgId
            ? {
                ...m,
                content: newContent,
                mode,
                model,
                reasoningBudget,
                timestamp,
                versions: updatedPromptVersions,
                versionIndex: newPromptVersionIndex,
              }
            : m
        ),
      }));
      saveMessageVersions(currentThreadId, userMsgId, updatedPromptVersions, newPromptVersionIndex);

      const nextMsg = msgs[userIndex + 1];
      if (nextMsg && nextMsg.sender === 'assistant') {
        await handleRegenerateMessage(nextMsg.id);
      } else {
        await handleSendMessage(newContent, mode, true, reasoningBudget, model, undefined, undefined, userMsg.images);
      }
    },
    [currentThreadId, isLoadingChat, threadMessagesMap, handleRegenerateMessage, handleSendMessage]
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
    diagnostics: {
      activeTool,
      activePlan,
      activePlanStructure,
      activeExecutionTrace,
      activeRollbackTrace,
      activeMode,
      activeWebPrefetch,
    },
  };
}
