import React, { useEffect, useState } from 'react';
import { Clock, Layers, Loader2 } from 'lucide-react';
import type { ConsolidationResult, ConsolidationSettings, ConsolidationStatus } from '../../api/memory';
import { formatDateTime } from '../../utils/metricsFormat';
import { choiceFromModel, describeModelChoice, modelFromChoice } from '../../utils/modelChoice';
import { ModelChoiceSelect } from '../ModelChoiceSelect';
import { Toggle } from '../Toggle';

const selectClass = 'bg-panel border border-border rounded-lg px-2 py-1 text-xs text-fg focus:border-accent max-w-[14rem]';

const summary = (r: ConsolidationResult) =>
  r.error
    ? r.error
    : `${r.messages ?? 0} messaggi: ${r.added ?? 0} fatti nuovi, ${r.updated ?? 0} aggiornati, ${r.invalidated ?? 0} non più validi, ${r.deduplicated ?? 0} doppioni`;

const schedule = (s: ConsolidationSettings) =>
  s.enabled ? `ogni giorno alle ${s.time} (${s.timezone}) con il ${describeModelChoice(s.model)}` : 'solo su richiesta';

/** Il fuso del browser: l'orario si sceglie nell'ora locale di chi lo imposta. */
const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Rome';

interface ConsolidationBarProps {
  status: ConsolidationStatus;
  /** `model`: la scelta per questa esecuzione (null = default, 'loaded' = il modello caricato). */
  onStart: (model: string | null) => void;
  onSaveSettings: (settings: ConsolidationSettings) => void;
}

/**
 * I fatti nascono dal consolidamento dei messaggi: quanti ne mancano, l'esito dell'ultimo, il pulsante per farlo ora
 * con il modello scelto e la programmazione giornaliera (orario e modello).
 */
export const ConsolidationBar: React.FC<ConsolidationBarProps> = ({ status, onStart, onSaveSettings }) => {
  const saved = status.settings;
  const [runChoice, setRunChoice] = useState(choiceFromModel(saved.model));
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(saved);

  // Dopo un salvataggio la scelta per l'esecuzione manuale riparte da quella programmata
  useEffect(() => setRunChoice(choiceFromModel(saved.model)), [saved.model]);

  const openSettings = () => {
    setDraft(saved);
    setEditing((open) => !open);
  };

  const save = () => {
    onSaveSettings({ ...draft, timezone: browserTimezone() });
    setEditing(false);
  };

  return (
    <div className="rounded-xl border border-border bg-panel/60 px-3 py-2 space-y-2" aria-label="Consolidamento della memoria">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-fg-muted space-y-0.5 min-w-0">
          <p>
            {status.pending.messages > 0 ? (
              <>
                <span className="font-semibold text-fg">{status.pending.messages}</span> messaggi in {status.pending.threads} conversazioni da consolidare nei fatti
              </>
            ) : (
              'Tutte le conversazioni sono consolidate nei fatti'
            )}
            {` · ${schedule(saved)}`}
          </p>
          {status.last_run && status.last_result && (
            <p className={status.last_result.error ? 'text-rose-400' : ''}>
              Ultimo: {formatDateTime(status.last_run)}
              {status.last_result.model ? ` (${status.last_result.model})` : ''} · {summary(status.last_result)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
          <ModelChoiceSelect value={runChoice} onChange={setRunChoice} className={selectClass} aria-label="Modello per consolidare ora" />
          <button
            onClick={() => onStart(modelFromChoice(runChoice))}
            disabled={status.running || status.pending.messages === 0}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-accent text-accent-contrast text-xs font-semibold disabled:opacity-40 cursor-pointer"
          >
            {status.running ? <Loader2 size={12} className="animate-spin" /> : <Layers size={12} />}
            {status.running ? 'Consolidamento…' : 'Consolida ora'}
          </button>
          <button
            onClick={openSettings}
            aria-expanded={editing}
            title="Programmazione del consolidamento"
            className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg cursor-pointer"
          >
            <Clock size={12} />
          </button>
        </div>
      </div>

      {editing && (
        <div className="flex flex-wrap items-center gap-3 border-t border-border/50 pt-2 text-xs text-fg-muted" aria-label="Programmazione del consolidamento">
          <span className="flex items-center gap-1.5">
            <Toggle size="sm" checked={draft.enabled} onChange={(enabled) => setDraft((d) => ({ ...d, enabled }))} title="Consolidamento giornaliero" />
            Ogni giorno
          </span>
          <label className="flex items-center gap-1.5">
            alle
            <input
              type="time"
              value={draft.time}
              disabled={!draft.enabled}
              onChange={(e) => setDraft((d) => ({ ...d, time: e.target.value }))}
              className={`${selectClass} disabled:opacity-40`}
              aria-label="Orario del consolidamento"
            />
          </label>
          <label className="flex items-center gap-1.5">
            con
            <ModelChoiceSelect
              value={choiceFromModel(draft.model)}
              onChange={(choice) => setDraft((d) => ({ ...d, model: modelFromChoice(choice) }))}
              className={selectClass}
              aria-label="Modello del consolidamento programmato"
            />
          </label>
          <button onClick={save} disabled={!draft.time} className="px-2.5 py-1 rounded-lg bg-accent text-accent-contrast text-xs font-semibold disabled:opacity-40 cursor-pointer">
            Salva
          </button>
          <span>Orario nel fuso {browserTimezone()}. Il modello vale anche come scelta iniziale per «Consolida ora».</span>
        </div>
      )}
    </div>
  );
};
