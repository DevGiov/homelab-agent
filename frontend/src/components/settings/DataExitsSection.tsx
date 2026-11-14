import React, { useCallback, useEffect, useState } from 'react';
import { ArrowUpRight, Loader2, RefreshCw } from 'lucide-react';
import { getDataExitSummary, type DataExitSummary } from '../../api/security';
import { formatDateTime } from '../../utils/metricsFormat';
import { describeDestination, isLevel, LABEL_NAMES } from '../../utils/sensitivity';
import { SensitivityChip } from '../sensitivity/SensitivityChip';

const PERIODS = [
  { hours: 24, label: 'Ultime 24 ore' },
  { hours: 168, label: 'Ultimi 7 giorni' },
  { hours: 720, label: 'Ultimi 30 giorni' },
];

/** Etichette abbassate a mano (backend: audit_log.LABEL_TARGETS): non sono uscite, restano fuori dal riepilogo. */
const LOWERED_TARGETS: Record<string, string> = {
  thread: 'conversazione',
  fact: 'fatto',
  kb: 'documento',
};

const FLOW_TEXT: Record<string, string> = {
  ask: 'conferma chiesta',
  deny: 'bloccata',
  lowered: 'livello abbassato',
};

/** Quanto spesso il controllo delle uscite di dati interviene: per destinazione, e le ultime richieste di conferma. */
export const DataExitsSection: React.FC = () => {
  const [hours, setHours] = useState(168);
  const [data, setData] = useState<DataExitSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getDataExitSummary(hours));
    } catch (err) {
      console.warn('Riepilogo delle uscite di dati non caricato:', err);
      setError('Riepilogo non disponibile.');
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    load();
  }, [load]);

  const destinations = (data?.destinations ?? []).filter((d) => !(d.destination in LOWERED_TARGETS));
  const totals = destinations.reduce(
    (acc, d) => ({ allow: acc.allow + d.allow, ask: acc.ask + d.ask, approved: acc.approved + d.approved, deny: acc.deny + d.deny }),
    { allow: 0, ask: 0, approved: 0, deny: 0 }
  );

  return (
    <div className="bg-panel/70 border border-border rounded-xl p-3.5 space-y-2.5" data-testid="data-exits">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ArrowUpRight size={15} className="text-amber-400" />
          <h4 className="text-xs font-semibold text-fg">Uscite di dati</h4>
        </div>
        <div className="flex items-center gap-1.5">
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="bg-bg/60 border border-border rounded-md px-1.5 py-0.5 text-[11px] text-fg focus:outline-none cursor-pointer"
            aria-label="Periodo"
          >
            {PERIODS.map((p) => (
              <option key={p.hours} value={p.hours} className="bg-panel text-fg">
                {p.label}
              </option>
            ))}
          </select>
          <button onClick={load} disabled={loading} className="p-1 text-fg-muted hover:text-fg transition rounded cursor-pointer" title="Aggiorna">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>
      <p className="text-[11px] text-fg-muted leading-relaxed">
        Ogni chiamata che porta dati fuori dal backend passa da un controllo: <strong>consentita</strong> se la destinazione può
        ricevere quei dati, altrimenti l'agente <strong>chiede conferma</strong> mostrando cosa invierebbe. Tante conferme sui
        dati pubblici o interni dicono che le etichette sono troppo strette.
      </p>

      {error && <p className="text-[11px] text-rose-300">{error}</p>}
      {loading && !data ? (
        <div className="flex items-center justify-center p-3 text-xs text-fg-muted">
          <Loader2 size={14} className="animate-spin mr-2" /> Caricamento…
        </div>
      ) : destinations.length === 0 ? (
        <p className="text-[11px] text-fg-muted italic">Nessuna uscita di dati nel periodo.</p>
      ) : (
        <>
          <div className="text-[11px] text-fg">
            {totals.allow} consentite · <span className="text-amber-300">{totals.ask} conferme chieste</span> · {totals.approved} autorizzate dopo
            una conferma · {totals.deny} bloccate
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-fg-muted text-left">
                  <th className="font-medium py-1 pr-2">Destinazione</th>
                  <th className="font-medium py-1 px-2 text-right">Consentite</th>
                  <th className="font-medium py-1 px-2 text-right">Conferme</th>
                  <th className="font-medium py-1 px-2 text-right">Autorizzate</th>
                  <th className="font-medium py-1 pl-2 text-right">Bloccate</th>
                </tr>
              </thead>
              <tbody>
                {destinations.map((d) => (
                  <tr key={d.destination} className="border-t border-border/50">
                    <td className="py-1 pr-2 text-fg" title={d.destination}>
                      {describeDestination(d.destination)}
                    </td>
                    <td className="py-1 px-2 text-right tabular-nums">{d.allow}</td>
                    <td className="py-1 px-2 text-right tabular-nums text-amber-300">{d.ask}</td>
                    <td className="py-1 px-2 text-right tabular-nums">{d.approved}</td>
                    <td className="py-1 pl-2 text-right tabular-nums">{d.deny}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {(data?.recent.length ?? 0) > 0 && (
        <div className="space-y-1 pt-1 border-t border-border/60">
          <div className="text-[11px] font-semibold text-fg-muted uppercase tracking-wider">Ultime richieste</div>
          {data!.recent.map((e, i) => (
            <div key={`${e.timestamp}-${i}`} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]">
              <span className="text-fg-muted tabular-nums">{formatDateTime(e.timestamp)}</span>
              <span className="text-fg">{FLOW_TEXT[e.flow] ?? e.flow}</span>
              {e.flow === 'lowered' ? (
                <span className="text-fg-muted">{LOWERED_TARGETS[e.destination] ?? e.destination}</span>
              ) : (
                <span className="text-fg-muted">{describeDestination(e.destination)}</span>
              )}
              {isLevel(e.label) && (e.flow === 'lowered' ? <span>a {LABEL_NAMES[e.label].toLowerCase()}</span> : <SensitivityChip tag={{ label: e.label }} always />)}
              {e.summary && <span className="font-mono text-fg-muted truncate max-w-[20rem]" title={e.summary}>{e.summary}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
