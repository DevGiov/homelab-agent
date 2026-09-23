import React, { useState, useEffect } from 'react';
import { X, Trash2, Calendar as CalIcon, Clock, MapPin, Tag, AlertCircle, CheckCircle2 } from 'lucide-react';
import type { CalendarItem, CalendarEventItem } from '../../api/calendarApi';
import { calendarApi } from '../../api/calendarApi';

interface EventModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  calendars: CalendarItem[];
  eventToEdit?: CalendarEventItem | null;
  defaultDate?: string; // YYYY-MM-DD
}

export const EventModal: React.FC<EventModalProps> = ({
  isOpen,
  onClose,
  onSave,
  calendars,
  eventToEdit,
  defaultDate,
}) => {
  const [summary, setSummary] = useState('');
  const [calendarId, setCalendarId] = useState('');
  const [dtstart, setDtstart] = useState('');
  const [dtend, setDtend] = useState('');
  const [duration, setDuration] = useState('1h');
  const [useDuration, setUseDuration] = useState(true);
  const [allDay, setAllDay] = useState(false);
  const [location, setLocation] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('meeting');
  const [importance, setImportance] = useState('normal');
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflictWarning, setConflictWarning] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    setError(null);
    setConflictWarning(null);

    if (eventToEdit) {
      setSummary(eventToEdit.summary || '');
      setCalendarId(eventToEdit.calendar_id || (calendars[0]?.id ?? ''));
      setAllDay(eventToEdit.all_day);
      setLocation(eventToEdit.location || '');
      setDescription(eventToEdit.description || '');
      setCategory(eventToEdit.category || 'meeting');
      setImportance(eventToEdit.importance || 'normal');
      setUseDuration(false);

      if (eventToEdit.all_day) {
        setDtstart(eventToEdit.dtstart.substring(0, 10));
        setDtend(eventToEdit.dtend.substring(0, 10));
      } else {
        setDtstart(eventToEdit.dtstart.substring(0, 16));
        setDtend(eventToEdit.dtend.substring(0, 16));
      }
    } else {
      // Nuovo evento
      const now = new Date();
      let datePrefix = defaultDate;
      if (!datePrefix) {
        const y = now.getFullYear();
        const m = String(now.getMonth() + 1).padStart(2, '0');
        const d = String(now.getDate()).padStart(2, '0');
        datePrefix = `${y}-${m}-${d}`;
      }

      const nextHour = String(Math.min(now.getHours() + 1, 23)).padStart(2, '0');
      const defaultStart = `${datePrefix}T${nextHour}:00`;

      setSummary('');
      setCalendarId(calendars.find(c => !c.is_read_only)?.id || calendars[0]?.id || '');
      setAllDay(false);
      setDtstart(defaultStart);
      setDtend('');
      setDuration('1h');
      setUseDuration(true);
      setLocation('');
      setDescription('');
      setCategory('meeting');
      setImportance('normal');
    }
  }, [isOpen, eventToEdit, defaultDate, calendars]);

  // Controllo conflitti al cambio di orario
  useEffect(() => {
    if (!isOpen || allDay || !dtstart || eventToEdit) return;

    const checkTimeout = setTimeout(async () => {
      try {
        const res = await calendarApi.checkAvailability({
          start_time: dtstart,
          duration: useDuration ? duration : undefined,
          end_time: !useDuration && dtend ? dtend : undefined,
          calendar_id: calendarId || undefined,
        });

        if (!res.available && res.conflict_count > 0) {
          const names = res.conflicts.map(c => c.summary).slice(0, 2).join(', ');
          setConflictWarning(`Attenzione: ${res.conflict_count} evento/i in conflitto (${names})`);
        } else {
          setConflictWarning(null);
        }
      } catch {
        // Ignora errori di check background
      }
    }, 400);

    return () => clearTimeout(checkTimeout);
  }, [isOpen, dtstart, dtend, duration, useDuration, calendarId, allDay, eventToEdit]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!summary.trim()) {
      setError('Inserisci un titolo per l\'evento');
      return;
    }
    if (!dtstart) {
      setError('Specifica la data di inizio');
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      let finalStart = dtstart;
      let finalEnd = dtend;

      if (allDay) {
        if (!finalStart.includes('T')) finalStart = `${finalStart}T00:00:00`;
        if (!finalEnd || !finalEnd.includes('T')) finalEnd = `${finalStart.substring(0, 10)}T23:59:59`;
      }

      if (eventToEdit) {
        await calendarApi.updateEvent(eventToEdit.uid || eventToEdit.id, {
          calendar_id: calendarId,
          summary: summary.trim(),
          dtstart: finalStart,
          dtend: !useDuration && finalEnd ? finalEnd : undefined,
          duration: useDuration ? duration : undefined,
          all_day: allDay,
          location: location.trim(),
          description: description.trim(),
          category,
          importance,
        });
      } else {
        await calendarApi.createEvent({
          calendar_id: calendarId,
          summary: summary.trim(),
          dtstart: finalStart,
          dtend: !useDuration && finalEnd ? finalEnd : undefined,
          duration: useDuration ? duration : undefined,
          all_day: allDay,
          location: location.trim(),
          description: description.trim(),
          category,
          importance,
        });
      }

      onSave();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Errore durante il salvataggio dell\'evento');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!eventToEdit) return;
    if (!window.confirm(`Sei sicuro di voler eliminare l'evento "${eventToEdit.summary}"?`)) return;

    setIsDeleting(true);
    setError(null);
    try {
      await calendarApi.deleteEvent(eventToEdit.uid || eventToEdit.id);
      onSave();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Errore durante l\'eliminazione');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div 
        className="w-full max-w-lg glass-panel border border-border/70 rounded-2xl shadow-2xl bg-panel overflow-hidden flex flex-col max-h-[90vh]"
        onClick={e => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between bg-panel-header/50">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <CalIcon size={18} />
            </div>
            <div>
              <h2 className="font-semibold text-base text-fg">
                {eventToEdit ? 'Modifica Evento' : 'Nuovo Evento'}
              </h2>
              <p className="text-xs text-fg-muted">
                {eventToEdit ? 'Aggiorna i dettagli dell\'appuntamento' : 'Pianifica un nuovo appuntamento o promemoria'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel-hover rounded-lg transition"
            title="Chiudi"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Body / Form */}
        <form onSubmit={handleSubmit} className="p-6 overflow-y-auto space-y-4 flex-1">
          {error && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-xl flex items-start gap-2.5 text-xs text-rose-400">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {conflictWarning && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/25 rounded-xl flex items-start gap-2.5 text-xs text-amber-400">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <span>{conflictWarning}</span>
            </div>
          )}

          {/* Titolo */}
          <div>
            <label className="block text-xs font-medium text-fg-muted mb-1.5">
              Titolo Evento <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={summary}
              onChange={e => setSummary(e.target.value)}
              placeholder="es. Riunione Team Progetto, Manutenzione Homelab..."
              required
              className="w-full px-3.5 py-2.5 bg-input border border-border/70 rounded-xl text-sm text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition shadow-inner"
            />
          </div>

          {/* Calendario & Categoria */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-fg-muted mb-1.5">
                Calendario
              </label>
              <select
                value={calendarId}
                onChange={e => setCalendarId(e.target.value)}
                className="w-full px-3 py-2 bg-input border border-border/70 rounded-xl text-xs text-fg focus:outline-none focus:border-accent transition"
              >
                {calendars.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.name} {c.is_read_only ? '(Sola lettura)' : ''}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-fg-muted mb-1.5 flex items-center gap-1">
                <Tag size={12} /> Categoria
              </label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value)}
                className="w-full px-3 py-2 bg-input border border-border/70 rounded-xl text-xs text-fg focus:outline-none focus:border-accent transition"
              >
                <option value="meeting">Riunione / Meeting</option>
                <option value="personal">Personale</option>
                <option value="homelab">Homelab / Server</option>
                <option value="flight">Viaggio / Volo</option>
                <option value="reminder">Promemoria</option>
                <option value="general">Generale</option>
              </select>
            </div>
          </div>

          {/* Flag Tutto il Giorno */}
          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="allDay"
              checked={allDay}
              onChange={e => setAllDay(e.target.checked)}
              className="rounded border-border text-accent focus:ring-accent"
            />
            <label htmlFor="allDay" className="text-xs text-fg cursor-pointer select-none">
              Evento per l'intera giornata
            </label>
          </div>

          {/* Date & Orari */}
          <div className="p-3.5 bg-panel-header/30 border border-border/40 rounded-xl space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-medium text-fg-muted mb-1 flex items-center gap-1">
                  <Clock size={12} /> {allDay ? 'Data' : 'Inizio'}
                </label>
                <input
                  type={allDay ? 'date' : 'datetime-local'}
                  value={dtstart}
                  onChange={e => setDtstart(e.target.value)}
                  required
                  className="w-full px-3 py-2 bg-input border border-border/70 rounded-lg text-xs text-fg focus:outline-none focus:border-accent transition"
                />
              </div>

              {!allDay && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[11px] font-medium text-fg-muted">
                      {useDuration ? 'Durata' : 'Fine'}
                    </label>
                    <button
                      type="button"
                      onClick={() => setUseDuration(!useDuration)}
                      className="text-[10px] text-accent hover:underline cursor-pointer"
                    >
                      {useDuration ? 'Specifica orario fine' : 'Usa durata'}
                    </button>
                  </div>

                  {useDuration ? (
                    <select
                      value={duration}
                      onChange={e => setDuration(e.target.value)}
                      className="w-full px-3 py-2 bg-input border border-border/70 rounded-lg text-xs text-fg focus:outline-none focus:border-accent transition"
                    >
                      <option value="15m">15 minuti</option>
                      <option value="30m">30 minuti</option>
                      <option value="45m">45 minuti</option>
                      <option value="1h">1 ora</option>
                      <option value="1h30m">1 ora e 30m</option>
                      <option value="2h">2 ore</option>
                      <option value="3h">3 ore</option>
                      <option value="4h">4 ore</option>
                    </select>
                  ) : (
                    <input
                      type="datetime-local"
                      value={dtend}
                      onChange={e => setDtend(e.target.value)}
                      className="w-full px-3 py-2 bg-input border border-border/70 rounded-lg text-xs text-fg focus:outline-none focus:border-accent transition"
                    />
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Luogo / Link Meeting */}
          <div>
            <label className="block text-xs font-medium text-fg-muted mb-1.5 flex items-center gap-1">
              <MapPin size={12} /> Luogo o Link Virtuale
            </label>
            <input
              type="text"
              value={location}
              onChange={e => setLocation(e.target.value)}
              placeholder="es. Stanza 3A, oppure https://meet.google.com/xyz..."
              className="w-full px-3.5 py-2 bg-input border border-border/70 rounded-xl text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent transition"
            />
          </div>

          {/* Descrizione / Note */}
          <div>
            <label className="block text-xs font-medium text-fg-muted mb-1.5">
              Descrizione / Note
            </label>
            <textarea
              rows={3}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Aggiungi ordine del giorno, codici prenotazione, note o dettagli..."
              className="w-full px-3.5 py-2 bg-input border border-border/70 rounded-xl text-xs text-fg placeholder:text-fg-muted/60 focus:outline-none focus:border-accent transition resize-none"
            />
          </div>

          {/* Modal Footer */}
          <div className="pt-2 border-t border-border/40 flex items-center justify-between gap-2">
            {eventToEdit ? (
              <button
                type="button"
                onClick={handleDelete}
                disabled={isDeleting || isSaving}
                className="px-3 py-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/25 rounded-xl text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
              >
                <Trash2 size={14} />
                <span>{isDeleting ? 'Eliminazione...' : 'Elimina'}</span>
              </button>
            ) : <div />}

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={isSaving || isDeleting}
                className="px-4 py-2 bg-panel-header/50 hover:bg-panel-hover text-fg-muted hover:text-fg border border-border/60 rounded-xl text-xs font-medium transition cursor-pointer"
              >
                Annulla
              </button>
              <button
                type="submit"
                disabled={isSaving || isDeleting}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm shadow-accent/20 transition cursor-pointer disabled:opacity-50"
              >
                {isSaving ? (
                  <span>Salvataggio...</span>
                ) : (
                  <>
                    <CheckCircle2 size={14} />
                    <span>{eventToEdit ? 'Salva Modifiche' : 'Crea Evento'}</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
