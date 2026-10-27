import React from 'react';
import { Globe } from 'lucide-react';
import type { FormattedMessage } from '../../api/chat';
import { ExecutionTraceViewer } from '../ExecutionTraceViewer';
import { InlineApprovalCard } from '../InlineApprovalCard';
import { PlanViewer } from '../PlanViewer';

interface AssistantDetailsProps {
  message: FormattedMessage;
  threadId: string | null;
  isLoading: boolean;
  onExecutePlan: (summary: string) => void;
  onApprovalResolved?: (action: string, res?: any) => void;
}

/** Richiesta di approvazione del messaggio: dai campi del messaggio o dal passo della trace che la richiede. */
function pendingApproval(msg: FormattedMessage) {
  const step = msg.execution_trace?.find((t) => t.approval_required);
  if (!msg.approval_required && !step) return null;
  const requestId = msg.request_id || step?.request_id;
  if (!requestId) return null;
  return {
    requestId,
    toolName: msg.tool_used || step?.tool_name || 'tool',
    argumentsData: step?.args,
    commandPreview: msg.command_preview || step?.command_preview,
    commandPrefix: msg.command_prefix || step?.command_prefix,
    riskReason: msg.risk_reason || step?.risk_reason || msg.approval_prompt,
  };
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/** Viste inline sotto la risposta: piano, approvazione, trace di esecuzione e fonti web. */
export const AssistantDetails: React.FC<AssistantDetailsProps> = ({
  message: msg,
  threadId,
  isLoading,
  onExecutePlan,
  onApprovalResolved,
}) => {
  const approval = pendingApproval(msg);
  const sources = msg.web_prefetch?.sources ?? [];
  const hasTrace = Boolean(msg.reasoning || msg.execution_trace?.length || msg.rollback_trace?.length);

  return (
    <>
      {(msg.mode?.toLowerCase() === 'plan' || Boolean(msg.plan_steps?.length)) && (
        <PlanViewer
          planSteps={msg.plan_steps}
          planStructure={msg.plan_structure}
          onExecutePlan={onExecutePlan}
          isLoading={isLoading}
        />
      )}

      {approval && (
        <InlineApprovalCard
          {...approval}
          threadId={threadId}
          isResolvedInitially={msg.approval_resolved}
          resolvedActionInitially={msg.approval_action}
          onResolved={(action, res) => {
            msg.approval_resolved = true;
            msg.approval_action = action;
            onApprovalResolved?.(action, res);
          }}
        />
      )}

      {hasTrace && (
        <ExecutionTraceViewer
          reasoning={msg.reasoning}
          trace={msg.execution_trace}
          rollbackTrace={msg.rollback_trace}
          initialCollapsed={true}
        />
      )}

      {sources.length > 0 && (
        <div className="mt-3 pt-2.5 border-t border-border/60">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-accent mb-1.5">
            <Globe size={12} className="text-accent" />
            <span>Fonti web consultate:</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sources.slice(0, 5).map((src, idx) => (
              <a
                key={idx}
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-panel/80 hover:bg-panel border border-border/80 hover:border-accent text-fg-muted hover:text-fg text-[10px] transition group"
                title={`${src.title}\n${src.url}`}
              >
                <span className="truncate max-w-[140px]">{domainOf(src.url)}</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </>
  );
};
