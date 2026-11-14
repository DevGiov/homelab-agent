import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ThreadItem } from './api/threads';
import { ThreadList } from './ThreadList';

const threads: ThreadItem[] = [
  { thread_id: 'thread_a', title: 'Backup del NAS', last_message: 'Fatto', checkpoint_count: 4 },
  { thread_id: 'thread_b', title: 'Aggiornamento Debian', last_message: null, checkpoint_count: 0, is_active: true },
];

function renderList(overrides: Partial<React.ComponentProps<typeof ThreadList>> = {}) {
  const props = {
    threads,
    currentThreadId: 'thread_a',
    onSelectThread: vi.fn(),
    onNewThread: vi.fn(),
    onDeleteThread: vi.fn(),
    onDeleteAllThreads: vi.fn(),
    onRefresh: vi.fn(),
    isLoading: false,
    isBackendHealthy: true,
    currentView: 'chat' as const,
    onViewChange: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<ThreadList {...props} />) };
}

describe('ThreadList', () => {
  afterEach(cleanup);

  it('mostra ogni conversazione come pulsante, con quella corrente marcata', () => {
    renderList();
    const list = screen.getByRole('list', { name: 'Conversazioni' });
    const current = within(list).getByRole('button', { name: /^Backup del NAS/ });
    const other = within(list).getByRole('button', { name: /^Aggiornamento Debian/ });

    expect(current.tagName).toBe('BUTTON');
    expect(current.getAttribute('type')).toBe('button');
    expect(current.getAttribute('aria-current')).toBe('true');
    expect(other.hasAttribute('aria-current')).toBe(false);
  });

  it('apre una conversazione dalla tastiera: il pulsante riceve il focus e si attiva', () => {
    const { props } = renderList();
    const other = screen.getByRole('button', { name: /^Aggiornamento Debian/ });
    other.focus();
    expect(document.activeElement).toBe(other);
    // Invio e Spazio attivano un <button> nativo con un click
    fireEvent.click(other);
    expect(props.onSelectThread).toHaveBeenCalledWith('thread_b');
  });

  it("elimina con un pulsante a parte, etichettato e non annidato in quello della conversazione", () => {
    const { props, container } = renderList();
    const remove = screen.getByRole('button', { name: 'Elimina la conversazione Aggiornamento Debian' });
    const select = screen.getByRole('button', { name: /^Aggiornamento Debian/ });

    expect(select.contains(remove)).toBe(false);
    expect(container.querySelectorAll('button button, button a, a button, button input')).toHaveLength(0);

    fireEvent.click(remove);
    expect(props.onDeleteThread).toHaveBeenCalledWith('thread_b');
    expect(props.onSelectThread).not.toHaveBeenCalled();
  });

  it('sta in una barra laterale con la navigazione delle viste', () => {
    const { props } = renderList({ currentView: 'memory' });
    expect(screen.getByRole('complementary', { name: 'Barra laterale' })).toBeTruthy();
    const nav = screen.getByRole('navigation', { name: 'Viste' });
    expect(within(nav).getByRole('button', { name: 'Memoria' }).getAttribute('aria-current')).toBe('page');
    expect(within(nav).getByRole('button', { name: 'Chat' }).hasAttribute('aria-current')).toBe(false);

    fireEvent.click(within(nav).getByRole('button', { name: 'Automazioni' }));
    expect(props.onViewChange).toHaveBeenCalledWith('automations');
  });

  it('non lascia testi in inglese', () => {
    const { container } = renderList();
    fireEvent.click(screen.getByTitle('Elimina tutte le conversazioni'));
    const attributes = [...container.querySelectorAll('[title], [aria-label], [placeholder]')].flatMap((el) =>
      ['title', 'aria-label', 'placeholder'].map((name) => el.getAttribute(name) ?? ''),
    );
    const text = [container.textContent ?? '', ...attributes].join(' ');
    expect(text).not.toMatch(/\b(Thread|threads|New|Delete|Clear|Cancel|Refresh|Filter|Connected|Connecting|sidebar)\b/);
  });
});
