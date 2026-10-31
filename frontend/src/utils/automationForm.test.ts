import { describe, expect, it } from 'vitest';
import { buildAutomation, changeStepType, formFromAutomation, LOADED_MODEL, stepsFromAutomation } from './automationForm';

const automation = {
  id: 'tpl-github-issue-repair',
  name: 'Repair',
  version: 3,
  enabled: true,
  triggers: [
    { id: 'trg-webhook-issue', type: 'webhook', webhook_token: 'tok', enabled: true },
    { id: 'trg-manual-repair', type: 'manual', enabled: false },
  ],
  workflow: {
    initial_step_id: 'fetch',
    steps: [
      { step_id: 'fetch', name: 'Fetch', type: 'deterministic_action', action_or_tool: 'http_get', parameters: { url: 'x' } },
      { step_id: 'think', name: 'Think', type: 'agentic_task', action_or_tool: 'llm_call', prompt_template: 'p' },
    ],
  },
  budget: { max_tokens: 1000 },
  parameters: { repo: 'a/b' },
};

describe('automationForm', () => {
  it('il salvataggio non tocca i trigger (webhook e manuali compresi)', () => {
    const saved = buildAutomation(automation, formFromAutomation(automation), stepsFromAutomation(automation));
    expect(saved.triggers).toEqual(automation.triggers);
  });

  it('applica i campi del form, incrementa la versione e conserva il resto della definizione', () => {
    const form = { ...formFromAutomation(automation), name: 'Nuovo nome', retentionDays: '' as const };
    const saved = buildAutomation(automation, form, stepsFromAutomation(automation));
    expect(saved).toMatchObject({ id: automation.id, name: 'Nuovo nome', version: 4, retention_days: null, parameters: { repo: 'a/b' } });
    expect(saved.budget).toEqual({ max_duration_seconds: 300, max_tokens: 1000, max_llm_calls: 10, max_tool_calls: 25, max_retries_per_step: 2 });
  });

  it('il modello: vuoto è il default (null), poi il modello caricato o uno preciso', () => {
    const steps = stepsFromAutomation(automation);
    expect(formFromAutomation(automation).model).toBe('');
    expect(buildAutomation(automation, formFromAutomation(automation), steps).model).toBeNull();
    const loaded = { ...formFromAutomation(automation), model: LOADED_MODEL };
    expect(buildAutomation(automation, loaded, steps).model).toBe('loaded');
    expect(formFromAutomation({ ...automation, model: 'Qwen3.6-35B' }).model).toBe('Qwen3.6-35B');
  });

  it('i task agentici salvano il prompt, le azioni il tool', () => {
    const saved = buildAutomation(automation, formFromAutomation(automation), stepsFromAutomation(automation));
    expect(saved.workflow.steps.map((s: any) => [s.step_id, s.action_or_tool, s.prompt_template])).toEqual([
      ['fetch', 'http_get', null],
      ['think', null, 'p'],
    ]);
    expect(saved.workflow.initial_step_id).toBe('fetch');
  });

  it('il cambio di tipo imposta prompt o tool di default', () => {
    const [fetch, think] = stepsFromAutomation(automation);
    expect(changeStepType(fetch, 'agentic_task')).toMatchObject({ action_or_tool: null, prompt_template: expect.any(String) });
    expect(changeStepType(think, 'deterministic_action')).toMatchObject({ action_or_tool: 'llm_call', prompt_template: null });
  });
});
