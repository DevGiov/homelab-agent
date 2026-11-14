import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarEventItem, CalendarItem } from '../../api/calendar';
import { EventModal } from './EventModal';

const calendars: CalendarItem[] = [{ id: 'cal-1', name: 'Personale', color: '#3b82f6', source: 'local', is_visible: true, is_read_only: false }];
const event: CalendarEventItem = {
  id: 'evt-1',
  uid: 'evt-1@esempio.invalid',
  calendar_id: 'cal-1',
  summary: 'Cena di prova',
  dtstart: '2026-11-20T19:00:00Z',
  dtend: '2026-11-20T21:00:00Z',
  all_day: false,
  status: 'confirmed',
};

describe('EventModal', () => {
  afterEach(cleanup);

  it('ogni campo ha un nome dalla sua etichetta', () => {
    render(<EventModal isOpen onClose={vi.fn()} onSave={vi.fn()} calendars={calendars} eventToEdit={event} />);
    const dialog = screen.getByRole('dialog', { name: 'Modifica Evento' });
    const unnamed = [...dialog.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea')].filter(
      (field) => !field.labels?.length && !field.getAttribute('aria-label'),
    );
    expect(unnamed.map((f) => f.outerHTML.slice(0, 60))).toEqual([]);

    expect(within(dialog).getByLabelText(/Titolo Evento/)).toHaveProperty('value', 'Cena di prova');
    expect(within(dialog).getByLabelText('Calendario').tagName).toBe('SELECT');
    expect(within(dialog).getByLabelText(/Categoria/).tagName).toBe('SELECT');
    expect(within(dialog).getByLabelText(/Inizio/).getAttribute('type')).toBe('datetime-local');
    expect(within(dialog).getByLabelText('Fine').getAttribute('type')).toBe('datetime-local');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Usa durata' }));
    expect(within(dialog).getByLabelText('Durata').tagName).toBe('SELECT');
    expect(within(dialog).getByLabelText(/Luogo/).tagName).toBe('INPUT');
    expect(within(dialog).getByLabelText('Descrizione / Note').tagName).toBe('TEXTAREA');
    expect(within(dialog).getByLabelText("Evento per l'intera giornata").getAttribute('type')).toBe('checkbox');
  });
});
