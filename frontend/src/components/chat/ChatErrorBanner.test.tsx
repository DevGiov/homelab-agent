import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatErrorBanner } from './ChatErrorBanner';

describe('ChatErrorBanner', () => {
  afterEach(cleanup);
  const long = `Errore dell'API: https://servizio.invalid/${'percorso-senza-spazi/'.repeat(20)}`;

  it('il testo va a capo anche nelle stringhe senza spazi e non si tronca', () => {
    render(<ChatErrorBanner message={long} onClose={() => {}} />);
    const text = screen.getByTestId('chat-error-text');
    expect(text.textContent).toBe(long);
    const classes = text.className.split(/\s+/);
    expect(classes).toContain('[overflow-wrap:anywhere]');
    // In un contenitore flex serve min-w-0, altrimenti la parola lunga allarga la riga oltre lo schermo
    expect(classes).toContain('min-w-0');
    expect(text.parentElement!.className.split(/\s+/)).toContain('min-w-0');
    expect(classes).not.toContain('truncate');
  });

  it("il messaggio è un avviso per i lettori di schermo, senza il pulsante Chiudi", () => {
    render(<ChatErrorBanner message={long} onClose={() => {}} />);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toBe(long);
    expect(alert.querySelector('button')).toBeNull();
  });

  it('il pulsante Chiudi non si restringe e chiude', () => {
    const onClose = vi.fn();
    render(<ChatErrorBanner message={long} onClose={onClose} />);
    const close = screen.getByRole('button', { name: 'Chiudi' });
    expect(close.className.split(/\s+/)).toContain('shrink-0');
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
