import React, { useState } from 'react';
import { Palette, Plus } from 'lucide-react';
import { calendarApi } from '../../../api/calendar';
import { ColorPicker } from './ColorPicker';
import { inputClass, labelClass, submitClass } from './formStyles';
import type { ManageFormProps } from './types';

export const NewCalendarForm: React.FC<ManageFormProps> = ({ submit, isBusy, invalid }) => {
  const [name, setName] = useState('');
  const [color, setColor] = useState('#3b82f6');
  const [description, setDescription] = useState('');

  const create = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return invalid('Specifica un nome per il calendario.');
    submit(async () => {
      await calendarApi.createCalendar({ name: name.trim(), color, description: description.trim() });
      return `Calendario '${name}' creato con successo!`;
    }, 'Errore durante la creazione.');
  };

  return (
    <form onSubmit={create} className="space-y-4">
      <div>
        <label className={labelClass}>
          Nome Calendario <span className="text-rose-400">*</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="es. Lavoro, Palestra, Manutenzione Homelab..."
          required
          className={`${inputClass} py-2.5`}
        />
      </div>

      <div>
        <label className={`${labelClass} flex items-center gap-1`}>
          <Palette size={13} /> Colore Calendario
        </label>
        <ColorPicker value={color} onChange={setColor} size="md" />
      </div>

      <div>
        <label className={labelClass}>Descrizione (opzionale)</label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Note o dettagli sullo scopo del calendario..."
          className={inputClass}
        />
      </div>

      <div className="pt-2 flex justify-end">
        <button type="submit" disabled={isBusy} className={submitClass}>
          <Plus size={14} />
          <span>{isBusy ? 'Creazione...' : 'Crea Calendario'}</span>
        </button>
      </div>
    </form>
  );
};
