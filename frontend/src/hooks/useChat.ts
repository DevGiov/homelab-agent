import { useState, useCallback, useRef, useEffect } from 'react';
import {
  sendStreamMessage,
  getThreadDetails,
  type FormattedMessage,
  type AgentMode,
  type ExecutionTraceItem,
  type PlanStructure,
  type RollbackAction,
  type WebPrefetchData,
} from '../api';
import { adaptChatResponseToMessage, adaptLettaMessagesToMessages } from '../utils/messageAdapter';

export function useChat(currentThreadId: string | null, onThreadCreated?: (id: string) => void) {
  const [threadMessagesMap, setThreadMessagesMap] = useState<Record<string, FormattedMessage[]>>({});
  const [isLoadingChat, setIsLoadingChat] = useState<boolean>(false);
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

  // Load history for a thread
  const loadThreadHistory = useCallback(async (threadId: string) => {
    if (isSendingRef.current) return;
    setIsLoadingChat(true);
    try {
      const details = await getThreadDetails(threadId);
      if (details) {
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
      }
    } catch (err) {
      console.warn(`Could not load history for thread ${threadId}:`, err);
    } finally {
      setIsLoadingChat(false);
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
      webSearch?: boolean
    ) => {
      setChatError(null);
      isSendingRef.current = true;

      const targetThreadId = currentThreadId || `thread_${Date.now()}`;
      if (!currentThreadId && onThreadCreated) {
        onThreadCreated(targetThreadId);
      }

      const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const userMsg: FormattedMessage = {
        id: `user_${Date.now()}`,
        sender: 'user',
        content: input,
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
          }
        );
      } catch (err: any) {
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

        setThreadMessagesMap((prev) => ({
          ...prev,
          [targetThreadId]: [...(prev[targetThreadId] || []), errorMsgItem],
        }));
      } finally {
        setIsLoadingChat(false);
        isSendingRef.current = false;
      }
    },
    [currentThreadId, onThreadCreated]
  );

  const currentMessages = currentThreadId ? threadMessagesMap[currentThreadId] || [] : [];

  return {
    currentMessages,
    isLoadingChat,
    chatError,
    setChatError,
    handleSendMessage,
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
