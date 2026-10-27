import React from 'react';
import { Calendar, Clock } from 'lucide-react';
import { DAY_NAMES, describeSchedule, HOURLY_INTERVALS, toCron, type Frequency, type Schedule } from '../../../utils/cronSchedule';
import { Toggle } from './Toggle';

const FREQUENCIES: Array<[Frequency, string]> = [
  ['daily', 'Giornaliero'],
  ['weekly', 'Settimanale'],
  ['hourly', 'Intervallo Orario'],
  ['custom', 'Cron Avanzato'],
];
// Lunedì per primo, domenica in fondo
const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0];

const inputClass =
  'w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500';
const clamp = (value: number, max: number) => Math.max(0, Math.min(max, value));

interface CronScheduleSectionProps {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  schedule: Schedule;
  onChange: (patch: Partial<Schedule>) => void;
  timezone: string;
}

export const CronScheduleSection: React.FC<CronScheduleSectionProps> = ({ enabled, onEnabledChange, schedule, onChange, timezone }) => {
  const { frequency } = schedule;
  const minuteInput = (
    <div className="flex-1">
      <label className="block text-xs text-slate-400 mb-1">{frequency === 'hourly' ? 'Al minuto' : 'Minuto (0-59)'}</label>
      <input
        type="number"
        min={0}
        max={59}
        value={schedule.minute}
        onChange={(e) => onChange({ minute: clamp(Number(e.target.value), 59) })}
        className={`${inputClass} font-mono`}
      />
    </div>
  );

  return (
    <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800/80 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Clock className="w-4 h-4 text-emerald-400" />
          <span className="font-medium text-slate-200">Schedulazione Temporale (Cron)</span>
        </div>
        <Toggle checked={enabled} onChange={onEnabledChange} color="peer-checked:bg-emerald-500" />
      </div>

      {enabled && (
        <div className="space-y-4 pt-2 border-t border-slate-800/60">
          <div className="flex gap-2">
            {FREQUENCIES.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => onChange({ frequency: value })}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                  frequency === value
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm'
                    : 'bg-slate-800/50 text-slate-400 hover:text-slate-300 border border-slate-700/40'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {(frequency === 'daily' || frequency === 'weekly') && (
            <div className="grid grid-cols-2 gap-4">
              {frequency === 'weekly' && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Giorno della settimana</label>
                  <select value={schedule.dayOfWeek} onChange={(e) => onChange({ dayOfWeek: Number(e.target.value) })} className={inputClass}>
                    {WEEK_ORDER.map((day) => (
                      <option key={day} value={day}>
                        {DAY_NAMES[day]}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div className={frequency === 'daily' ? 'col-span-2 flex gap-4' : 'flex gap-4'}>
                <div className="flex-1">
                  <label className="block text-xs text-slate-400 mb-1">Ora (0-23)</label>
                  <input
                    type="number"
                    min={0}
                    max={23}
                    value={schedule.hour}
                    onChange={(e) => onChange({ hour: clamp(Number(e.target.value), 23) })}
                    className={`${inputClass} font-mono`}
                  />
                </div>
                {minuteInput}
              </div>
            </div>
          )}

          {frequency === 'hourly' && (
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="block text-xs text-slate-400 mb-1">Ogni quante ore</label>
                <select value={schedule.hourlyInterval} onChange={(e) => onChange({ hourlyInterval: Number(e.target.value) })} className={inputClass}>
                  {HOURLY_INTERVALS.map((hours) => (
                    <option key={hours} value={hours}>
                      Ogni {hours} {hours === 1 ? 'ora' : 'ore'}
                    </option>
                  ))}
                </select>
              </div>
              {minuteInput}
            </div>
          )}

          {frequency === 'custom' && (
            <div>
              <label className="block text-xs text-slate-400 mb-1">Espressione Cron standard (5 campi: m h dom mon dow)</label>
              <input
                type="text"
                value={schedule.custom}
                onChange={(e) => onChange({ custom: e.target.value })}
                placeholder="es. 0 8 * * 1-5"
                className={`${inputClass} font-mono`}
              />
            </div>
          )}

          <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 text-emerald-300">
              <Calendar className="w-4 h-4 shrink-0" />
              <span>{describeSchedule(schedule, timezone)}</span>
            </div>
            <span className="font-mono text-[11px] bg-slate-950/80 px-2 py-0.5 rounded text-emerald-400 border border-emerald-500/30">
              {toCron(schedule)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
