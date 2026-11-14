import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ChatOptions } from '../../hooks/useChatOptions';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { ChatOptionsBar } from './ChatOptionsBar';

vi.mock('../ModelSelector', () => ({ ModelSelector: () => <div data-testid="model-selector" /> }));

afterEach(cleanup);

function fakeOptions(overrides: Partial<ChatOptions> = {}): ChatOptions {
  return {
    securityMode: 'normal',
    setSecurityMode: vi.fn(),
    webSearch: 'auto',
    setWebSearch: vi.fn(),
    incognito: false,
    setIncognito: vi.fn(),
    reasoningBudget: undefined,
    setReasoningBudget: vi.fn(),
    model: 'default',
    setModel: vi.fn(),
    ...overrides,
  } as unknown as ChatOptions;
}

const models = { modelDetails: [], activeProvider: 'llamacpp', refreshModels: vi.fn() } as unknown as ModelCatalog;

describe('opzioni dell\'invio', () => {
  it('con i default fuori restano solo il pulsante e il modello', () => {
    render(<ChatOptionsBar options={fakeOptions()} models={models} level="public" onLevelChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Opzioni' }).getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByTestId('model-selector')).toBeTruthy();
    expect(screen.queryAllByTestId(/^option-change-/)).toHaveLength(0);
  });

  it('le scelte diverse dal default restano visibili come chip, e una chip apre il pannello', () => {
    const options = fakeOptions({ securityMode: 'dangerous', incognito: true, webSearch: 'on', reasoningBudget: 8192 });
    render(<ChatOptionsBar options={options} models={models} level="internal" onLevelChange={vi.fn()} />);
    const chips = screen.getAllByTestId(/^option-change-/).map((c) => c.textContent);
    expect(chips).toEqual(['Dangerous', 'Dati interni', 'Incognito', 'Web: sempre', 'Ragionamento: 8192 token']);
    fireEvent.click(screen.getByTestId('option-change-security'));
    expect(screen.getByRole('dialog', { name: "Opzioni dell'invio" })).toBeTruthy();
  });

  it('il pannello cambia le opzioni e mostra la spiegazione della scelta attiva', () => {
    const options = fakeOptions();
    const onLevelChange = vi.fn();
    render(<ChatOptionsBar options={options} models={models} level="public" onLevelChange={onLevelChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('I tool di sola lettura partono da soli');
    expect(screen.getByRole('button', { name: 'Normal' }).getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'Dangerous' }));
    expect(options.setSecurityMode).toHaveBeenCalledWith('dangerous');
    fireEvent.click(screen.getByRole('button', { name: 'Interni' }));
    expect(onLevelChange).toHaveBeenCalledWith('internal');
    fireEvent.click(screen.getByRole('button', { name: 'Mai' }));
    expect(options.setWebSearch).toHaveBeenCalledWith('off');
    fireEvent.click(screen.getByRole('checkbox', { name: /Incognito/ }));
    expect(options.setIncognito).toHaveBeenCalledWith(true);
    fireEvent.change(screen.getByRole('combobox', { name: 'Ragionamento' }), { target: { value: '2048' } });
    expect(options.setReasoningBudget).toHaveBeenCalledWith(2048);
    fireEvent.change(screen.getByRole('combobox', { name: 'Ragionamento' }), { target: { value: 'default' } });
    expect(options.setReasoningBudget).toHaveBeenLastCalledWith(undefined);
  });

  it('Esc chiude il pannello e riporta il focus sul pulsante; un clic fuori lo chiude', () => {
    render(<ChatOptionsBar options={fakeOptions()} models={models} level="public" onLevelChange={vi.fn()} />);
    const button = screen.getByRole('button', { name: 'Opzioni' });
    fireEvent.click(button);
    expect(document.activeElement?.textContent).toBe('Safest');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(button);

    fireEvent.click(button);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('senza livello della conversazione il pannello non lo offre', () => {
    render(<ChatOptionsBar options={fakeOptions()} models={models} />);
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni' }));
    expect(screen.queryByRole('group', { name: 'Dati della conversazione' })).toBeNull();
    expect(screen.getByRole('group', { name: 'Sicurezza' })).toBeTruthy();
  });
});
