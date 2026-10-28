import React from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';
import type { HealthPoint, MetricsPoint, ServiceHealth } from '../../api/metrics';
import { formatDateTime, formatDuration, formatPct } from '../../utils/metricsFormat';

const SERVICE_LABELS: Record<string, string> = { llamacpp: 'llama.cpp', letta: 'Letta', searxng: 'SearXNG' };

function serviceLabel(service: string): string {
  return service.startsWith('mcp:') ? `MCP · ${service.slice(4)}` : (SERVICE_LABELS[service] ?? service);
}

function cellColor(point: HealthPoint): string {
  if (point.uptime_pct == null) return 'var(--chart-grid)';
  if (point.uptime_pct >= 100) return 'var(--chart-good)';
  return point.uptime_pct > 0 ? 'var(--chart-warning)' : 'var(--chart-critical)';
}

const LEGEND = [
  { label: 'Raggiungibile', color: 'var(--chart-good)' },
  { label: 'Intermittente', color: 'var(--chart-warning)' },
  { label: 'Non raggiungibile', color: 'var(--chart-critical)' },
  { label: 'Nessun campione', color: 'var(--chart-grid)' },
];

interface HealthPanelProps {
  services: ServiceHealth[];
  history: Record<string, HealthPoint[]>;
  points: MetricsPoint[];
}

/** Stato attuale dei servizi esterni e disponibilità nel tempo, un riquadro per intervallo. */
export const HealthPanel: React.FC<HealthPanelProps> = ({ services, history, points }) => (
  <section className="rounded-2xl border border-border bg-panel/60 p-3">
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2">
      <h2 className="text-xs font-semibold text-fg">Salute dei servizi</h2>
      <span className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-muted">
        {LEGEND.map((l) => (
          <span key={l.label} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: l.color }} />
            {l.label}
          </span>
        ))}
      </span>
    </div>

    {services.length === 0 ? (
      <p className="text-[11px] text-fg-muted py-3">Nessun campione nella finestra: il primo arriva entro un minuto dall'avvio del backend.</p>
    ) : (
      <div className="space-y-2.5">
        {services.map((s) => (
          <div key={s.service} className="grid grid-cols-1 md:grid-cols-[12rem_1fr] gap-x-3 gap-y-1 items-center">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-xs text-fg">
                {s.ok ? <CheckCircle2 size={13} className="text-emerald-400 shrink-0" /> : <XCircle size={13} className="text-rose-400 shrink-0" />}
                <span className="font-medium truncate">{serviceLabel(s.service)}</span>
                <span className={`text-[11px] ${s.ok ? 'text-emerald-400' : 'text-rose-400'}`}>{s.ok ? 'attivo' : 'giù'}</span>
              </div>
              <div className="text-[11px] text-fg-muted truncate" title={s.last_error ?? undefined}>
                {formatPct(s.uptime_pct)} · {formatDuration(s.avg_latency_ms)}
                {!s.ok && s.last_error ? ` · ${s.last_error}` : ''}
              </div>
            </div>
            <div className="flex gap-[2px] h-5" aria-label={`Disponibilità di ${serviceLabel(s.service)} nel tempo`}>
              {(history[s.service] ?? []).map((point, i) => (
                <div
                  key={points[i]?.start ?? i}
                  className="flex-1 rounded-[2px] min-w-[2px]"
                  style={{ backgroundColor: cellColor(point) }}
                  title={`${points[i] ? formatDateTime(points[i].start) : ''} · ${
                    point.uptime_pct == null ? 'nessun campione' : `${formatPct(point.uptime_pct)}, ${formatDuration(point.avg_latency_ms)}`
                  }`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    )}
  </section>
);
