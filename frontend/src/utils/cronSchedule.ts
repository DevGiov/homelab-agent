// Pianificazione dei trigger: conversione tra espressione cron e i controlli guidati della UI.

export type Frequency = 'daily' | 'weekly' | 'hourly' | 'custom';

export interface Schedule {
  frequency: Frequency;
  hour: number;
  minute: number;
  /** 0 = domenica … 6 = sabato, come nel campo cron. */
  dayOfWeek: number;
  hourlyInterval: number;
  /** Espressione usata in modalità `custom`. */
  custom: string;
}

export const HOURLY_INTERVALS = [1, 2, 3, 4, 6, 12];
export const DAY_NAMES = ['Domenica', 'Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato'];

const DEFAULT_SCHEDULE: Schedule = { frequency: 'daily', hour: 8, minute: 0, dayOfWeek: 1, hourlyInterval: 2, custom: '0 8 * * *' };

const intIn = (value: string, min: number, max: number) => /^\d+$/.test(value) && Number(value) >= min && Number(value) <= max;

/** Riconosce le forme gestite dai controlli guidati; tutto il resto (liste, intervalli, step) resta cron avanzato. */
export function parseCron(expression?: string | null): Schedule {
  if (!expression?.trim()) return DEFAULT_SCHEDULE;
  const expr = expression.trim();
  const custom = { ...DEFAULT_SCHEDULE, frequency: 'custom' as const, custom: expr };
  const parts = expr.split(/\s+/);
  if (parts.length !== 5) return custom;

  const [m, h, dom, mon, dow] = parts;
  if (dom !== '*' || mon !== '*' || !intIn(m, 0, 59)) return custom;
  const minute = Number(m);

  if (intIn(h, 0, 23)) {
    if (dow === '*') return { ...DEFAULT_SCHEDULE, frequency: 'daily', hour: Number(h), minute, custom: expr };
    if (intIn(dow, 0, 7)) return { ...DEFAULT_SCHEDULE, frequency: 'weekly', hour: Number(h), minute, dayOfWeek: Number(dow) % 7, custom: expr };
    return custom;
  }
  const interval = /^\*\/(\d+)$/.exec(h)?.[1];
  if (interval && dow === '*' && HOURLY_INTERVALS.includes(Number(interval))) {
    return { ...DEFAULT_SCHEDULE, frequency: 'hourly', minute, hourlyInterval: Number(interval), custom: expr };
  }
  return custom;
}

export function toCron(s: Schedule): string {
  switch (s.frequency) {
    case 'daily':
      return `${s.minute} ${s.hour} * * *`;
    case 'weekly':
      return `${s.minute} ${s.hour} * * ${s.dayOfWeek}`;
    case 'hourly':
      return `${s.minute} */${s.hourlyInterval} * * *`;
    default:
      return s.custom.trim();
  }
}

const pad = (n: number) => String(n).padStart(2, '0');

export function describeSchedule(s: Schedule, timezone: string): string {
  const time = `${pad(s.hour)}:${pad(s.minute)}`;
  switch (s.frequency) {
    case 'daily':
      return `Ogni giorno alle ore ${time} (fuso ${timezone}).`;
    case 'weekly':
      return `Ogni ${DAY_NAMES[s.dayOfWeek]} alle ore ${time} (fuso ${timezone}).`;
    case 'hourly':
      return `Ogni ${s.hourlyInterval} ore al minuto ${pad(s.minute)}.`;
    default:
      return `Espressione cron personalizzata: ${s.custom}`;
  }
}

export interface Trigger {
  id: string;
  type: string;
  cron_expression?: string;
  timezone?: string;
  webhook_token?: string;
  enabled?: boolean;
  [key: string]: unknown;
}

/**
 * Trigger da salvare: cron e webhook come configurati nel modale, gli altri tipi (manuale, eventi)
 * invariati. Senza alcun trigger resta l'avvio manuale.
 */
export function buildTriggers(
  existing: Trigger[],
  cron: { enabled: boolean; expression: string; timezone: string },
  webhook: { enabled: boolean; token: string }
): Trigger[] {
  const find = (type: string) => existing.find((t) => t.type === type);
  const triggers: Trigger[] = [];
  if (cron.enabled) {
    triggers.push({ id: find('cron')?.id || 'trg_cron_main', type: 'cron', cron_expression: cron.expression, timezone: cron.timezone, enabled: true });
  }
  if (webhook.enabled) {
    triggers.push({ id: find('webhook')?.id || 'trg_webhook_main', type: 'webhook', webhook_token: webhook.token || undefined, enabled: true });
  }
  triggers.push(...existing.filter((t) => t.type !== 'cron' && t.type !== 'webhook'));
  return triggers.length > 0 ? triggers : [{ id: 'trg_manual', type: 'manual', enabled: true }];
}
