import React from 'react';
import { Layers, Loader2 } from 'lucide-react';
import type { ConsolidationResult, ConsolidationStatus } from '../../api/memory';
import { formatDateTime } from '../../utils/metricsFormat';

const summary = (r: ConsolidationResult) =>
  r.error
    ? r.error
    : `${r.messages ?? 0} messaggi: ${r.added ?? 0} fatti nuovi, ${r.updated ?? 0} aggiornati, ${r.invalidated ?? 0} non più validi, ${r.deduplicated ?? 0} doppioni`;

/** I fatti nascono dal consolidamento dei messaggi: quanti ne mancano, l'esito dell'ultimo e il pulsante per farlo ora. */
export const ConsolidationBar: React.FC<{ status: ConsolidationStatus; onStart: () => void }> = ({ status, onStart }) => (
  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-panel/60 px-3 py-2" aria-label="Consolidamento della memoria">
    <div className="text-[11px] text-fg-muted space-y-0.5 min-w-0">
      <p>
        {status.pending.messages > 0 ? (
          <>
            <span className="font-semibold text-fg">{status.pending.messages}</span> messaggi in {status.pending.threads} conversazioni da consolidare nei fatti
          </>
        ) : (
          'Tutte le conversazioni sono consolidate nei fatti'
        )}
        {status.schedule_hour >= 0 ? ` · ogni giorno alle ${status.schedule_hour}:00 (ora del server)` : ' · solo su richiesta'}
      </p>
      {status.last_run && status.last_result && (
        <p className={status.last_result.error ? 'text-rose-400' : ''}>
          Ultimo: {formatDateTime(status.last_run)} · {summary(status.last_result)}
        </p>
      )}
    </div>
    <button
      onClick={onStart}
      disabled={status.running || status.pending.messages === 0}
      className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-accent text-white text-xs font-semibold disabled:opacity-40 cursor-pointer shrink-0"
    >
      {status.running ? <Loader2 size={12} className="animate-spin" /> : <Layers size={12} />}
      {status.running ? 'Consolidamento…' : 'Consolida ora'}
    </button>
  </div>
);
