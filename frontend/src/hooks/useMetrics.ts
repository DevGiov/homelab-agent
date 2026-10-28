import { useCallback, useEffect, useState } from 'react';
import {
  getMetricsSummary,
  getMetricsTimeseries,
  listTurns,
  type MetricsSummary,
  type MetricsTimeseries,
  type TurnRecord,
} from '../api/metrics';
import { formatApiError } from '../utils/error';

export interface MetricsWindow {
  id: string;
  label: string;
  hours: number;
  /** Intervalli dei grafici: 5 min sull'ora, 30 min sul giorno, 3 h sulla settimana, 12 h sul mese. */
  buckets: number;
}

export const METRICS_WINDOWS: MetricsWindow[] = [
  { id: '1h', label: '1 ora', hours: 1, buckets: 12 },
  { id: '24h', label: '24 ore', hours: 24, buckets: 48 },
  { id: '7d', label: '7 giorni', hours: 24 * 7, buckets: 56 },
  { id: '30d', label: '30 giorni', hours: 24 * 30, buckets: 60 },
];

const REFRESH_MS = 60_000;
const RECENT_TURNS = 30;

/** Riepilogo, serie temporali e ultimi turni della finestra scelta, aggiornati ogni minuto. */
export function useMetrics(range: MetricsWindow) {
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [series, setSeries] = useState<MetricsTimeseries | null>(null);
  const [turns, setTurns] = useState<TurnRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [s, ts, recent] = await Promise.all([
        getMetricsSummary(range.hours),
        getMetricsTimeseries(range.hours, range.buckets),
        listTurns(RECENT_TURNS),
      ]);
      setSummary(s);
      setSeries(ts);
      setTurns(recent);
      setError(null);
    } catch (err) {
      setError(`Metriche non caricate: ${formatApiError(err)}`);
    } finally {
      setIsLoading(false);
    }
  }, [range.hours, range.buckets]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  return { summary, series, turns, error, isLoading, reload: load };
}
