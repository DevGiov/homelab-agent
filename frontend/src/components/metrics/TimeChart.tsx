import React, { useLayoutEffect, useRef, useState } from 'react';
import { formatTick, niceScale } from '../../utils/metricsFormat';

export interface ChartSeries {
  key: string;
  label: string;
  /** Colore del segno (variabile CSS); il testo resta nei colori del tema. */
  color: string;
}

export interface ChartPoint {
  start: string;
  values: Record<string, number | null>;
}

interface TimeChartProps {
  title: string;
  /** `columns`: serie impilate; `line`: una linea per serie, null interrompe il tratto. */
  kind: 'columns' | 'line';
  series: ChartSeries[];
  points: ChartPoint[];
  windowHours: number;
  formatValue: (value: number) => string;
  height?: number;
}

const PAD = { top: 8, right: 8, bottom: 20, left: 44 };
const MAX_COLUMN = 24;
const GAP = 2;

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(600);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(200, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** Colonna con l'estremo dati arrotondato e la base squadrata sulla linea di base. */
function columnPath(x: number, y: number, w: number, h: number, rounded: boolean): string {
  const r = rounded ? Math.min(4, w / 2, h) : 0;
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Grafico temporale a intervalli uguali, con tooltip per intervallo al passaggio del puntatore. */
export const TimeChart: React.FC<TimeChartProps> = ({ title, kind, series, points, windowHours, formatValue, height = 150 }) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const band = plotW / Math.max(1, points.length);
  const total = (p: ChartPoint) =>
    kind === 'columns'
      ? series.reduce((sum, s) => sum + (p.values[s.key] ?? 0), 0)
      : Math.max(0, ...series.map((s) => p.values[s.key] ?? 0));
  const ticks = niceScale(Math.max(0, ...points.map(total)));
  const top = ticks[ticks.length - 1];
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH;
  const hasData = points.some((p) => series.some((s) => p.values[s.key] != null && p.values[s.key] !== 0));

  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 70))));
  const columnW = Math.min(MAX_COLUMN, Math.max(1, band - GAP));

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const index = Math.floor((e.clientX - rect.left - PAD.left) / band);
    setHover(index >= 0 && index < points.length ? index : null);
  };

  const hovered = hover != null ? points[hover] : null;
  const tooltipLeft = hover != null ? Math.min(Math.max(PAD.left + band * (hover + 0.5), 80), width - 80) : 0;

  return (
    <figure className="rounded-2xl border border-border bg-panel/60 p-3 min-w-0">
      <figcaption className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2">
        <span className="text-xs font-semibold text-fg">{title}</span>
        {series.length > 1 && (
          <span className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-muted">
            {series.map((s) => (
              <span key={s.key} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
                {s.label}
              </span>
            ))}
          </span>
        )}
      </figcaption>
      <div ref={ref} className="relative">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={title}
          className="block touch-none"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" strokeWidth={1} />
              <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-fg-muted text-[10px] tabular-nums">
                {formatValue(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            i % labelEvery === 0 ? (
              <text key={p.start} x={PAD.left + band * (i + 0.5)} y={height - 4} textAnchor="middle" className="fill-fg-muted text-[10px] tabular-nums">
                {formatTick(p.start, windowHours)}
              </text>
            ) : null,
          )}

          {hover != null && (
            <rect x={PAD.left + band * hover} y={PAD.top} width={band} height={plotH} fill="var(--chart-hover)" />
          )}

          {kind === 'columns'
            ? points.map((p, i) => {
                let base = y(0);
                const visible = series.filter((s) => (p.values[s.key] ?? 0) > 0);
                return visible.map((s, j) => {
                  const h = y(0) - y(p.values[s.key] ?? 0);
                  // Spazio di 2px tra i segmenti impilati
                  const segment = Math.max(0, h - (j > 0 ? GAP : 0));
                  const segmentTop = base - h;
                  base = segmentTop;
                  return (
                    <path
                      key={s.key}
                      d={columnPath(PAD.left + band * i + (band - columnW) / 2, segmentTop, columnW, segment, j === visible.length - 1)}
                      fill={s.color}
                    />
                  );
                });
              })
            : series.map((s) => {
                const d = points
                  .map((p, i) => {
                    const v = p.values[s.key];
                    if (v == null) return null;
                    const prev = i > 0 ? points[i - 1].values[s.key] : null;
                    return `${prev == null ? 'M' : 'L'}${PAD.left + band * (i + 0.5)},${y(v)}`;
                  })
                  .filter(Boolean)
                  .join('');
                return (
                  <g key={s.key}>
                    <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                    {/* Punti isolati (senza vicini) visibili come marcatori */}
                    {points.map((p, i) => {
                      const v = p.values[s.key];
                      const isolated = v != null && points[i - 1]?.values[s.key] == null && points[i + 1]?.values[s.key] == null;
                      const active = hover === i && v != null;
                      return isolated || active ? (
                        <circle key={p.start} cx={PAD.left + band * (i + 0.5)} cy={y(v)} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={2} />
                      ) : null;
                    })}
                  </g>
                );
              })}
          <line x1={PAD.left} x2={width - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--chart-axis)" strokeWidth={1} />
        </svg>

        {!hasData && (
          <div className="absolute inset-0 flex items-center justify-center text-[11px] text-fg-muted pointer-events-none">
            Nessun dato nella finestra
          </div>
        )}

        {hovered && hasData && (
          <div
            className="absolute top-0 -translate-x-1/2 pointer-events-none rounded-lg border border-border bg-panel px-2 py-1.5 text-[11px] shadow-lg whitespace-nowrap z-10"
            style={{ left: tooltipLeft }}
          >
            <div className="text-fg-muted mb-0.5">{new Date(hovered.start).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</div>
            {series.map((s) => (
              <div key={s.key} className="flex items-center gap-1.5 text-fg">
                <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: s.color }} />
                <span className="text-fg-muted">{s.label}</span>
                <span className="font-semibold tabular-nums ml-auto pl-2">
                  {hovered.values[s.key] == null ? '—' : formatValue(hovered.values[s.key] as number)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
};
