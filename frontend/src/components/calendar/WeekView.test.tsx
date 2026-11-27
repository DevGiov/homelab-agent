import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarEventItem } from '../../api/calendar';
import { groupByDate } from '../../utils/calendarDates';
import { WeekView } from './WeekView';

const event = (id: string, summary: string, dtstart: string): CalendarEventItem => ({
  id,
  uid: id,
  calendar_id: 'cal-1',
  summary,
  dtstart,
  dtend: dtstart,
  all_day: false,
  status: 'confirmed',
});

const events = [
  event('ev-1', 'Riunione di prova', '2026-11-12T09:00:00'),
  event('ev-2', 'Cena di prova', '2026-11-12T20:30:00'),
  event('ev-3', 'Dentista di prova', '2026-11-14T10:00:00'),
];

const renderWeek = () => {
  const onNewEvent = vi.fn();
  const onOpenEvent = vi.fn();
  // Settimana da lunedì 9 a domenica 15 novembre 2026
  render(<WeekView currentDate={new Date(2026, 10, 12)} eventsByDate={groupByDate(events)} onNewEvent={onNewEvent} onOpenEvent={onOpenEvent} />);
  return { onNewEvent, onOpenEvent };
};

describe('WeekView', () => {
  afterEach(cleanup);

  it('ogni giorno è un pulsante col nome del giorno e il numero di eventi, come nella vista mensile', () => {
    renderWeek();

    expect(screen.getByRole('button', { name: '12 novembre, 2 eventi' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '14 novembre, 1 evento' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '9 novembre, nessun evento' })).toBeTruthy();
  });

  it('il pulsante del giorno crea un evento in quella data senza aprire altro; gli eventi sono pulsanti che si aprono', () => {
    const { onNewEvent, onOpenEvent } = renderWeek();

    fireEvent.click(screen.getByRole('button', { name: '14 novembre, 1 evento' }));
    expect(onNewEvent).toHaveBeenCalledTimes(1);
    expect(onNewEvent).toHaveBeenCalledWith('2026-11-14');

    fireEvent.click(screen.getByRole('button', { name: /Cena di prova/ }));
    expect(onOpenEvent).toHaveBeenCalledTimes(1);
    expect(onOpenEvent.mock.calls[0][0].id).toBe('ev-2');
    expect(onNewEvent).toHaveBeenCalledTimes(1);
  });
});
