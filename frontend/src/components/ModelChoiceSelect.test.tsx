import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CatalogProvider } from '../api/providers';
import { jsonResponse, mockBackend } from '../test/backend';
import { LOADED_MODEL, type ModelChoice } from '../utils/modelChoice';
import { ModelChoiceSelect } from './ModelChoiceSelect';

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
  healthy: true,
  models: [{ id: 'claude-sonnet', is_vision: true, input_modalities: ['text'] }],
};

afterEach(cleanup);

async function setup(value: ModelChoice, providers: CatalogProvider[] = [LOCAL, CLOUD], defaultProvider = 'llamacpp') {
  mockBackend({ 'GET /v1/models': () => jsonResponse({ providers, default: { provider: defaultProvider, model: 'Qwen3.6-35B' } }) });
  const onChange = vi.fn();
  render(<ModelChoiceSelect value={value} onChange={onChange} aria-label="Modello" />);
  const select = screen.getByLabelText('Modello') as HTMLSelectElement;
  // Il catalogo arriva dopo il primo render
  await waitFor(() => expect(within(select).queryAllByRole('group').length).toBeGreaterThan(0));
  return { select, onChange };
}

const selectedLabel = (select: HTMLSelectElement) => select.selectedOptions[0]?.textContent;

describe('ModelChoiceSelect', () => {
  it('raggruppa i modelli per provider attivo, dopo le due scelte speciali', async () => {
    const { select } = await setup({ provider: null, model: '' });
    expect(within(select).getAllByRole('group').map((g) => g.getAttribute('label'))).toEqual(['llama-swap', 'AWS Bedrock']);
    expect(within(within(select).getByRole('group', { name: 'AWS Bedrock' })).getAllByRole('option').map((o) => o.textContent)).toEqual(['claude-sonnet']);
    const specials = Array.from(select.children).filter((c) => c.tagName === 'OPTION').map((o) => o.textContent);
    expect(specials).toEqual(['Default del server', 'Modello caricato al momento (ora: Qwen3.6-35B)']);
    expect(selectedLabel(select)).toBe('Default del server');
  });

  it('salva la coppia (provider, modello), non una stringa con un separatore', async () => {
    const { select, onChange } = await setup({ provider: null, model: '' });
    const cloudOption = within(within(select).getByRole('group', { name: 'AWS Bedrock' })).getByRole('option', { name: 'claude-sonnet' });
    fireEvent.change(select, { target: { value: (cloudOption as HTMLOptionElement).value } });
    expect(onChange).toHaveBeenLastCalledWith({ provider: 'bedrock', model: 'claude-sonnet' });
    fireEvent.change(select, { target: { value: LOADED_MODEL } });
    expect(onChange).toHaveBeenLastCalledWith({ provider: null, model: LOADED_MODEL });
    fireEvent.change(select, { target: { value: '' } });
    expect(onChange).toHaveBeenLastCalledWith({ provider: null, model: '' });
  });

  it('un modello salvato senza provider è un modello del provider predefinito', async () => {
    const { select } = await setup({ provider: null, model: 'Gemma-4-26B' });
    expect(selectedLabel(select)).toBe('Gemma-4-26B');
    expect(select.selectedOptions[0].parentElement?.getAttribute('label')).toBe('llama-swap');
  });

  it('una scelta il cui provider non c\'è più resta selezionata e segnata', async () => {
    const { select } = await setup({ provider: 'vecchio-cloud', model: 'gpt-x' });
    expect(selectedLabel(select)).toBe('gpt-x (provider vecchio-cloud non disponibile)');
  });

  it('un modello che il provider non elenca più resta nel suo gruppo, segnato', async () => {
    const { select } = await setup({ provider: 'bedrock', model: 'claude-ritirato' });
    expect(selectedLabel(select)).toBe('claude-ritirato (modello non elencato)');
    expect(select.selectedOptions[0].parentElement?.getAttribute('label')).toBe('AWS Bedrock');
  });

  it('il modello caricato non si offre se il provider predefinito è cloud, ma una scelta già salvata resta', async () => {
    const cloudDefault = await setup({ provider: null, model: '' }, [CLOUD, LOCAL], 'bedrock');
    expect(within(cloudDefault.select).queryByRole('option', { name: /Modello caricato/ })).toBeNull();
    cleanup();
    const kept = await setup({ provider: null, model: LOADED_MODEL }, [CLOUD, LOCAL], 'bedrock');
    expect(selectedLabel(kept.select)).toMatch(/^Modello caricato al momento/);
  });
});
