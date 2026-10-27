// Trasformazioni pure sui messaggi della chat usate da useChat.
import type {
  ChatResponse,
  ExecutionTraceItem,
  FormattedMessage,
  MessageVersion,
  PlanStructure,
  RollbackAction,
  StreamSnapshot,
  WebPrefetchData,
} from '../api/chat';
import { adaptChatResponseToMessage } from './messageAdapter';

/** Contenuto del pannello diagnostica: riflette l'ultima risposta dell'assistente. */
export interface ChatDiagnostics {
  activeTool?: string;
  activePlan?: string[];
  activePlanStructure?: PlanStructure;
  activeExecutionTrace?: ExecutionTraceItem[];
  activeRollbackTrace?: RollbackAction[];
  activeMode?: string;
  activeWebPrefetch?: WebPrefetchData;
}

interface DiagnosticsSource {
  tool_used?: string;
  plan_steps?: string[];
  plan_structure?: PlanStructure;
  execution_trace?: ExecutionTraceItem[];
  rollback_trace?: RollbackAction[];
  mode?: string;
  web_prefetch?: WebPrefetchData;
}

export function diagnosticsOf(source?: DiagnosticsSource): ChatDiagnostics {
  if (!source) return {};
  return {
    activeTool: source.tool_used,
    activePlan: source.plan_steps,
    activePlanStructure: source.plan_structure,
    activeExecutionTrace: source.execution_trace,
    activeRollbackTrace: source.rollback_trace,
    activeMode: source.mode,
    activeWebPrefetch: source.web_prefetch,
  };
}

export function lastAssistant(messages: FormattedMessage[]): FormattedMessage | undefined {
  return [...messages].reverse().find((m) => m.sender === 'assistant');
}

export function nowTime(): string {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function extractMessageVersion(msg: FormattedMessage): MessageVersion {
  const { sender: _sender, versions: _versions, versionIndex: _versionIndex, ...version } = msg;
  return version;
}

/** Messaggio definitivo dalla risposta `final`: mantiene l'id del placeholder e il reasoning già ricevuto in streaming. */
export function finalizeMessage(response: ChatResponse, id: string, streamedReasoning?: string): FormattedMessage {
  const final = adaptChatResponseToMessage(response);
  return { ...final, id, reasoning_content: final.reasoning_content || streamedReasoning };
}

/** Applica lo snapshot `sync` (stato accumulato, non un delta) al messaggio in generazione. */
export function applySnapshot(msg: FormattedMessage, snapshot: StreamSnapshot): FormattedMessage {
  return {
    ...msg,
    reasoning_content: snapshot.reasoning_content || msg.reasoning_content || '',
    content: snapshot.content || msg.content || '',
    mode: snapshot.mode || msg.mode,
    tool_used: snapshot.tool_used || msg.tool_used,
    plan_steps: snapshot.plan_steps || msg.plan_steps,
    plan_structure: snapshot.plan_structure || msg.plan_structure,
    execution_trace: snapshot.execution_trace || msg.execution_trace,
    metrics: snapshot.metrics || msg.metrics,
  };
}

/** Copia contenuto e reasoning nella versione `index`, così il carosello mostra la rigenerazione in corso. */
export function mirrorToVersion(msg: FormattedMessage, index: number): FormattedMessage {
  if (!msg.versions?.[index]) return msg;
  const versions = [...msg.versions];
  versions[index] = { ...versions[index], content: msg.content, reasoning_content: msg.reasoning_content };
  return { ...msg, versions };
}

/** Aggiorna i dati del web prefetch nel pannello diagnostica dagli eventi `retrieval`. */
export function webPrefetchFromEvent(
  current: WebPrefetchData | undefined,
  event: string,
  data: any,
  query: string
): WebPrefetchData | undefined {
  if (event === 'web_prefetch.started') {
    return { query: data.query || query, success: true, sources: [] };
  }
  if (event === 'web_prefetch.completed') {
    return { ...(current || { query, success: true }), provider_used: data.provider, latency_ms: data.latency_ms };
  }
  return current;
}
