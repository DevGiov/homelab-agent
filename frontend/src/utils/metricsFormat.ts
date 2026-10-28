// Formattazione dei valori della dashboard metriche: durate, numeri compatti, percentuali e orari.

/** Durata leggibile: 850 ms, 4,2 s, 3 min 10 s. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toLocaleString('it-IT', { maximumFractionDigits: 1 })} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`;
}

/** Numero compatto da mille in su: 1284 → 1,3K, 2_400_000 → 2,4M. */
export function formatCompact(value: number | null | undefined): string {
  if (value == null) return '—';
  return value.toLocaleString('it-IT', { notation: 'compact', maximumFractionDigits: 1 });
}

export function formatRate(tokS: number | null | undefined): string {
  return tokS == null ? '—' : `${tokS.toLocaleString('it-IT', { maximumFractionDigits: tokS < 100 ? 1 : 0 })} tok/s`;
}

export function formatPct(pct: number | null | undefined): string {
  return pct == null ? '—' : `${pct.toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`;
}

/** Orario dell'asse: solo ora per finestre fino a un giorno, giorno e ora oltre. */
export function formatTick(iso: string, windowHours: number): string {
  const d = new Date(iso);
  if (windowHours <= 24) return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

/** Massimo "pulito" per l'asse y (1, 2, 2,5 o 5 per una potenza di dieci) e i tick a passo regolare. */
export function niceScale(max: number, ticks = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const rough = max / ticks;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude;
  const count = Math.ceil(max / step);
  return Array.from({ length: count + 1 }, (_, i) => Number((i * step).toPrecision(12)));
}
