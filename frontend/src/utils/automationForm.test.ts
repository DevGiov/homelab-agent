import { describe, expect, it } from 'vitest';
import { buildAutomation, changeStepType, formFromAutomation, parseHostList, stepsFromAutomation } from './automationForm';
import { LOADED_MODEL } from './modelChoice';

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

  it('i tool di uno step agentico: null = tutti, [] = nessuno, le azioni non ne hanno', () => {
    const steps = stepsFromAutomation(automation).map((s) => (s.step_id === 'think' ? { ...s, tools: [] } : s));
    const saved = buildAutomation(automation, formFromAutomation(automation), steps);
    expect(saved.workflow.steps.map((s: any) => s.tools)).toEqual([null, []]);
    expect(stepsFromAutomation(automation)[1].tools).toBeNull();
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

  it('parseHostList divide su spazi, a capo e virgole, toglie vuoti, converte in minuscolo e toglie i doppioni mantenendo l\'ordine', () => {
    const raw = 'API.EXAMPLE.COM, test.com\n*.OTHER.ORG, api.example.com  TEST.COM\n, \t ';
    expect(parseHostList(raw)).toEqual(['api.example.com', 'test.com', '*.other.org']);
    expect(parseHostList('')).toEqual([]);
    expect(parseHostList('   , \n\t ')).toEqual([]);
  });

  it('legge allowed_hosts da permission_policy e gestisce automazioni senza permission_policy', () => {
    const withPolicy = {
      ...automation,
      permission_policy: {
        allowed_hosts: ['api.example.com', 'test.com'],
        custom_rule: 'keep',
      },
    };
    expect(formFromAutomation(withPolicy).allowedHosts).toBe('api.example.com\ntest.com');

    const withoutPolicy = { ...automation };
    delete (withoutPolicy as any).permission_policy;
    expect(formFromAutomation(withoutPolicy).allowedHosts).toBe('');
  });

  it('buildAutomation scrive permission_policy.allowed_hosts e conserva gli altri campi della policy', () => {
    const withPolicy = {
      ...automation,
      permission_policy: {
        allowed_hosts: ['old.com'],
        allowed_tools: ['http_get'],
        extra_flag: true,
      },
    };
    const form = {
      ...formFromAutomation(withPolicy),
      allowedHosts: 'API.GITHUB.COM, *.example.com\napi.github.com',
    };
    const saved = buildAutomation(withPolicy, form, stepsFromAutomation(withPolicy));
    expect(saved.permission_policy).toEqual({
      allowed_hosts: ['api.github.com', '*.example.com'],
      allowed_tools: ['http_get'],
      extra_flag: true,
    });
  });

  it('buildAutomation crea permission_policy se assente nell\'automazione di partenza', () => {
    const withoutPolicy = { ...automation };
    delete (withoutPolicy as any).permission_policy;
    const form = {
      ...formFromAutomation(withoutPolicy),
      allowedHosts: 'api.example.com\n*.test.com',
    };
    const saved = buildAutomation(withoutPolicy, form, stepsFromAutomation(withoutPolicy));
    expect(saved.permission_policy).toEqual({
      allowed_hosts: ['api.example.com', '*.test.com'],
    });
  });
});
