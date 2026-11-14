import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ThreadItem } from './api/threads';
import { ThreadList } from './ThreadList';

const threads: ThreadItem[] = [
  { thread_id: 'thread_a', title: 'Backup del NAS', last_message: 'Fatto', checkpoint_count: 4 },
  { thread_id: 'thread_b', title: 'Aggiornamento Debian', last_message: null, checkpoint_count: 0, is_active: true },
];

/**
 * Clic con modificatori: vero se la pagina lo lascia al browser (nessun preventDefault). Il listener sul documento lo
 * ferma dopo, perché jsdom non sa aprire un'altra scheda.
 */
function leftToBrowser(el: HTMLElement, init: MouseEventInit) {
  let prevented = true;
  const observe = (e: Event) => {
    prevented = e.defaultPrevented;
    e.preventDefault();
  };
  document.addEventListener('click', observe);
  fireEvent.click(el, init);
  document.removeEventListener('click', observe);
  return !prevented;
}

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

  it('mostra ogni conversazione come link alla sua URL, con quella corrente marcata', () => {
    renderList({ threads: [...threads, { thread_id: 'id con/spazio', title: 'Strana', last_message: null, checkpoint_count: 0 }] });
    const list = screen.getByRole('list', { name: 'Conversazioni' });
    const current = within(list).getByRole('link', { name: /^Backup del NAS/ });
    const other = within(list).getByRole('link', { name: /^Aggiornamento Debian/ });

    expect(current.tagName).toBe('A');
    expect(current.getAttribute('href')).toBe('/c/thread_a');
    expect(within(list).getByRole('link', { name: /^Strana/ }).getAttribute('href')).toBe('/c/id%20con%2Fspazio');
    expect(current.getAttribute('aria-current')).toBe('true');
    expect(other.hasAttribute('aria-current')).toBe(false);
  });

  it('apre una conversazione dalla tastiera: il link riceve il focus e si attiva', () => {
    const { props } = renderList();
    const other = screen.getByRole('link', { name: /^Aggiornamento Debian/ });
    other.focus();
    expect(document.activeElement).toBe(other);
    // Invio su un link nativo arriva come click, senza tasti modificatori
    const plain = fireEvent.click(other);
    expect(plain).toBe(false); // preventDefault: la pagina non viene ricaricata
    expect(props.onSelectThread).toHaveBeenCalledWith('thread_b');
  });

  it('Ctrl, Cmd e Maiusc sul link lasciano al browser la nuova scheda o finestra', () => {
    const { props } = renderList();
    const other = screen.getByRole('link', { name: /^Aggiornamento Debian/ });
    for (const modifier of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }]) {
      expect(leftToBrowser(other, modifier)).toBe(true);
    }
    expect(props.onSelectThread).not.toHaveBeenCalled();
  });

  it("elimina con un pulsante a parte, etichettato e non annidato in quello della conversazione", () => {
    const { props, container } = renderList();
    const remove = screen.getByRole('button', { name: 'Elimina la conversazione Aggiornamento Debian' });
    const select = screen.getByRole('link', { name: /^Aggiornamento Debian/ });

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
    expect(within(nav).getByRole('link', { name: 'Memoria' }).getAttribute('aria-current')).toBe('page');
    expect(within(nav).getByRole('link', { name: 'Chat' }).hasAttribute('aria-current')).toBe(false);

    expect(fireEvent.click(within(nav).getByRole('link', { name: 'Automazioni' }))).toBe(false);
    expect(props.onViewChange).toHaveBeenCalledWith('automations');
  });

  it('ogni vista è un link alla sua URL, che si apre anche in un’altra scheda', () => {
    const { props } = renderList({ viewHref: (view) => (view === 'chat' ? '/c/thread_a' : `/vista-${view}`) });
    const nav = screen.getByRole('navigation', { name: 'Viste' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/c/thread_a',
      '/vista-automations',
      '/vista-calendar',
      '/vista-memory',
      '/vista-metrics',
    ]);
    expect(leftToBrowser(links[3], { ctrlKey: true })).toBe(true);
    expect(props.onViewChange).not.toHaveBeenCalled();
  });

  it('senza viewHref i link portano all’ingresso di ogni vista', () => {
    renderList();
    const nav = screen.getByRole('navigation', { name: 'Viste' });
    expect(within(nav).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual([
      '/',
      '/automazioni',
      '/calendario',
      '/memoria',
      '/metriche',
    ]);
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
