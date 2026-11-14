import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarEventItem, CalendarItem } from '../../api/calendar';
import { mockBackend } from '../../test/backend';
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
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

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

  it("elimina l'evento solo dopo la conferma nel dialogo dell'app; Escape chiude la conferma e lascia aperto l'evento", async () => {
    const nativeConfirm = vi.fn(() => true);
    vi.stubGlobal('confirm', nativeConfirm);
    const { requests } = mockBackend({}, [[/^\/v1\/calendar\/events\//, () => new Response(null, { status: 204 })]]);
    const onClose = vi.fn();
    const onSave = vi.fn();
    render(<EventModal isOpen onClose={onClose} onSave={onSave} calendars={calendars} eventToEdit={event} />);
    const modal = screen.getByRole('dialog', { name: 'Modifica Evento' });
    const deleteButton = within(modal).getByRole('button', { name: 'Elimina' });

    act(() => deleteButton.focus());
    fireEvent.click(deleteButton);
    const confirm = screen.getByRole('alertdialog');
    expect(within(confirm).getByText('Sei sicuro di voler eliminare l\'evento "Cena di prova"?')).toBeTruthy();
    // La conferma sta nel body, fuori dal pannello dell'evento
    expect(modal.contains(confirm)).toBe(false);
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    await act(async () => {});
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Modifica Evento' })).toBeTruthy();
    expect(document.activeElement).toBe(deleteButton);
    expect(onClose).not.toHaveBeenCalled();

    // Il clic sul fondo della conferma annulla senza chiudere l'evento
    fireEvent.click(deleteButton);
    fireEvent.click(screen.getByRole('alertdialog').parentElement!);
    await act(async () => {});
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(requests).toEqual([]);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(deleteButton);
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Elimina' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.map((r) => `${r.method} ${r.path}`)).toEqual(['DELETE /v1/calendar/events/evt-1@esempio.invalid']);
    expect(onSave).toHaveBeenCalled();
    expect(nativeConfirm).not.toHaveBeenCalled();
  });
});
