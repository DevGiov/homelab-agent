import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ModelCatalog } from '../../hooks/useModelCatalog';
import { USER_BUBBLE_BUTTON } from '../../theme/userBubble';
import { PromptEditor } from './PromptEditor';

const models = { modelDetails: [], activeProvider: null, refreshModels: vi.fn() } as unknown as ModelCatalog;
const message = { id: 'm1', sender: 'user' as const, content: 'Controlla il backup', timestamp: '2026-11-14T10:00:00Z' };

describe('PromptEditor', () => {
  afterEach(cleanup);

  it("Invia ha i colori invertiti del fumetto, non l'accento che vi si confonde, e invia il testo modificato", () => {
    const onSubmit = vi.fn();
    render(<PromptEditor message={message} defaults={{ mode: 'auto', model: 'default' }} models={models} onSubmit={onSubmit} onCancel={vi.fn()} />);
    const send = screen.getByRole('button', { name: 'Invia' });
    const classes = send.className.split(/\s+/);
    expect(classes).toEqual(expect.arrayContaining(USER_BUBBLE_BUTTON.split(' ')));
    expect(classes.filter((c) => /(^|:)(bg|text)-accent/.test(c))).toEqual([]);

    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt' }), { target: { value: '  Controlla il backup di oggi ' } });
    fireEvent.click(send);
    expect(onSubmit).toHaveBeenCalledWith({ content: 'Controlla il backup di oggi', mode: undefined, model: undefined, reasoningBudget: undefined });
  });
});
