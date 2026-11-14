import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { FeedbackToast } from './FeedbackToast';

describe('FeedbackToast', () => {
  afterEach(cleanup);

  it("un errore si annuncia subito (alert), una conferma con calma (status)", () => {
    const { rerender } = render(<FeedbackToast feedback={{ type: 'error', text: 'Salvataggio non riuscito' }} />);
    expect(screen.getByRole('alert').textContent).toBe('Salvataggio non riuscito');
    rerender(<FeedbackToast feedback={{ type: 'success', text: 'Salvato' }} />);
    expect(screen.getByRole('status').textContent).toBe('Salvato');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
