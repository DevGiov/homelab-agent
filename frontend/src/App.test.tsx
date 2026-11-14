import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { jsonResponse, mockBackend } from './test/backend';

describe('App: landmark della pagina', () => {
  beforeEach(() => {
    // jsdom non implementa lo scorrimento della lista dei messaggi
    Element.prototype.scrollIntoView = vi.fn();
    mockBackend({
      'GET /v1/threads': () => jsonResponse([]),
      'GET /v1/health': () => jsonResponse({ status: 'ok' }),
    });
  });
  afterEach(cleanup);

  it('ha un solo main, la navigazione delle viste e le due barre laterali con un nome', async () => {
    const { container } = render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });

    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(container.querySelectorAll('main')).toHaveLength(1);
    expect(screen.getByRole('complementary', { name: 'Barra laterale' })).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'Diagnostica' })).toBeTruthy();
    // La chat sta nel main, le barre laterali fuori
    const main = screen.getByRole('main');
    expect(main.querySelector('textarea')).toBeTruthy();
    expect(main.querySelector('aside')).toBeNull();
    expect(screen.getByRole('region', { name: 'Messaggi' })).toBeTruthy();
  });

  it('dà un titolo alla vista corrente sotto quello dell’app', async () => {
    render(<App />);
    await screen.findByRole('navigation', { name: 'Viste' });
    expect(screen.getByRole('heading', { level: 1, name: 'Main-Agent UI' })).toBeTruthy();
    expect(screen.getAllByRole('heading', { level: 2 }).length).toBeGreaterThan(0);
  });
});
