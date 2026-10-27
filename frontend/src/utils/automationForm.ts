// Conversione tra la definizione di un'automazione e lo stato del form di modifica.

export type StepType = 'deterministic_action' | 'agentic_task' | 'approval_gate' | string;

export interface StepDef {
  step_id: string;
  name: string;
  type: StepType;
  action_or_tool?: string | null;
  prompt_template?: string | null;
  parameters?: Record<string, any>;
  requires_approval?: boolean;
  timeout_seconds?: number;
}

export interface Budget {
  max_duration_seconds: number;
  max_tokens: number;
  max_llm_calls: number;
  max_tool_calls: number;
  max_retries_per_step: number;
}

export interface AutomationFormState {
  name: string;
  description: string;
  enabled: boolean;
  retentionDays: number | '';
  budget: Budget;
}

const DEFAULT_BUDGET: Budget = {
  max_duration_seconds: 300,
  max_tokens: 50000,
  max_llm_calls: 10,
  max_tool_calls: 25,
  max_retries_per_step: 2,
};

export const DEFAULT_AGENTIC_PROMPT = 'Analizza i risultati: {{steps.step_1.output.text}}';

export function formFromAutomation(automation: any): AutomationFormState {
  const budget = automation.budget ?? {};
  return {
    name: automation.name || '',
    description: automation.description || '',
    enabled: automation.enabled ?? true,
    retentionDays: automation.retention_days ?? 14,
    budget: Object.fromEntries(
      Object.entries(DEFAULT_BUDGET).map(([key, fallback]) => [key, budget[key] || fallback])
    ) as unknown as Budget,
  };
}

export function stepsFromAutomation(automation: any): StepDef[] {
  return (automation.workflow?.steps || []).map((s: any) => ({
    step_id: s.step_id || `step_${Math.random().toString(36).substring(2, 7)}`,
    name: s.name || 'Step',
    type: s.type || 'deterministic_action',
    action_or_tool: s.action_or_tool || null,
    prompt_template: s.prompt_template || null,
    parameters: s.parameters || {},
    requires_approval: Boolean(s.requires_approval),
    timeout_seconds: s.timeout_seconds || 60,
  }));
}

export function newStep(position: number): StepDef {
  return {
    step_id: `step_${position}_action`,
    name: `Nuovo Step ${position}`,
    type: 'deterministic_action',
    action_or_tool: 'web_search',
    parameters: { query: '' },
    prompt_template: null,
    requires_approval: false,
    timeout_seconds: 60,
  };
}

/** Cambio di tipo: un task agentico usa un prompt, un'azione deterministica un tool. */
export function changeStepType(step: StepDef, type: StepType): StepDef {
  if (type === 'agentic_task' && step.type !== 'agentic_task') {
    return { ...step, type, action_or_tool: null, prompt_template: step.prompt_template || DEFAULT_AGENTIC_PROMPT };
  }
  if (type === 'deterministic_action' && step.type !== 'deterministic_action') {
    return { ...step, type, action_or_tool: step.action_or_tool || 'web_search', prompt_template: null };
  }
  return { ...step, type };
}

/**
 * Definizione aggiornata da salvare. I trigger restano quelli esistenti: si modificano dal
 * modale dedicato (cron e webhook), mentre qui verrebbero ridotti a un solo cron.
 */
export function buildAutomation(automation: any, form: AutomationFormState, steps: StepDef[]) {
  return {
    ...automation,
    name: form.name,
    description: form.description,
    enabled: form.enabled,
    retention_days: form.retentionDays === '' ? null : Number(form.retentionDays),
    version: (automation.version || 1) + 1,
    workflow: {
      ...automation.workflow,
      initial_step_id: steps[0]?.step_id || 'step_1',
      steps: steps.map((s) => ({
        step_id: s.step_id,
        name: s.name,
        type: s.type,
        action_or_tool: s.type === 'agentic_task' ? null : s.action_or_tool,
        prompt_template: s.type === 'agentic_task' ? s.prompt_template : null,
        parameters: s.parameters || {},
        requires_approval: s.requires_approval,
        timeout_seconds: s.timeout_seconds,
      })),
    },
    budget: Object.fromEntries(Object.entries(form.budget).map(([key, value]) => [key, Number(value)])),
  };
}
