import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { FormattedMessage } from '../../api/chat';
import { AssistantDetails } from './AssistantDetails';

const message = (extra: Partial<FormattedMessage> = {}): FormattedMessage => ({
  id: 'a1',
  sender: 'assistant',
  content: 'risposta',
  timestamp: '10:00',
  ...extra,
});

const renderDetails = (msg: FormattedMessage) =>
  render(<AssistantDetails message={msg} threadId="t1" isLoading={false} onExecutePlan={() => {}} />);

afterEach(cleanup);

describe('AssistantDetails — avvisi di ripiego', () => {
  it('mostra un avviso per ogni ripiego, col testo del motivo', () => {
    renderDetails(
      message({
        fallbacks: [
          { from: 'cloud', to: 'local', reason: 'budget' },
          { from: 'cloud', to: 'local', reason: 'label' },
        ],
      })
    );
    const list = screen.getByRole('list', { name: 'Avvisi sul modello usato' });
    const items = within(list).getAllByRole('listitem');
    expect(items.map((i) => i.textContent)).toEqual([
      'Tetto di spesa raggiunto: risposta da local invece di cloud.',
      'Dati non ammessi su cloud: questo passo è andato a local.',
    ]);
  });

  it('senza ripieghi non mostra nulla', () => {
    renderDetails(message({ fallbacks: null }));
    expect(screen.queryByRole('list')).toBeNull();
  });
});
