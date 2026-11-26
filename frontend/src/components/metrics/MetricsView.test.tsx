import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MetricsSummary, MetricsTimeseries, TurnRecord } from '../../api/metrics';
import { jsonResponse, mockBackend } from '../../test/backend';
import { MetricsView } from './MetricsView';

const summary: MetricsSummary = {
  window_hours: 24,
  turns: {
    total: 12,
    by_status: { ok: 9, error: 2, stopped: 1 },
    by_source: { chat: 10, automation: 2 },
    p50_ms: 4200,
    p95_ms: 61_000,
    max_ms: 90_000,
    tool_calls: 30,
    tool_errors: 1,
  },
  llm: { calls: 20, errors: 0, prompt_tokens: 40_000, cached_tokens: 30_000, completion_tokens: 3000, prompt_tok_s: 1834.4, gen_tok_s: 42.25, cache_hit_pct: 75, cost_usd: 1.2345, fallbacks: { budget: 2, label: 1 } },
  models: [
    { provider: 'llamacpp', model: 'LFM2.5-24B', calls: 17, errors: 0, p50_ms: 3000, completion_tokens: 2500, cost_usd: 0, prompt_tok_s: 1834.4, gen_tok_s: 42.25, cache_hit_pct: 75 },
    { provider: 'cloud', model: 'big-model', calls: 3, errors: 0, p50_ms: 5000, completion_tokens: 500, cost_usd: 1.2345, prompt_tok_s: null, gen_tok_s: null, cache_hit_pct: null },
  ],
  roles: [
    { role: 'select_tool', calls: 12, errors: 0, prompt_tokens: 30_000, cached_tokens: 25_000, completion_tokens: 900, p50_ms: 2000, cost_usd: 0.0042, fallbacks: { budget: 2 } },
    { role: 'consolidate', calls: 8, errors: 0, prompt_tokens: 10_000, cached_tokens: 5000, completion_tokens: 2100, p50_ms: 4000, cost_usd: 0, fallbacks: {} },
  ],
  tools: [{ tool: 'web_search', calls: 8, errors: 1, avg_ms: 1500, p95_ms: 3000 }],
  health: [
    { service: 'llamacpp', samples: 60, uptime_pct: 100, ok: true, last_error: null, last_checked: '2026-10-28T10:00:00+00:00', avg_latency_ms: 12 },
    { service: 'mcp:metamcp', samples: 60, uptime_pct: 90, ok: false, last_error: 'HTTP 502', last_checked: '2026-10-28T10:00:00+00:00', avg_latency_ms: 40 },
  ],
};

const point = (start: string, turns: number) => ({
  start,
  turns,
  errors: 0,
  stopped: 0,
  p50_ms: turns ? 4000 : null,
  tool_errors: 0,
  llm_calls: turns,
  prompt_tok_s: null,
  gen_tok_s: turns ? 40 : null,
  cache_hit_pct: null,
  cost_usd: turns ? 0.01 : 0,
});

const series: MetricsTimeseries = {
  window_hours: 24,
  bucket_minutes: 30,
  points: [point('2026-10-28T09:00:00+00:00', 3), point('2026-10-28T09:30:00+00:00', 0)],
  health: { llamacpp: [{ uptime_pct: 100, avg_latency_ms: 12 }, { uptime_pct: null, avg_latency_ms: null }] },
};

const turns: TurnRecord[] = [
  {
    id: 1,
    ts: '2026-10-28T09:10:00+00:00',
    turn_key: 't1',
    source: 'automation',
    mode: 'auto_github_trending_daily',
    model: 'LFM2.5-24B',
    status: 'error',
    duration_ms: 61_000,
    llm_ms: 50_000,
    llm_calls: 4,
    prompt_tokens: 9000,
    cached_tokens: 5000,
    completion_tokens: 800,
    tool_calls: 3,
    tool_errors: 1,
    error: 'step fallito',
  },
];

function setup() {
  return mockBackend({
    'GET /v1/metrics/summary': () => jsonResponse(summary),
    'GET /v1/metrics/timeseries': () => jsonResponse(series),
    'GET /v1/metrics/turns': () => jsonResponse(turns),
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('MetricsView', () => {
  it('mostra riepilogo, salute dei servizi e tabelle', async () => {
    setup();
    render(<MetricsView />);

    expect(await screen.findByText('4,2 s')).toBeTruthy();
    expect(screen.getByText('10 chat · 2 automazioni')).toBeTruthy();
    expect(screen.getAllByText('42,3 tok/s').length).toBeGreaterThan(0);
    expect(screen.getByText('MCP · metamcp')).toBeTruthy();
    expect(screen.getByText(/HTTP 502/)).toBeTruthy();
    expect(screen.getByText('web_search')).toBeTruthy();

    const turnsTable = screen.getByText('Ultimi turni').closest('section') as HTMLElement;
    expect(within(turnsTable).getByText('auto_github_trending_daily')).toBeTruthy();
    expect(within(turnsTable).getByText('errore').getAttribute('title')).toBe('step fallito');
  });

  it('mostra il costo, i ripieghi al modello locale e le tabelle per provider e per ruolo', async () => {
    setup();
    render(<MetricsView />);
    await screen.findByText('4,2 s');

    const detail = screen.getByText('3 chiamate al modello locale: 2 per tetto di spesa, 1 per dati non ammessi');
    expect(detail.previousElementSibling?.textContent).toBe('$1,23');

    const models = screen.getByRole('region', { name: 'Modelli' });
    const cloudRow = within(models).getByText('big-model').closest('tr') as HTMLElement;
    expect(within(cloudRow).getByText('cloud')).toBeTruthy();
    expect(within(cloudRow).getByText('$1,23')).toBeTruthy();
    expect(within(models).getByText('LFM2.5-24B').closest('tr')?.textContent).toContain('$0');

    const roles = screen.getByRole('region', { name: 'Ruoli' });
    const toolRow = within(roles).getByText('select_tool').closest('tr') as HTMLElement;
    expect(within(toolRow).getByText('$0,0042')).toBeTruthy();
    expect(within(toolRow).getByText('2 per tetto di spesa')).toBeTruthy();
    expect(within(roles).getByText('consolidate')).toBeTruthy();
  });

  it('ricarica le metriche sulla finestra scelta', async () => {
    const { requests } = setup();
    render(<MetricsView />);
    await screen.findByText('4,2 s');

    fireEvent.click(screen.getByRole('button', { name: '7 giorni' }));
    await waitFor(() => expect(requests.some((r) => r.path === '/v1/metrics/timeseries' && r.search.includes('hours=168'))).toBe(true));
    const last = requests.filter((r) => r.path === '/v1/metrics/timeseries').at(-1);
    expect(new URLSearchParams(last?.search).get('buckets')).toBe('56');
    expect(screen.getByRole('button', { name: '7 giorni' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('segnala le metriche non disponibili', async () => {
    mockBackend({});
    render(<MetricsView />);
    expect(await screen.findByText(/Metriche non caricate/)).toBeTruthy();
  });
});
