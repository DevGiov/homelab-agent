import { createRef } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarEventItem } from '../../api/calendar';
import { AgendaView } from './AgendaView';

const event: CalendarEventItem = {
  id: 'ev-1',
  uid: 'ev-1',
  calendar_id: 'cal-1',
  summary: 'Riunione di prova',
  dtstart: '2026-11-20T09:00:00Z',
  dtend: '2026-11-20T10:00:00Z',
  all_day: false,
  status: 'confirmed',
};

describe('AgendaView', () => {
  afterEach(cleanup);

  it("ogni evento si apre anche da tastiera, col pulsante Modifica", () => {
    const onOpenEvent = vi.fn();
    render(
      <AgendaView events={[event]} containerRef={createRef()} todayMarkerRef={createRef()} onNewEvent={vi.fn()} onOpenEvent={onOpenEvent} />,
    );
    const edit = screen.getByRole('button', { name: "Modifica l'evento Riunione di prova" });
    expect(edit.className.split(/\s+/)).toEqual(expect.arrayContaining(['can-hover:opacity-0', 'focus-visible:opacity-100']));
    fireEvent.click(edit);
    expect(onOpenEvent).toHaveBeenCalledTimes(1);
    expect(onOpenEvent).toHaveBeenCalledWith(event);
  });
});
