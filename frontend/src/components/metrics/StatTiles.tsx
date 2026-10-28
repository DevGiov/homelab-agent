import React from 'react';
import type { MetricsSummary } from '../../api/metrics';
import { formatCompact, formatDuration, formatPct, formatRate } from '../../utils/metricsFormat';

const Tile: React.FC<{ label: string; value: string; detail: string; alert?: boolean }> = ({ label, value, detail, alert }) => (
  <div className="rounded-2xl border border-border bg-panel/60 px-3 py-2.5 min-w-0">
    <div className="text-[11px] text-fg-muted truncate">{label}</div>
    <div className={`text-xl font-semibold mt-0.5 truncate ${alert ? 'text-rose-400' : 'text-fg'}`}>{value}</div>
    <div className="text-[11px] text-fg-muted mt-0.5 truncate" title={detail}>
      {detail}
    </div>
  </div>
);

/** Riepilogo della finestra: volume e esito dei turni, durata, velocità del modello e cache del prompt. */
export const StatTiles: React.FC<{ summary: MetricsSummary }> = ({ summary }) => {
  const { turns, llm } = summary;
  const errors = turns.by_status.error ?? 0;
  const stopped = turns.by_status.stopped ?? 0;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2">
      <Tile
        label="Turni"
        value={formatCompact(turns.total)}
        detail={`${turns.by_source.chat ?? 0} chat · ${turns.by_source.automation ?? 0} automazioni`}
      />
      <Tile
        label="Turni in errore"
        value={formatCompact(errors)}
        detail={`${turns.total ? formatPct(Math.round((1000 * errors) / turns.total) / 10) : '—'} · ${stopped} interrotti`}
        alert={errors > 0}
      />
      <Tile label="Durata mediana" value={formatDuration(turns.p50_ms)} detail={`p95 ${formatDuration(turns.p95_ms)}`} />
      <Tile label="Generazione" value={formatRate(llm.gen_tok_s)} detail={`prompt ${formatRate(llm.prompt_tok_s)}`} />
      <Tile
        label="Prompt dalla cache"
        value={formatPct(llm.cache_hit_pct)}
        detail={`${formatCompact(llm.cached_tokens)} di ${formatCompact(llm.prompt_tokens)} token`}
      />
      <Tile
        label="Chiamate a tool"
        value={formatCompact(turns.tool_calls)}
        detail={`${turns.tool_errors} in errore · ${formatCompact(llm.calls)} chiamate LLM`}
        alert={turns.tool_errors > 0}
      />
    </div>
  );
};
