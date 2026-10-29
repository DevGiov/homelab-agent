import type { ChatResponse, FormattedMessage, AgentMode } from '../api/chat';

/**
 * Converts a raw ChatResponse into a normalized FormattedMessage for the UI.
 */
export function adaptChatResponseToMessage(
  response: ChatResponse
): FormattedMessage {
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const rawText = response.response || '(Nessun contenuto restituito)';

  // Clean prompt artifacts if present
  const cleanedText = rawText
    .replace(/\[Mode:\s*[A-Za-z]+\]\n?/i, '')
    .trim();

  // Normalize mode string to AgentMode union if valid
  const normalizedMode = (
    ['chat', 'ask', 'act', 'plan'].includes(response.mode?.toLowerCase())
      ? response.mode.toLowerCase()
      : response.mode
  ) as AgentMode;

  return {
    id: `msg_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
    sender: 'assistant',
    content: cleanedText,
    timestamp,
    mode: normalizedMode,
    tool_used: response.tool_used,
    reasoning: response.execution_trace?.find((t) => t.reasoning)?.reasoning,
    plan_steps: response.plan_steps?.map((s) => s.replace(/^\d+[.)]\s*/, '').trim()),
    plan_structure: response.plan_structure,
    execution_trace: response.execution_trace,
    rollback_trace: response.rollback_trace,
    reasoning_content: response.reasoning_content,
    web_prefetch: response.web_prefetch,
    metrics: response.metrics,
    model: response.model,
    isError: Boolean(response.error),
    approval_required: response.approval_required,
    request_id: response.request_id,
    approval_prompt: response.approval_prompt,
    command_preview: response.command_preview,
    command_prefix: response.command_prefix,
    risk_reason: response.risk_reason,
    security_mode: response.security_mode,
  };
}
