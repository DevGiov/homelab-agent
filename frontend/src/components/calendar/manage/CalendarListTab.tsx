import React, { useState } from 'react';
import { Edit2, Save, Trash2 } from 'lucide-react';
import { calendarApi, type CalendarItem } from '../../../api/calendar';
import type { Notify } from '../../../hooks/useFeedback';
import { DEFAULT_CALENDAR_COLOR } from '../../../utils/calendarDates';
import { formatApiError } from '../../../utils/error';

interface CalendarListTabProps {
  calendars: CalendarItem[];
  notify: Notify;
  onChanged: () => void;
}

/** Calendari registrati: rinomina e colore in linea, eliminazione (mai dell'ultimo rimasto). */
export const CalendarListTab: React.FC<CalendarListTabProps> = ({ calendars, notify, onChanged }) => {
  const [editing, setEditing] = useState<{ id: string; name: string; color: string } | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const isLast = calendars.length <= 1;

  const run = async (action: () => Promise<unknown>, success: string, failure: string) => {
    setIsBusy(true);
    try {
      await action();
      notify('success', success);
      onChanged();
      return true;
    } catch (err) {
      notify('error', formatApiError(err, failure));
      return false;
    } finally {
      setIsBusy(false);
    }
  };

  const saveEditing = async () => {
    if (!editing?.name.trim()) return;
    const ok = await run(
      () => calendarApi.updateCalendar(editing.id, { name: editing.name.trim(), color: editing.color }),
      'Calendario aggiornato con successo.',
      'Errore salvataggio calendario.'
    );
    if (ok) setEditing(null);
  };

  const remove = (cal: CalendarItem) => {
    if (isLast) {
      notify('error', "Non puoi eliminare l'unico calendario rimasto nel sistema.");
      return;
    }
    if (!window.confirm(`Sei sicuro di voler eliminare il calendario '${cal.name}' e tutti i suoi eventi associati?`)) return;
    run(() => calendarApi.deleteCalendar(cal.id), `Calendario '${cal.name}' eliminato.`, 'Errore eliminazione.');
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-fg-muted">
        Gestisci i calendari registrati. Puoi rinominarli, cambiare il colore di visualizzazione o eliminarli.
      </p>

      <div className="divide-y divide-border/50 border border-border/70 rounded-xl overflow-hidden bg-panel-header/20">
        {calendars.map((cal) => {
          const isEditing = editing?.id === cal.id;
          return (
            <div
              key={cal.id}
              className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-panel-hover/30 transition"
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                {isEditing ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={editing.color}
                      onChange={(e) => setEditing({ ...editing, color: e.target.value })}
                      className="w-7 h-7 rounded border border-border cursor-pointer bg-transparent"
                    />
                    <input
                      type="text"
                      value={editing.name}
                      onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                      className="px-2.5 py-1 text-xs bg-input-bg text-fg border border-input-border rounded-lg focus:outline-none focus:border-accent"
                    />
                  </div>
                ) : (
                  <>
                    <span className="w-3.5 h-3.5 rounded-full shrink-0 shadow-sm" style={{ backgroundColor: cal.color || DEFAULT_CALENDAR_COLOR }} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-xs text-fg truncate">{cal.name}</span>
                        <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-panel border border-border text-fg-muted">
                          {cal.source}
                        </span>
                      </div>
                      <p className="text-[11px] text-fg-muted truncate">{cal.sync_url ? `Feed: ${cal.sync_url}` : 'Calendario locale'}</p>
                    </div>
                  </>
                )}
              </div>

              <div className="flex items-center justify-end gap-2 shrink-0">
                {cal.event_count !== undefined && (
                  <span className="text-xs text-fg-muted bg-panel px-2 py-1 rounded-lg border border-border/60">{cal.event_count} eventi</span>
                )}
                {isEditing ? (
                  <button
                    onClick={saveEditing}
                    disabled={isBusy}
                    className="p-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs flex items-center gap-1 transition cursor-pointer"
                    title="Salva modifiche"
                  >
                    <Save size={14} />
                    <span className="text-xs">Salva</span>
                  </button>
                ) : (
                  <button
                    onClick={() => setEditing({ id: cal.id, name: cal.name, color: cal.color || DEFAULT_CALENDAR_COLOR })}
                    className="p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition"
                    title="Modifica nome e colore"
                  >
                    <Edit2 size={14} />
                  </button>
                )}
                <button
                  onClick={() => remove(cal)}
                  disabled={isLast || isBusy}
                  className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition disabled:opacity-30 disabled:cursor-not-allowed"
                  title={isLast ? "Impossibile eliminare l'unico calendario" : 'Elimina calendario'}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
