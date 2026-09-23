import { api } from '../api';

export interface CalendarItem {
  id: string;
  name: string;
  color: string;
  source: 'local' | 'caldav' | 'google' | 'webcal' | string;
  sync_url?: string;
  account_id?: string;
  is_visible: boolean;
  is_read_only: boolean;
  event_count?: number;
  last_synced_at?: string;
  sync_error?: string;
  created_at?: string;
  updated_at?: string;
}

export interface CalendarEventItem {
  id: string;
  uid: string;
  calendar_id: string;
  calendar_name?: string;
  calendar_color?: string;
  calendar_source?: string;
  summary: string;
  description?: string;
  location?: string;
  dtstart: string;
  dtend: string;
  all_day: boolean;
  is_utc?: boolean;
  rrule?: string;
  recurrence_exdates?: string[];
  category?: string;
  importance?: string;
  status: 'confirmed' | 'tentative' | 'cancelled' | string;
  color?: string;
  reminder_minutes?: number;
  source_type?: string;
  source_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface FreeSlot {
  start: string;
  end: string;
  start_iso: string;
  end_iso: string;
  duration_minutes: number;
}

export interface AvailabilityResult {
  start_time: string;
  end_time: string;
  available: boolean;
  conflict_count: number;
  conflicts: CalendarEventItem[];
}

export const calendarApi = {
  // --- Calendari ---
  async getCalendars(): Promise<CalendarItem[]> {
    const res = await api.get<CalendarItem[]>('/calendar/calendars');
    return res.data;
  },

  async createCalendar(data: {
    name: string;
    color?: string;
    description?: string;
    is_visible?: boolean;
    provider?: string;
    external_feed_url?: string;
  }): Promise<CalendarItem> {
    const res = await api.post<CalendarItem>('/calendar/calendars', data);
    return res.data;
  },

  async updateCalendar(
    calendarId: string,
    data: Partial<CalendarItem> & { provider?: string; external_feed_url?: string }
  ): Promise<CalendarItem> {
    const res = await api.put<CalendarItem>(`/calendar/calendars/${calendarId}`, data);
    return res.data;
  },

  async deleteCalendar(calendarId: string): Promise<void> {
    await api.delete(`/calendar/calendars/${calendarId}`);
  },

  // --- Eventi ---
  async getEvents(params?: {
    calendar_id?: string;
    start_date?: string;
    end_date?: string;
    query?: string;
  }): Promise<CalendarEventItem[]> {
    const res = await api.get<CalendarEventItem[]>('/calendar/events', { params });
    return res.data;
  },

  async getUpcomingEvents(days = 7): Promise<{ days: number; count: number; events: CalendarEventItem[] }> {
    const res = await api.get<{ days: number; count: number; events: CalendarEventItem[] }>('/calendar/events/upcoming', {
      params: { days },
    });
    return res.data;
  },

  async getEvent(eventId: string): Promise<CalendarEventItem> {
    const res = await api.get<CalendarEventItem>(`/calendar/events/${eventId}`);
    return res.data;
  },

  async createEvent(data: {
    summary: string;
    dtstart: string;
    dtend?: string;
    duration?: string;
    calendar_id?: string;
    description?: string;
    location?: string;
    all_day?: boolean;
    category?: string;
    importance?: string;
    color?: string;
    status?: string;
  }): Promise<{ status: string; duplicate?: boolean; event: CalendarEventItem; message?: string }> {
    const res = await api.post<{ status: string; duplicate?: boolean; event: CalendarEventItem; message?: string }>(
      '/calendar/events',
      data
    );
    return res.data;
  },

  async updateEvent(
    eventId: string,
    data: Partial<CalendarEventItem> & { duration?: string }
  ): Promise<{ status: string; event: CalendarEventItem }> {
    const res = await api.put<{ status: string; event: CalendarEventItem }>(`/calendar/events/${eventId}`, data);
    return res.data;
  },

  async deleteEvent(eventId: string): Promise<void> {
    await api.delete(`/calendar/events/${eventId}`);
  },

  // --- Disponibilità & Sincronizzazione ---
  async checkAvailability(params: {
    start_time: string;
    duration?: string;
    end_time?: string;
    calendar_id?: string;
  }): Promise<AvailabilityResult> {
    const res = await api.get<AvailabilityResult>('/calendar/availability', { params });
    return res.data;
  },

  async syncCalendars(): Promise<{ status: string; result: any }> {
    const res = await api.post<{ status: string; result: any }>('/calendar/sync');
    return res.data;
  },
};
