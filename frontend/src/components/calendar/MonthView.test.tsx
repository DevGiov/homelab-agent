import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarEventItem } from '../../api/calendar';
import { groupByDate, toDateKey } from '../../utils/calendarDates';
import { MonthView } from './MonthView';

const event = (id: string, summary: string, dtstart: string, extra: Partial<CalendarEventItem> = {}): CalendarEventItem => ({
  id,
  uid: id,
  calendar_id: 'cal-1',
  summary,
  dtstart,
  dtend: dtstart,
  all_day: false,
  status: 'confirmed',
  ...extra,
});

const events = [
  event('ev-1', 'Riunione di prova', '2026-11-14T09:00:00'),
  event('ev-2', 'Cena di prova', '2026-11-14T20:30:00'),
  event('ev-3', 'Ferie di prova', '2026-11-20T00:00:00', { all_day: true }),
];

/** Larghezza della finestra per `useMediaQuery`: il telefono è sotto 640 px. */
const stubWidth = (px: number) =>
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: px >= Number(/min-width: (\d+)px/.exec(query)?.[1] ?? 0),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));

const renderMonth = () => {
  const onNewEvent = vi.fn();
  const onOpenEvent = vi.fn();
  const view = render(
    <MonthView currentDate={new Date(2026, 10, 1)} eventsByDate={groupByDate(events)} onNewEvent={onNewEvent} onOpenEvent={onOpenEvent} />,
  );
  return { ...view, onNewEvent, onOpenEvent };
};

describe('MonthView', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('ogni giorno è un pulsante col nome del giorno e il numero di eventi; gli eventi sono pulsanti, mai annidati', () => {
    stubWidth(1280);
    const { container } = renderMonth();

    expect(screen.getByRole('button', { name: '14 novembre, 2 eventi' }).textContent).toBe('14');
    expect(screen.getByRole('button', { name: '20 novembre, 1 evento' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '1 novembre, nessun evento' })).toBeTruthy();
    // Anche i giorni dei mesi accanto che completano le settimane
    expect(screen.getByRole('button', { name: '26 ottobre, nessun evento' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Riunione di prova/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Ferie di prova/ })).toBeTruthy();

    // Un pulsante per giorno (6 settimane: l'1 novembre 2026 è domenica) più uno per evento: nessun altro punto di Tab, nessun controllo dentro un altro
    const buttons = Array.from(container.querySelectorAll('button'));
    expect(buttons).toHaveLength(42 + events.length);
    expect(container.querySelectorAll('button button, button a, a button, a a')).toHaveLength(0);
    expect(buttons.filter((b) => !(b.getAttribute('aria-label') || b.textContent?.trim()))).toEqual([]);
    expect(container.querySelectorAll('[tabindex], [role="button"]')).toHaveLength(0);
  });

  it('il giorno di oggi è segnato come data corrente', () => {
    stubWidth(1280);
    const today = new Date();
    render(<MonthView currentDate={today} eventsByDate={new Map()} onNewEvent={vi.fn()} onOpenEvent={vi.fn()} />);
    const current = document.querySelectorAll('[aria-current="date"]');
    expect(current).toHaveLength(1);
    expect(current[0].getAttribute('data-date')).toBe(toDateKey(today));
  });

  it('su desktop il pulsante del giorno crea un evento in quella data, come il clic sulla cella; un evento si apre col suo pulsante', () => {
    stubWidth(1280);
    const { onNewEvent, onOpenEvent } = renderMonth();

    fireEvent.click(screen.getByRole('button', { name: '14 novembre, 2 eventi' }));
    expect(onNewEvent).toHaveBeenCalledTimes(1);
    expect(onNewEvent).toHaveBeenCalledWith('2026-11-14');

    fireEvent.click(screen.getByRole('button', { name: /Cena di prova/ }));
    expect(onOpenEvent).toHaveBeenCalledWith(events[1]);
    expect(onNewEvent).toHaveBeenCalledTimes(1);
  });

  it('su mobile il pulsante del giorno apre e chiude il dettaglio; Chiudi riporta il focus al giorno', () => {
    stubWidth(375);
    const { onNewEvent, onOpenEvent } = renderMonth();
    const day = screen.getByRole('button', { name: '14 novembre, 2 eventi' });
    expect(day.getAttribute('aria-expanded')).toBe('false');

    act(() => day.focus());
    fireEvent.click(day);
    expect(day.getAttribute('aria-expanded')).toBe('true');
    const detail = document.getElementById(day.getAttribute('aria-controls')!)!;
    expect(within(detail).getByText('Eventi del 2026-11-14')).toBeTruthy();
    expect(onNewEvent).not.toHaveBeenCalled();

    fireEvent.click(within(detail).getByRole('button', { name: /Riunione di prova/ }));
    expect(onOpenEvent).toHaveBeenCalledWith(events[0]);

    act(() => within(detail).getByRole('button', { name: 'Chiudi' }).focus());
    fireEvent.click(within(detail).getByRole('button', { name: 'Chiudi' }));
    expect(screen.queryByText('Eventi del 2026-11-14')).toBeNull();
    expect(day.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(day);

    fireEvent.click(day);
    fireEvent.click(day);
    expect(screen.queryByText('Eventi del 2026-11-14')).toBeNull();
  });
});
