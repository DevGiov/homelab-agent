import React, { useState } from 'react';
import { ExternalLink, Globe, HelpCircle } from 'lucide-react';
import { calendarApi } from '../../../api/calendar';
import { ColorPicker } from './ColorPicker';
import { inputClass, labelClass, PRESET_COLORS, submitClass } from './formStyles';
import type { ManageFormProps } from './types';

const GoogleHelp: React.FC = () => {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-3 bg-panel-header/40 border border-border/60 rounded-xl space-y-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full font-medium text-accent hover:underline text-left cursor-pointer"
      >
        <span className="flex items-center gap-1.5">
          <HelpCircle size={14} /> Come ottenere il link segreto da Google Calendar
        </span>
        <span>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <ol className="list-decimal pl-5 space-y-1 text-fg-muted text-[11px] leading-relaxed pt-1">
          <li>
            Apri Google Calendar da browser (
            <a href="https://calendar.google.com" target="_blank" rel="noreferrer" className="text-accent underline inline-flex items-center gap-0.5">
              calendar.google.com <ExternalLink size={10} />
            </a>
            ).
          </li>
          <li>
            Sulla sinistra, sotto <strong>I miei calendari</strong>, passa con il mouse sul tuo calendario e clicca sui{' '}
            <strong>tre puntini (Opzioni)</strong> → <strong>Impostazioni e condivisione</strong>.
          </li>
          <li>
            Scorri in basso fino alla sezione <strong>Integra calendario</strong>.
          </li>
          <li>
            Individua e copia la voce <strong>"Indirizzo segreto in formato iCal"</strong> (attenzione: non usare quello pubblico se il
            calendario è privato).
          </li>
          <li>
            Incolla l'indirizzo nel campo sopra e clicca <strong>Importa Feed</strong>.
          </li>
        </ol>
      )}
    </div>
  );
};

/** Sottoscrizione a un feed iCal remoto (Google Calendar, webcal). */
export const ImportUrlForm: React.FC<ManageFormProps> = ({ submit, isBusy, invalid }) => {
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [color, setColor] = useState('#4285f4');

  const changeUrl = (value: string) => {
    setUrl(value);
    if (!name && value.includes('google.com')) setName('Google Calendar');
  };

  const subscribe = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return invalid("Inserisci l'URL del feed iCal.");
    submit(async () => {
      const res = await calendarApi.importIcsUrl({ url: url.trim(), name: name.trim() || undefined, color });
      return `Feed importato con successo! Sincronizzati ${res.synced_count || 0} eventi.`;
    }, "Errore durante l'importazione del feed.");
  };

  return (
    <form onSubmit={subscribe} className="space-y-4">
      <div>
        <label className={labelClass}>
          URL Feed iCalendar (Google Calendar o Webcal) <span className="text-rose-400">*</span>
        </label>
        <input
          type="url"
          value={url}
          onChange={(e) => changeUrl(e.target.value)}
          placeholder="https://calendar.google.com/calendar/ical/.../basic.ics oppure webcal://..."
          required
          className={`${inputClass} py-2.5 font-mono`}
        />
      </div>

      <GoogleHelp />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>Nome Assegnato</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Google Personale" className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Colore</label>
          <ColorPicker value={color} onChange={setColor} colors={PRESET_COLORS.slice(0, 5)} />
        </div>
      </div>

      <div className="pt-2 flex justify-end">
        <button type="submit" disabled={isBusy} className={submitClass}>
          <Globe size={14} />
          <span>{isBusy ? 'Sottoscrizione in corso...' : 'Sottoscrivi e Sincronizza'}</span>
        </button>
      </div>
    </form>
  );
};
