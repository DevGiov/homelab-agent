import { http } from './http';

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
    return http.get<CalendarItem[]>('/calendar/calendars');
  },

  async createCalendar(data: {
    name: string;
    color?: string;
    description?: string;
    is_visible?: boolean;
    provider?: string;
    external_feed_url?: string;
  }): Promise<CalendarItem> {
    return http.post<CalendarItem>('/calendar/calendars', data);
  },

  async updateCalendar(
    calendarId: string,
    data: Partial<CalendarItem> & { provider?: string; external_feed_url?: string }
  ): Promise<CalendarItem> {
    return http.put<CalendarItem>(`/calendar/calendars/${calendarId}`, data);
  },

  async deleteCalendar(calendarId: string): Promise<void> {
    await http.delete(`/calendar/calendars/${calendarId}`);
  },

  // --- Eventi ---
  async getEvents(params?: {
    calendar_id?: string;
    start_date?: string;
    end_date?: string;
    query?: string;
  }): Promise<CalendarEventItem[]> {
    return http.get<CalendarEventItem[]>('/calendar/events', params);
  },

  async getUpcomingEvents(days = 7): Promise<{ days: number; count: number; events: CalendarEventItem[] }> {
    return http.get<{ days: number; count: number; events: CalendarEventItem[] }>('/calendar/events/upcoming', { days });
  },

  async getEvent(eventId: string): Promise<CalendarEventItem> {
    return http.get<CalendarEventItem>(`/calendar/events/${eventId}`);
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
    return http.post<{ status: string; duplicate?: boolean; event: CalendarEventItem; message?: string }>(
      '/calendar/events',
      data
    );
  },

  async updateEvent(
    eventId: string,
    data: Partial<CalendarEventItem> & { duration?: string }
  ): Promise<{ status: string; event: CalendarEventItem }> {
    return http.put<{ status: string; event: CalendarEventItem }>(`/calendar/events/${eventId}`, data);
  },

  async deleteEvent(eventId: string): Promise<void> {
    await http.delete(`/calendar/events/${eventId}`);
  },

  // --- Disponibilità & Sincronizzazione ---
  async checkAvailability(params: {
    start_time: string;
    duration?: string;
    end_time?: string;
    calendar_id?: string;
  }): Promise<AvailabilityResult> {
    return http.get<AvailabilityResult>('/calendar/availability', params);
  },

  async syncCalendars(): Promise<{ status: string; result: any }> {
    return http.post<{ status: string; result: any }>('/calendar/sync');
  },

  async importIcsUrl(data: {
    url: string;
    name?: string;
    color?: string;
  }): Promise<{ status: string; calendar: CalendarItem; synced_count: number }> {
    return http.post<{ status: string; calendar: CalendarItem; synced_count: number }>(
      '/calendar/import/url',
      data
    );
  },

  async importIcsFile(
    file: File,
    calendarId?: string,
    calendarName?: string,
    color?: string
  ): Promise<{ status: string; calendar: CalendarItem; imported_count: number }> {
    const formData = new FormData();
    formData.append('file', file);
    if (calendarId) formData.append('calendar_id', calendarId);
    if (calendarName) formData.append('calendar_name', calendarName);
    if (color) formData.append('color', color);

    return http.post<{ status: string; calendar: CalendarItem; imported_count: number }>(
      '/calendar/import/file',
      formData
    );
  },

  async importIcsRaw(data: {
    ics_content: string;
    calendar_id?: string;
    calendar_name?: string;
    color?: string;
  }): Promise<{ status: string; calendar: CalendarItem; imported_count: number }> {
    return http.post<{ status: string; calendar: CalendarItem; imported_count: number }>(
      '/calendar/import/ics',
      data
    );
  },
};

