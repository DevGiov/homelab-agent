import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AutomationsHeader } from './AutomationsHeader';

const renderHeader = () =>
  render(
    <AutomationsHeader
      counts={{ automations: 12, jobs: 10, runs: 50, approvals: 14 }}
      isLoading={false}
      onRefresh={vi.fn()}
      onOpenMobileSidebar={vi.fn()}
    />,
  );

const classesOf = (element: Element) => element.getAttribute('class')?.split(/\s+/) ?? [];

// jsdom non calcola il layout: qui si controllano le regole che impediscono il taglio. La misura vera (Chromium, 320-400
// px con numeri a due cifre) è nel messaggio del commit che le ha introdotte.
describe('AutomationsHeader', () => {
  afterEach(cleanup);

  it('nulla si taglia: niente scorrimento nascosto, titolo che va a capo, pillole che passano sotto se non c’è posto', () => {
    const { container } = renderHeader();
    const header = container.firstElementChild!;
    const clipping = [header, ...header.querySelectorAll('*')].filter((el) =>
      classesOf(el).some((c) => /^(overflow-(x-)?(auto|hidden|scroll)|truncate|whitespace-nowrap|text-ellipsis)$/.test(c)),
    );
    expect(clipping.map((el) => el.outerHTML.slice(0, 80))).toEqual([]);

    expect(classesOf(header)).toContain('flex-wrap');
    const [titleGroup, controls] = Array.from(header.children);
    // Senza min-w-0 il gruppo del titolo non scende sotto la sua parola più lunga: le pillole vanno a capo prima
    expect(classesOf(titleGroup)).toContain('flex-1');
    expect(classesOf(titleGroup)).not.toContain('min-w-0');
    expect(classesOf(controls)).toEqual(expect.arrayContaining(['flex-wrap', 'ml-auto']));
    expect(screen.getByRole('heading', { name: 'Automazioni e loop' })).toBeTruthy();
  });

  it('le pillole a sola icona e i pulsanti hanno un nome per i lettori di schermo', () => {
    renderHeader();
    for (const label of ['Auto:', 'Job:', 'Approvazioni:']) {
      const span = screen.getByText(label);
      expect(classesOf(span)).toEqual(expect.arrayContaining(['sr-only', '@3xl:not-sr-only']));
      expect(classesOf(span)).not.toContain('hidden');
    }
    expect(screen.getByText('Auto:').parentElement!.textContent).toBe('Auto:12');
    expect(screen.getByText('Approvazioni:').parentElement!.textContent).toBe('Approvazioni:14');
    expect(screen.getByRole('button', { name: 'Aggiorna dati' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apri menu principale' })).toBeTruthy();
  });
});
