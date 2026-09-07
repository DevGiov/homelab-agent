import type { ChatResponse, LettaMessage, FormattedMessage, AgentMode } from '../api';

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
    plan_steps: response.plan_steps?.map((s) => s.replace(/^\d+[\.\)]\s*/, '').trim()),
    plan_structure: response.plan_structure,
    execution_trace: response.execution_trace,
    rollback_trace: response.rollback_trace,
    reasoning_content: response.reasoning_content,
    web_prefetch: response.web_prefetch,
    metrics: response.metrics,
    isError: Boolean(response.error),
    approval_required: response.approval_required,
    request_id: response.request_id,
    approval_prompt: response.approval_prompt,
    command_preview: response.command_preview,
    command_prefix: response.command_prefix,
    risk_reason: response.risk_reason,
  };
}

/**
 * Converts an array of raw LettaMessages into normalized FormattedMessage items.
 * Safely handles historical messages without breaking if metadata is missing.
 */
export function adaptLettaMessagesToMessages(messages: LettaMessage[]): FormattedMessage[] {
  const chatMsgs: FormattedMessage[] = [];

  // Filter only user and assistant messages with non-empty content
  const filtered = messages.filter(
    (m) => (m.message_type === 'user_message' || m.message_type === 'assistant_message') && m.content
  );

  // Sort chronologically
  filtered.sort((a, b) => {
    const dateA = a.date ? new Date(a.date).getTime() : 0;
    const dateB = b.date ? new Date(b.date).getTime() : 0;
    return dateA - dateB;
  });

  filtered.forEach((m, idx) => {
    const timeStr = m.date
      ? new Date(m.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : '';

    let rawContent = m.content || '';

    // Structured metadata fallback check
    let mode: string | undefined = m.metadata?.mode;
    let tool_used: string | undefined = m.tool_name || m.metadata?.tool_used;
    let plan_steps: string[] | undefined = m.metadata?.plan_steps;
    let plan_structure = m.metadata?.plan_structure;
    let execution_trace = m.metadata?.execution_trace;

    // Legacy string parsing fallbacks for older messages without structured metadata
    if (!mode) {
      const modeMatch = rawContent.match(/\[Mode:\s*([A-Za-z]+)\]/i);
      if (modeMatch) {
        mode = modeMatch[1].toLowerCase();
      }
    }

    if (!tool_used) {
      const toolMatch = rawContent.match(/Tool utilizzato:\s*([^\n]+)/i);
      if (toolMatch) {
        tool_used = toolMatch[1].trim().replace(/`/g, '');
      }
    }

    if (!plan_steps && rawContent.includes('Passaggi di esecuzione:')) {
      const planSection = rawContent.split('Passaggi di esecuzione:')[1];
      if (planSection) {
        const lines = planSection
          .split('\n')
          .map((l) => l.trim())
          .filter((l) => /^\d+\.\s+/.test(l));
        if (lines.length > 0) {
          plan_steps = lines.map((l) => l.replace(/^\d+\.\s+/, ''));
        }
      }
    }

    // Clean legacy tags from content
    const content = rawContent.replace(/\[Mode:\s*[A-Za-z]+\]\n?/i, '').trim();

    chatMsgs.push({
      id: m.id || `msg_hist_${idx}`,
      sender: m.message_type === 'user_message' ? 'user' : 'assistant',
      content,
      timestamp: timeStr,
      mode: mode as AgentMode,
      tool_used,
      plan_steps,
      plan_structure,
      execution_trace,
    });
  });

  return chatMsgs;
}
