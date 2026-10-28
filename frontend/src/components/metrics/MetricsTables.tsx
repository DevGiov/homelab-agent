import React from 'react';
import type { ModelStats, ToolStats, TurnRecord } from '../../api/metrics';
import { formatCompact, formatDateTime, formatDuration, formatPct, formatRate } from '../../utils/metricsFormat';

interface Column<T> {
  label: string;
  render: (row: T) => React.ReactNode;
  numeric?: boolean;
}

function Table<T>({ title, rows, columns, rowKey, empty }: {
  title: string;
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  empty: string;
}) {
  return (
    <section className="rounded-2xl border border-border bg-panel/60 p-3 min-w-0">
      <h2 className="text-xs font-semibold text-fg mb-2">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-[11px] text-fg-muted py-2">{empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-fg-muted border-b border-border">
                {columns.map((c) => (
                  <th key={c.label} className={`font-medium py-1.5 px-2 whitespace-nowrap ${c.numeric ? 'text-right' : 'text-left'}`}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={rowKey(row)} className="border-b border-border/50 last:border-0 hover:bg-panel-hover/60">
                  {columns.map((c) => (
                    <td key={c.label} className={`py-1.5 px-2 text-fg whitespace-nowrap ${c.numeric ? 'text-right tabular-nums' : ''}`}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const errorsCell = (errors: number) => <span className={errors ? 'text-rose-400 font-semibold' : 'text-fg-muted'}>{errors}</span>;

export const ModelsTable: React.FC<{ models: ModelStats[] }> = ({ models }) => (
  <Table
    title="Modelli"
    rows={models}
    rowKey={(m) => m.model}
    empty="Nessuna chiamata LLM nella finestra."
    columns={[
      { label: 'Modello', render: (m) => <span className="font-medium">{m.model}</span> },
      { label: 'Chiamate', numeric: true, render: (m) => formatCompact(m.calls) },
      { label: 'Errori', numeric: true, render: (m) => errorsCell(m.errors) },
      { label: 'Durata p50', numeric: true, render: (m) => formatDuration(m.p50_ms) },
      { label: 'Generazione', numeric: true, render: (m) => formatRate(m.gen_tok_s) },
      { label: 'Prompt', numeric: true, render: (m) => formatRate(m.prompt_tok_s) },
      { label: 'Cache', numeric: true, render: (m) => formatPct(m.cache_hit_pct) },
    ]}
  />
);

export const ToolsTable: React.FC<{ tools: ToolStats[] }> = ({ tools }) => (
  <Table
    title="Tool più lenti"
    rows={tools}
    rowKey={(t) => t.tool}
    empty="Nessuna chiamata a tool nella finestra."
    columns={[
      { label: 'Tool', render: (t) => <code className="text-[11px]">{t.tool}</code> },
      { label: 'Chiamate', numeric: true, render: (t) => formatCompact(t.calls) },
      { label: 'Errori', numeric: true, render: (t) => errorsCell(t.errors) },
      { label: 'Media', numeric: true, render: (t) => formatDuration(t.avg_ms) },
      { label: 'p95', numeric: true, render: (t) => formatDuration(t.p95_ms) },
    ]}
  />
);

const STATUS: Record<TurnRecord['status'], { label: string; className: string }> = {
  ok: { label: 'ok', className: 'text-emerald-400' },
  error: { label: 'errore', className: 'text-rose-400 font-semibold' },
  stopped: { label: 'interrotto', className: 'text-amber-400' },
};

export const TurnsTable: React.FC<{ turns: TurnRecord[] }> = ({ turns }) => (
  <Table
    title="Ultimi turni"
    rows={turns}
    rowKey={(t) => t.id}
    empty="Nessun turno registrato."
    columns={[
      { label: 'Inizio', render: (t) => <span className="text-fg-muted">{formatDateTime(t.ts)}</span> },
      { label: 'Origine', render: (t) => (t.source === 'chat' ? 'chat' : 'automazione') },
      { label: 'Modalità', render: (t) => <span className="truncate max-w-[12rem] inline-block align-bottom">{t.mode ?? '—'}</span> },
      {
        label: 'Esito',
        render: (t) => (
          <span className={STATUS[t.status].className} title={t.error ?? undefined}>
            {STATUS[t.status].label}
          </span>
        ),
      },
      { label: 'Durata', numeric: true, render: (t) => formatDuration(t.duration_ms) },
      { label: 'LLM', numeric: true, render: (t) => `${t.llm_calls} · ${formatDuration(t.llm_ms)}` },
      { label: 'Token', numeric: true, render: (t) => `${formatCompact(t.prompt_tokens)} → ${formatCompact(t.completion_tokens)}` },
      { label: 'Tool', numeric: true, render: (t) => (t.tool_errors ? <span className="text-rose-400">{`${t.tool_calls} (${t.tool_errors} err.)`}</span> : t.tool_calls) },
      { label: 'Modello', render: (t) => <span className="text-fg-muted">{t.model ?? '—'}</span> },
    ]}
  />
);
