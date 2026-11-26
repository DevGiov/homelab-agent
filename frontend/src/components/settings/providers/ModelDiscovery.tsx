import React, { useId, useState } from 'react';
import { Check, Eye, Loader2, Search } from 'lucide-react';
import { discoverModels, type DiscoveredModel, type ProviderKind, type ProviderPatch } from '../../../api/providers';
import { providerErrorMessage } from '../../../utils/providerErrors';
import { inputClass } from './providerStyles';

type Scope = NonNullable<DiscoveredModel['scope']> | 'none' | 'extra';

const SCOPE_HEADINGS: Record<Scope, string> = {
  region: 'Solo questa regione',
  geo: 'Area geografica (profilo tra regioni)',
  global: 'Globale',
  none: 'Modelli',
  extra: 'Già configurati, non trovati dalla ricerca',
};
const SCOPE_NOTES: Partial<Record<Scope, string>> = {
  global: 'Questi profili possono instradare la richiesta in qualunque regione AWS.',
};
const SCOPE_ORDER: Scope[] = ['extra', 'region', 'geo', 'global', 'none'];

interface Props {
  provider: string;
  kind: ProviderKind;
  /** Le modifiche non ancora salvate, da provare insieme alla ricerca; `undefined` se non ce ne sono. */
  getDraft: () => ProviderPatch | undefined;
  /** I modelli dell'elenco adesso (quello della bozza, se è stato modificato). */
  currentModels: string[];
  /** Mette i modelli scelti nella bozza del campo: il salvataggio resta quello normale della scheda. */
  onUse: (ids: string[]) => void;
  disabled?: boolean;
}

/** «Cerca modelli»: chiede al provider cosa offre e lascia scegliere. Sono candidati: non si salva nulla da qui. */
export const ModelDiscovery: React.FC<Props> = ({ provider, kind, getDraft, currentModels, onUse, disabled }) => {
  const baseId = useId();
  const [searching, setSearching] = useState(false);
  const [found, setFound] = useState<DiscoveredModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');

  const search = async () => {
    setSearching(true);
    setError(null);
    setApplied(false);
    setFound(null);
    try {
      const result = await discoverModels(provider, getDraft());
      if (result.error) {
        setError(result.error);
      } else {
        setFound(result.models);
        setChecked(new Set([...result.models.filter((m) => m.configured).map((m) => m.id), ...currentModels]));
        setFilter('');
      }
    } catch (err) {
      setError(providerErrorMessage(err, 'Ricerca non riuscita'));
    } finally {
      setSearching(false);
    }
  };

  const toggle = (id: string) =>
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const useSelected = () => {
    if (!found) return;
    // Un id già nell'elenco ma assente dai risultati resta scelto: la ricerca offre candidati, non l'elenco intero
    const known = new Set(found.map((m) => m.id));
    const extra = currentModels.filter((id) => !known.has(id));
    onUse([...extra, ...found.map((m) => m.id)].filter((id) => checked.has(id)));
    setFound(null);
    setApplied(true);
  };

  const rows: Array<DiscoveredModel & { group: Scope }> = [];
  if (found) {
    const known = new Set(found.map((m) => m.id));
    for (const id of currentModels) {
      if (!known.has(id)) rows.push({ id, name: id, vendor: null, kind: 'model', scope: null, vision: false, configured: true, group: 'extra' });
    }
    for (const m of found) rows.push({ ...m, group: m.scope ?? 'none' });
  }
  const needle = filter.trim().toLowerCase();
  const visible = rows.filter((m) => !needle || [m.id, m.name, m.vendor ?? ''].some((text) => text.toLowerCase().includes(needle)));
  const groups = SCOPE_ORDER.map((scope) => ({ scope, items: visible.filter((m) => m.group === scope) })).filter((g) => g.items.length > 0);
  const grouped = rows.some((m) => m.group !== 'none');

  return (
    <div className="stack-y-2" data-testid="model-discovery">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={search}
          disabled={searching || disabled}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-fg-muted hover:text-fg text-xs cursor-pointer disabled:opacity-50"
        >
          {searching ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <Search size={12} aria-hidden="true" />}
          Cerca modelli
        </button>
        {applied && (
          <span role="status" className="text-xs text-emerald-300">
            Elenco dei modelli aggiornato: premi Salva per applicarlo.
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-xs text-rose-300">
          Ricerca non riuscita: {error}
        </p>
      )}
      {found && found.length === 0 && <p className="text-xs text-fg-muted">Nessun modello trovato.</p>}
      {found && found.length > 0 && (
        <div className="stack-y-2 rounded-lg border border-border p-2.5">
          <label htmlFor={`${baseId}-filter`} className="block text-xs font-medium text-fg-muted">
            Filtra i modelli
          </label>
          <input
            id={`${baseId}-filter`}
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="nome, id o fornitore"
            className={inputClass}
          />
          <div role="group" aria-label="Modelli trovati" className="stack-y-2 max-h-72 overflow-y-auto">
            {groups.length === 0 && <p className="text-xs text-fg-muted">Nessun modello corrisponde al filtro.</p>}
            {groups.map(({ scope, items }) => (
              <div key={scope} role="group" aria-labelledby={`${baseId}-${scope}`} className="stack-y-1">
                {(grouped || scope === 'extra') && (
                  <h5 id={`${baseId}-${scope}`} className="text-xs font-semibold text-fg">
                    {SCOPE_HEADINGS[scope]}
                  </h5>
                )}
                {SCOPE_NOTES[scope] && <p className="text-xs text-amber-300">{SCOPE_NOTES[scope]}</p>}
                <ul className="stack-y-0.5">
                  {items.map((m) => (
                    <li key={m.id}>
                      <label className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-fg cursor-pointer">
                        <input type="checkbox" checked={checked.has(m.id)} onChange={() => toggle(m.id)} aria-label={m.id} className="accent-accent" />
                        <span className="font-mono">{m.id}</span>
                        {m.name !== m.id && <span className="text-fg-muted">{m.name}</span>}
                        {m.vendor && <span className="text-fg-muted">· {m.vendor}</span>}
                        {m.vision && (
                          <span className="px-1.5 py-0.5 rounded-sm text-xs font-medium border flex items-center gap-1 bg-sky-500/10 text-sky-300 border-sky-500/25">
                            <Eye size={9} aria-hidden="true" />
                            visione
                          </span>
                        )}
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={useSelected}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-accent-contrast text-xs font-semibold cursor-pointer"
            >
              <Check size={12} aria-hidden="true" /> Usa i selezionati
            </button>
            <span className="text-xs text-fg-muted">{checked.size} selezionati</span>
          </div>
          <p className="text-xs text-fg-muted">
            {kind === 'bedrock'
              ? "Non tutti i modelli rispondono all'API compatibile OpenAI di Bedrock: dopo il salvataggio prova il modello in chat."
              : "Non tutti i modelli rispondono all'API di chat del servizio: dopo il salvataggio prova il modello in chat."}
          </p>
        </div>
      )}
    </div>
  );
};
