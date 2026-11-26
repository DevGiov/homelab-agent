import React from 'react';
import { useModelCatalog } from '../hooks/useModelCatalog';
import { DEFAULT_CHOICE, LOADED_MODEL, type ModelChoice } from '../utils/modelChoice';

interface ModelChoiceSelectProps {
  /** La coppia (provider, modello); vedi utils/modelChoice. */
  value: ModelChoice;
  onChange: (value: ModelChoice) => void;
  className?: string;
  'aria-label'?: string;
}

// Valori delle opzioni: '' e 'loaded' per le due scelte speciali; una coppia è un array JSON, che non può confondersi con loro
const DEFAULT_KEY = '';
const pairKey = (provider: string, model: string) => JSON.stringify([provider, model]);

const keyOf = (choice: ModelChoice, defaultProvider: string | null): string => {
  if (!choice.model) return choice.provider ? pairKey(choice.provider, '') : DEFAULT_KEY;
  if (choice.model === LOADED_MODEL) return choice.provider ? pairKey(choice.provider, LOADED_MODEL) : LOADED_MODEL;
  // Un modello salvato senza provider (prima dei provider) è un modello del provider predefinito
  const provider = choice.provider ?? defaultProvider;
  return provider ? pairKey(provider, choice.model) : pairKey('', choice.model);
};

const choiceOf = (key: string): ModelChoice => {
  if (key === DEFAULT_KEY) return DEFAULT_CHOICE;
  if (key === LOADED_MODEL) return { provider: null, model: LOADED_MODEL };
  const [provider, model] = JSON.parse(key) as [string, string];
  return { provider, model };
};

/**
 * Selettore del modello per i lavori in background: «Default del server» e «Modello caricato al momento» (entrambi sul
 * provider predefinito, che al momento dell'esecuzione può essere cambiato) e poi i modelli di ogni provider attivo,
 * raggruppati sotto il suo nome come nel selettore della chat. Una scelta salvata che il catalogo non elenca più (provider
 * eliminato o disattivato, modello sparito) resta visibile e selezionata, segnata come non disponibile.
 */
export const ModelChoiceSelect: React.FC<ModelChoiceSelectProps> = ({ value, onChange, className = '', ...rest }) => {
  const { providers, defaultModel, loadedModel } = useModelCatalog();
  const defaultProvider = defaultModel?.provider ?? null;
  const defaultIsCloud = providers.find((p) => p.name === defaultProvider)?.cloud ?? false;
  const key = keyOf(value, defaultProvider);

  // Finché il catalogo non è arrivato nulla si può dire mancante
  const catalogReady = providers.length > 0;
  const known = new Set(providers.flatMap((p) => p.models.map((m) => pairKey(p.name, m.id))));
  const providerNames = new Set(providers.map((p) => p.name));

  // La scelta salvata, se non è né una delle speciali né un modello dell'elenco, compare come voce a sé
  let orphan: { key: string; label: string; inGroup: string | null } | null = null;
  if (key !== DEFAULT_KEY && key !== LOADED_MODEL && !known.has(key) && catalogReady) {
    const provider = value.provider ?? defaultProvider ?? '';
    const what = value.model === LOADED_MODEL ? `Modello caricato su ${provider}` : value.model || `Default di ${provider}`;
    const providerThere = providerNames.has(provider);
    // Il default di un provider o il suo modello caricato (dati scritti a mano via API) valgono finché il provider esiste
    const suffix = !providerThere ? ` (provider ${provider} non disponibile)` : value.model && value.model !== LOADED_MODEL ? ' (modello non elencato)' : '';
    orphan = { key, label: `${what}${suffix}`, inGroup: providerThere ? provider : null };
  }

  const specials = (
    <>
      <option value={DEFAULT_KEY}>Default del server</option>
      {(!defaultIsCloud || key === LOADED_MODEL) && (
        <option value={LOADED_MODEL}>Modello caricato al momento{loadedModel ? ` (ora: ${loadedModel})` : ''}</option>
      )}
    </>
  );

  return (
    <select value={key} onChange={(e) => onChange(choiceOf(e.target.value))} className={className} aria-label={rest['aria-label']}>
      {specials}
      {providers.map((p) => (
        <optgroup key={p.name} label={p.display_name}>
          {p.models.map((m) => (
            <option key={m.id} value={pairKey(p.name, m.id)}>
              {m.id}
            </option>
          ))}
          {orphan?.inGroup === p.name && <option value={orphan.key}>{orphan.label}</option>}
        </optgroup>
      ))}
      {orphan && orphan.inGroup === null && <option value={orphan.key}>{orphan.label}</option>}
      {/* Una scelta con il provider predefinito non ancora noto: la voce salvata resta selezionata */}
      {!catalogReady && key !== DEFAULT_KEY && key !== LOADED_MODEL && <option value={key}>{value.model}</option>}
    </select>
  );
};
