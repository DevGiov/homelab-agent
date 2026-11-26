import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ConsolidationStatus } from '../../api/memory';
import { jsonResponse, mockBackend } from '../../test/backend';
import { ConsolidationBar } from './ConsolidationBar';

afterEach(cleanup);

const status = (provider: string | null, model: string | null): ConsolidationStatus => ({
  running: false,
  running_since: null,
  last_run: null,
  last_result: null,
  pending: { messages: 4, threads: 1 },
  settings: { enabled: true, time: '03:00', timezone: 'Europe/Rome', provider, model },
  next_run: null,
});

const catalog = {
  providers: [
    { name: 'llamacpp', display_name: 'llama-swap', kind: 'openai_compat', cloud: false, clearance: 'private', healthy: true, models: [{ id: 'Qwen3.6-35B', is_vision: false, input_modalities: ['text'] }] },
    { name: 'bedrock', display_name: 'AWS Bedrock', kind: 'bedrock', cloud: true, clearance: 'internal', healthy: true, models: [{ id: 'claude-sonnet', is_vision: false, input_modalities: ['text'] }] },
  ],
  default: { provider: 'llamacpp', model: 'Qwen3.6-35B' },
};

describe('ConsolidationBar: modello come coppia (provider, modello)', () => {
  it('parte dalla coppia programmata e la passa intera a «Consolida ora» e al salvataggio', async () => {
    mockBackend({ 'GET /v1/models': () => jsonResponse(catalog) });
    const onStart = vi.fn();
    const onSaveSettings = vi.fn();
    render(<ConsolidationBar status={status('bedrock', 'claude-sonnet')} onStart={onStart} onSaveSettings={onSaveSettings} />);
    const bar = screen.getByLabelText('Consolidamento della memoria');
    expect(bar.textContent).toContain('con il claude-sonnet (bedrock)');
    const now = within(bar).getByLabelText('Modello per consolidare ora') as HTMLSelectElement;
    await waitFor(() => expect(now.selectedOptions[0]?.textContent).toBe('claude-sonnet'));
    fireEvent.click(within(bar).getByRole('button', { name: /Consolida ora/ }));
    expect(onStart).toHaveBeenCalledWith({ provider: 'bedrock', model: 'claude-sonnet' });

    fireEvent.click(within(bar).getByTitle('Programmazione del consolidamento'));
    const scheduled = within(bar).getByLabelText('Modello del consolidamento programmato') as HTMLSelectElement;
    // Ogni selettore carica il suo catalogo: quello appena aperto lo riceve dopo
    await waitFor(() => expect(within(scheduled).queryAllByRole('group')).toHaveLength(2));
    const local = within(within(scheduled).getByRole('group', { name: 'llama-swap' })).getByRole('option', { name: 'Qwen3.6-35B' }) as HTMLOptionElement;
    fireEvent.change(scheduled, { target: { value: local.value } });
    fireEvent.click(within(bar).getByRole('button', { name: 'Salva' }));
    expect(onSaveSettings).toHaveBeenCalledWith(expect.objectContaining({ provider: 'llamacpp', model: 'Qwen3.6-35B' }));
  });

  it('un provider eliminato resta visibile nella scelta programmata, segnato', async () => {
    mockBackend({ 'GET /v1/models': () => jsonResponse(catalog) });
    render(<ConsolidationBar status={status('vecchio', 'm-1')} onStart={vi.fn()} onSaveSettings={vi.fn()} />);
    const now = screen.getByLabelText('Modello per consolidare ora') as HTMLSelectElement;
    await waitFor(() => expect(now.selectedOptions[0]?.textContent).toBe('m-1 (provider vecchio non disponibile)'));
  });
});
