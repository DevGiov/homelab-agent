import React, { useState } from 'react';
import { Upload } from 'lucide-react';
import { calendarApi, type CalendarItem } from '../../../api/calendar';
import { ColorPicker } from './ColorPicker';
import { inputClass, labelClass, submitClass } from './formStyles';
import type { ManageFormProps } from './types';

const NEW_CALENDAR = '__new__';

/** Import di un file .ics in un calendario esistente o in uno nuovo. */
export const ImportFileForm: React.FC<ManageFormProps & { calendars: CalendarItem[] }> = ({ calendars, submit, isBusy, invalid }) => {
  const [file, setFile] = useState<File | null>(null);
  const [targetId, setTargetId] = useState(NEW_CALENDAR);
  const [newName, setNewName] = useState('');
  const [color, setColor] = useState('#10b981');
  const isNew = targetId === NEW_CALENDAR;

  const selectFile = (selected?: File) => {
    if (!selected) return;
    setFile(selected);
    if (!newName) setNewName(selected.name.replace('.ics', ''));
  };

  const importFile = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return invalid('Seleziona un file .ics da importare.');
    submit(async () => {
      const res = await calendarApi.importIcsFile(
        file,
        isNew ? undefined : targetId,
        isNew ? newName.trim() || file.name.replace('.ics', '') : undefined,
        color
      );
      return `File importato! ${res.imported_count || 0} eventi aggiunti al calendario.`;
    }, "Errore durante l'importazione del file.");
  };

  return (
    <form onSubmit={importFile} className="space-y-4">
      <div>
        <label className={labelClass}>Seleziona file .ICS esportato da Google Calendar, Outlook o Apple Calendar</label>
        <div className="border-2 border-dashed border-border/80 hover:border-accent/60 rounded-xl p-5 text-center bg-input-bg transition cursor-pointer flex flex-col items-center justify-center gap-2">
          <Upload size={24} className="text-accent" />
          <input
            type="file"
            accept=".ics,text/calendar"
            onChange={(e) => selectFile(e.target.files?.[0])}
            className="text-xs text-fg file:mr-4 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-medium file:bg-accent file:text-white hover:file:bg-accent-hover cursor-pointer"
          />
          {file && (
            <p className="text-xs text-emerald-400 font-medium">
              File selezionato: {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>Destinazione Eventi</label>
          <select
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            className="w-full px-3 py-2 bg-input-bg text-fg border border-input-border rounded-xl text-xs focus:outline-none focus:border-accent"
          >
            <option value={NEW_CALENDAR} className="bg-panel text-fg">
              + Crea un nuovo calendario per questo file
            </option>
            {calendars.map((c) => (
              <option key={c.id} value={c.id} className="bg-panel text-fg">
                Importa dentro: {c.name}
              </option>
            ))}
          </select>
        </div>

        {isNew && (
          <div className="space-y-3 sm:col-span-2">
            <div>
              <label className={labelClass}>Nome Nuovo Calendario</label>
              <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="es. Eventi Importati" className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Colore Calendario</label>
              <ColorPicker value={color} onChange={setColor} />
            </div>
          </div>
        )}
      </div>

      <div className="pt-2 flex justify-end">
        <button type="submit" disabled={!file || isBusy} className={submitClass}>
          <Upload size={14} />
          <span>{isBusy ? 'Importazione in corso...' : 'Importa File .ICS'}</span>
        </button>
      </div>
    </form>
  );
};
