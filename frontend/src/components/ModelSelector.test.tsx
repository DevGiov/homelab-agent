import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CatalogProvider } from '../api/providers';
import { jsonResponse, mockBackend } from '../test/backend';
import { ModelSelector } from './ModelSelector';

const LOCAL: CatalogProvider = {
  name: 'llamacpp',
  display_name: 'llama-swap',
  kind: 'openai_compat',
  cloud: false,
  clearance: 'private',
  healthy: true,
  models: [
    { id: 'Qwen3.6-35B', is_vision: true, input_modalities: ['text', 'image'], is_loaded: true },
    { id: 'Gemma-4-26B', is_vision: false, input_modalities: ['text'], is_loaded: false },
  ],
};

const CLOUD: CatalogProvider = {
  name: 'bedrock',
  display_name: 'AWS Bedrock',
  kind: 'bedrock',
  cloud: true,
  clearance: 'internal',
  healthy: false,
  models: [{ id: 'claude-sonnet', is_vision: true, input_modalities: ['text'] }],
};

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(cleanup);

function open(props: Partial<React.ComponentProps<typeof ModelSelector>> = {}) {
  const onSelect = vi.fn();
  const utils = render(<ModelSelector selected={{ provider: 'llamacpp', model: 'Qwen3.6-35B' }} onSelect={onSelect} providers={[LOCAL, CLOUD]} {...props} />);
  fireEvent.click(screen.getByRole('button', { name: /Qwen3.6-35B/ }));
  return { onSelect, ...utils };
}

describe('ModelSelector: gruppi per provider', () => {
  it('raggruppa i modelli sotto il nome visibile del provider, con locale o cloud e il livello', () => {
    open();
    const local = screen.getByRole('group', { name: 'llama-swap' });
    expect(within(local).getByText('locale')).toBeTruthy();
    expect(within(local).getByText('riceve dati privati')).toBeTruthy();
    expect(within(local).getByText('Gemma-4-26B')).toBeTruthy();
    expect(within(local).queryByText('claude-sonnet')).toBeNull();

    const cloud = screen.getByRole('group', { name: 'AWS Bedrock' });
    expect(within(cloud).getByText('cloud')).toBeTruthy();
    expect(within(cloud).getByText('riceve dati interni')).toBeTruthy();
    expect(within(cloud).getByText('claude-sonnet')).toBeTruthy();
  });

  it('un provider non raggiungibile resta nell\'elenco, segnato', () => {
    open();
    expect(within(screen.getByRole('group', { name: 'AWS Bedrock' })).getByText('non raggiungibile')).toBeTruthy();
    expect(within(screen.getByRole('group', { name: 'llama-swap' })).queryByText('non raggiungibile')).toBeNull();
  });

  it('tiene i dettagli di oggi: visione e modello caricato', () => {
    open();
    const local = screen.getByRole('group', { name: 'llama-swap' });
    expect(within(local).getByText('Visione')).toBeTruthy();
    expect(within(local).getByText('In VRAM')).toBeTruthy();
  });

  it('un modello cloud non è mai "In VRAM", anche se il server lo desse caricato', () => {
    open({ providers: [LOCAL, { ...CLOUD, models: [{ ...CLOUD.models[0], is_loaded: true }] }] });
    expect(within(screen.getByRole('group', { name: 'AWS Bedrock' })).queryByText('In VRAM')).toBeNull();
    expect(within(screen.getByRole('group', { name: 'llama-swap' })).getByText('In VRAM')).toBeTruthy();
  });

  it('scegliere un modello dà la coppia (provider, modello)', () => {
    const { onSelect } = open();
    fireEvent.click(within(screen.getByRole('group', { name: 'AWS Bedrock' })).getByText('claude-sonnet'));
    expect(onSelect).toHaveBeenCalledWith({ provider: 'bedrock', model: 'claude-sonnet' });
  });

  it('la ricerca filtra tra i provider e toglie i gruppi vuoti', () => {
    open();
    fireEvent.change(screen.getByPlaceholderText('Cerca modello...'), { target: { value: 'claude' } });
    expect(screen.queryByRole('group', { name: 'llama-swap' })).toBeNull();
    expect(screen.getByRole('group', { name: 'AWS Bedrock' })).toBeTruthy();
  });
});

describe('ModelSelector: caricamento su llama.cpp', () => {
  it('un modello locale non caricato si carica sul suo provider', async () => {
    const { requests } = mockBackend({ 'POST /v1/providers/llamacpp/models/load': () => jsonResponse({ status: 'ok' }) });
    const onRefresh = vi.fn();
    const { onSelect } = open({ onRefreshModels: onRefresh });
    fireEvent.click(screen.getByText('Gemma-4-26B'));
    expect(onSelect).toHaveBeenCalledWith({ provider: 'llamacpp', model: 'Gemma-4-26B' });
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    expect(requests.find((r) => r.path === '/v1/providers/llamacpp/models/load')?.body).toEqual({ model: 'Gemma-4-26B' });
  });

  it('un modello cloud non chiede nessun caricamento', async () => {
    const { requests } = mockBackend({});
    const { onSelect } = open();
    fireEvent.click(screen.getByText('claude-sonnet'));
    expect(onSelect).toHaveBeenCalled();
    await Promise.resolve();
    expect(requests.filter((r) => r.path.endsWith('/models/load'))).toHaveLength(0);
  });
});

describe('ModelSelector: provider che non c\'è più', () => {
  it('la scelta resta visibile e segnata non disponibile, senza cambiare da sola', () => {
    const onSelect = vi.fn();
    render(<ModelSelector selected={{ provider: 'vecchio', model: 'm1' }} onSelect={onSelect} providers={[LOCAL]} />);
    const trigger = screen.getByRole('button', { name: /m1/ });
    expect(trigger.textContent).toContain('vecchio · m1');
    expect(trigger.textContent).toContain('non disponibile');
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.click(trigger);
    expect(screen.getByRole('alert').textContent).toContain('vecchio · m1');
    expect(screen.getByRole('alert').textContent).toContain('non è disponibile');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('senza una scelta mostra il modello predefinito', () => {
    render(<ModelSelector selected={null} onSelect={vi.fn()} providers={[LOCAL]} />);
    expect(screen.getByRole('button').textContent).toContain('Modello: predefinito');
  });
});
