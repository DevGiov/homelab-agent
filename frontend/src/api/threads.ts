import type { FormattedMessage, MessageVersion } from './chat';
import { http } from './http';

export interface ThreadItem {
  thread_id: string;
  title?: string;
  last_message: string | null;
  checkpoint_count: number;
  is_active?: boolean;
}

export interface LettaMessage {
  id: string;
  date?: string;
  message_type: 'user_message' | 'assistant_message' | 'system_message' | 'reasoning_message' | 'tool_call_message' | 'tool_return_message' | string;
  content: string | null;
  tool_name?: string;
  metadata?: Record<string, any>;
}

export interface ThreadDetails {
  thread_id: string;
  title?: string;
  agent_id?: string;
  checkpoint_count?: number;
  messages?: FormattedMessage[];
  letta_messages?: LettaMessage[];
  is_active?: boolean;
  is_paused?: boolean;
  active_snapshot?: any;
}

const threadPath = (threadId: string) => `/threads/${encodeURIComponent(threadId)}`;

export function listThreads(): Promise<ThreadItem[]> {
  return http.get('/threads');
}

export function getThreadDetails(threadId: string): Promise<ThreadDetails> {
  return http.get(threadPath(threadId));
}

export function deleteThread(threadId: string): Promise<{ status: string }> {
  return http.delete(threadPath(threadId));
}

export function deleteAllThreads(): Promise<{ status: string }> {
  return http.delete('/threads');
}

// Versioni dei messaggi: persistenza best effort, la UI le ha già applicate in locale

export async function switchMessageVersion(threadId: string, messageId: string, versionIndex: number): Promise<void> {
  try {
    await http.post(`${threadPath(threadId)}/messages/${messageId}/version`, { version_index: versionIndex });
  } catch (err) {
    console.warn('Indice di versione non salvato sul backend:', err);
  }
}

export async function saveMessageVersions(
  threadId: string,
  messageId: string,
  versions: MessageVersion[],
  versionIndex: number
): Promise<void> {
  try {
    await http.post(`${threadPath(threadId)}/messages/${messageId}/versions_data`, {
      versions,
      version_index: versionIndex,
    });
  } catch (err) {
    console.warn('Versioni non salvate sul backend:', err);
  }
}
