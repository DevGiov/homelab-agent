import React from 'react';
import { Activity, Check, ChevronLeft, ChevronRight, Copy, Cpu, Globe, Pause, RefreshCw, Wrench, Zap } from 'lucide-react';
import type { FormattedMessage } from '../../api/chat';

interface MessageMetaProps {
  message: FormattedMessage;
  /** Il messaggio è l'ultimo e la generazione è in pausa. */
  showPaused: boolean;
  isLoading: boolean;
  copied: boolean;
  onCopy: () => void;
  onSwitchVersion?: (messageId: string, index: number) => void;
  onRegenerate?: (messageId: string) => void;
  onInspect?: (messageId: string) => void;
}

const badge = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-mono text-[9px] sm:text-[10px]';
const actionButton = 'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[9px] font-mono transition cursor-pointer';

/** Riga sotto il messaggio: versioni, orario, azioni e badge di modalità, modello, tool, fonti e metriche. */
export const MessageMeta: React.FC<MessageMetaProps> = ({
  message: msg,
  showPaused,
  isLoading,
  copied,
  onCopy,
  onSwitchVersion,
  onRegenerate,
  onInspect,
}) => {
  const isUser = msg.sender === 'user';
  const versionIndex = msg.versionIndex ?? 0;
  const versionCount = msg.versions?.length ?? 0;
  const modeName = msg.mode?.toLowerCase();
  const sourcesCount = msg.web_prefetch?.sources?.length ?? 0;
  const metrics = msg.metrics;

  return (
    <div className={`flex items-center gap-1.5 text-[10px] text-fg-muted px-1 flex-wrap ${isUser ? 'justify-end' : 'justify-start'}`}>
      {versionCount > 1 && (
        <div className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded-md bg-panel border border-border text-[9px] font-mono text-fg-muted shadow-sm select-none">
          <button
            type="button"
            onClick={() => onSwitchVersion?.(msg.id, versionIndex - 1)}
            disabled={versionIndex <= 0}
            className="p-0.5 hover:text-fg disabled:opacity-25 disabled:hover:text-fg-muted transition cursor-pointer"
            title="Versione precedente"
          >
            <ChevronLeft size={11} />
          </button>
          <span className="px-1 text-[9px] font-semibold text-fg">
            {versionIndex + 1} / {versionCount}
          </span>
          <button
            type="button"
            onClick={() => onSwitchVersion?.(msg.id, versionIndex + 1)}
            disabled={versionIndex >= versionCount - 1}
            className="p-0.5 hover:text-fg disabled:opacity-25 disabled:hover:text-fg-muted transition cursor-pointer"
            title="Versione successiva"
          >
            <ChevronRight size={11} />
          </button>
        </div>
      )}

      <span>{msg.timestamp}</span>

      {!isUser && msg.content && (
        <button
          type="button"
          onClick={onCopy}
          className={`${actionButton} bg-panel hover:bg-panel-header border border-border text-fg-muted hover:text-fg`}
          title="Copia risposta"
        >
          {copied ? (
            <>
              <Check size={10} className="text-emerald-400" />
              <span className="text-emerald-400">Copiato</span>
            </>
          ) : (
            <>
              <Copy size={10} />
              <span>Copia</span>
            </>
          )}
        </button>
      )}

      {!isUser && onRegenerate && !isLoading && (
        <button
          type="button"
          onClick={() => onRegenerate(msg.id)}
          className={`${actionButton} bg-panel hover:bg-panel-header border border-border hover:border-accent text-fg-muted hover:text-fg shadow-sm`}
          title="Rigenera risposta dal prompt precedente"
        >
          <RefreshCw size={9} />
          <span>Rigenera</span>
        </button>
      )}

      {!isUser && onInspect && (
        <button
          type="button"
          onClick={() => onInspect(msg.id)}
          className={`${actionButton} bg-accent/10 hover:bg-accent/20 border border-accent/30 text-accent shadow-sm`}
          title="Ispeziona parametri, trace e tool nel pannello diagnostica"
        >
          <Activity size={9} />
          <span>Diagnostica</span>
        </button>
      )}

      {modeName && (
        <span className="px-1.5 py-0.5 rounded bg-panel border border-border text-[9px] uppercase font-mono tracking-wider">
          {modeName}
        </span>
      )}
      {msg.model && (
        <span className={`${badge} bg-panel border border-border text-fg-muted`} title={`Modello LLM: ${msg.model}`}>
          <Cpu size={10} className="text-accent shrink-0" />
          <span>{msg.model}</span>
        </span>
      )}
      {msg.tool_used && (
        <span className={`${badge} bg-emerald-500/10 border border-emerald-500/20 text-emerald-400`}>
          <Wrench size={10} />
          {msg.tool_used}
        </span>
      )}
      {sourcesCount > 0 && (
        <span className={`${badge} bg-cyan-500/10 border border-cyan-500/20 text-cyan-400`}>
          <Globe size={10} />
          {sourcesCount} fonti web
        </span>
      )}
      {metrics && (
        <span
          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-[9px] sm:text-[10px] bg-panel border border-border text-fg-muted"
          title={`Generati: ${metrics.completion_tokens ?? 0} tok • Prompt: ${metrics.prompt_tokens ?? 0} tok • Totale contesto: ${metrics.total_tokens ?? 0} tok • Velocità LLM: ${metrics.tok_per_s ?? 0} tok/s • Tempo LLM: ${metrics.llm_duration_s ?? metrics.duration_s ?? 0}s • Durata turno: ${metrics.duration_s ?? 0}s`}
        >
          <Zap size={10} className="text-amber-400" />
          <span>{metrics.tok_per_s ?? 0} tok/s</span>
          <span className="text-border">•</span>
          <span>{metrics.completion_tokens ?? 0} tok gen</span>
          {metrics.duration_s !== undefined && (
            <>
              <span className="text-border">•</span>
              <span>{metrics.duration_s}s</span>
            </>
          )}
        </span>
      )}
      {showPaused && (
        <span className={`${badge} bg-amber-500/20 border border-amber-500/40 text-amber-300 animate-pulse`}>
          <Pause size={10} />
          In pausa...
        </span>
      )}
    </div>
  );
};
