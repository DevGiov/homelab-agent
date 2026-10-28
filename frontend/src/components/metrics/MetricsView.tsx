import React, { useState } from 'react';
import { Activity, Loader2, Menu, RefreshCw } from 'lucide-react';
import { METRICS_WINDOWS, useMetrics } from '../../hooks/useMetrics';
import { formatDuration, formatRate } from '../../utils/metricsFormat';
import { HealthPanel } from './HealthPanel';
import { ModelsTable, ToolsTable, TurnsTable } from './MetricsTables';
import { StatTiles } from './StatTiles';
import { TimeChart } from './TimeChart';

const TURN_SERIES = [
  { key: 'ok', label: 'Completati', color: 'var(--chart-1)' },
  { key: 'stopped', label: 'Interrotti', color: 'var(--chart-warning)' },
  { key: 'error', label: 'In errore', color: 'var(--chart-critical)' },
];

const count = (v: number) => String(Math.round(v));

/** Osservabilità dell'agente: turni di chat e automazioni, velocità dei modelli, tool e salute dei servizi. */
export const MetricsView: React.FC<{ onOpenMobileSidebar?: () => void }> = ({ onOpenMobileSidebar }) => {
  const [range, setRange] = useState(METRICS_WINDOWS[1]);
  const { summary, series, turns, error, isLoading, reload } = useMetrics(range);

  const points = series?.points ?? [];
  const turnPoints = points.map((p) => ({
    start: p.start,
    values: { ok: p.turns - p.errors - p.stopped, stopped: p.stopped, error: p.errors },
  }));
  const durationPoints = points.map((p) => ({ start: p.start, values: { p50: p.p50_ms } }));
  const speedPoints = points.map((p) => ({ start: p.start, values: { gen: p.gen_tok_s } }));

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-background">
      <div className="p-2.5 sm:p-3.5 border-b border-border bg-panel-header/40 backdrop-blur-md flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          {onOpenMobileSidebar && (
            <button
              onClick={onOpenMobileSidebar}
              className="md:hidden p-1.5 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition shrink-0 cursor-pointer"
              title="Apri menu principale"
            >
              <Menu size={20} />
            </button>
          )}
          <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shadow-sm shrink-0">
            <Activity size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="font-semibold text-xs sm:text-sm text-fg leading-tight truncate">Metriche</h1>
            <p className="text-[10px] sm:text-[11px] text-fg-muted mt-0.5 hidden md:block">
              Turni, velocità dei modelli, tool e salute dei servizi
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-0.5 p-0.5 rounded-xl border border-border bg-panel/60" role="group" aria-label="Finestra temporale">
            {METRICS_WINDOWS.map((w) => (
              <button
                key={w.id}
                onClick={() => setRange(w)}
                aria-pressed={w.id === range.id}
                className={`px-2 py-1 rounded-lg text-[11px] font-medium transition cursor-pointer whitespace-nowrap ${
                  w.id === range.id ? 'bg-accent text-accent-contrast shadow-sm' : 'text-fg-muted hover:text-fg hover:bg-panel-hover'
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
          <button
            onClick={reload}
            disabled={isLoading}
            className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover shrink-0 cursor-pointer"
            title="Aggiorna"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-3">
        {error && <div className="p-2 rounded-lg text-[11px] border bg-rose-950/40 border-rose-800/60 text-rose-300">{error}</div>}

        {!summary || !series ? (
          isLoading && (
            <div className="flex items-center justify-center gap-2 py-16 text-xs text-fg-muted">
              <Loader2 size={14} className="animate-spin text-accent" /> Caricamento metriche…
            </div>
          )
        ) : (
          <>
            <StatTiles summary={summary} />
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
              <TimeChart title="Turni per intervallo" kind="columns" series={TURN_SERIES} points={turnPoints} windowHours={range.hours} formatValue={count} />
              <TimeChart
                title="Durata mediana del turno"
                kind="line"
                series={[{ key: 'p50', label: 'Durata mediana', color: 'var(--chart-1)' }]}
                points={durationPoints}
                windowHours={range.hours}
                formatValue={formatDuration}
              />
              <TimeChart
                title="Velocità di generazione"
                kind="line"
                series={[{ key: 'gen', label: 'Generazione', color: 'var(--chart-1)' }]}
                points={speedPoints}
                windowHours={range.hours}
                formatValue={(v) => formatRate(v).replace(' tok/s', '')}
              />
            </div>
            <HealthPanel services={summary.health} history={series.health} points={points} />
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <ModelsTable models={summary.models} />
              <ToolsTable tools={summary.tools} />
            </div>
            <TurnsTable turns={turns} />
          </>
        )}
      </div>
    </div>
  );
};
