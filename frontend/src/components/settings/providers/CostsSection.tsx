import React, { useState } from 'react';
import { Save, Trash2 } from 'lucide-react';
import {
  deleteModelPrice,
  deleteSpendCeiling,
  setModelPrice,
  setSpendCeiling,
  type ModelPrice,
  type PriceInput,
  type ProviderCosts,
} from '../../../api/providers';
import type { Notify } from '../../../hooks/useFeedback';
import { providerErrorMessage } from '../../../utils/providerErrors';
import { without } from '../../../utils/providerKinds';
import { inputClass } from './providerStyles';

const money = (usd: number) => `$${usd.toFixed(2)}`;

const PRICE_FIELDS: Array<{ key: keyof PriceInput; label: string }> = [
  { key: 'input_per_mtok', label: 'ingresso' },
  { key: 'cached_per_mtok', label: 'cache' },
  { key: 'output_per_mtok', label: 'uscita' },
];

type PriceDraft = Record<keyof PriceInput, string>;

const draftOf = (price: ModelPrice | undefined): PriceDraft => ({
  input_per_mtok: price ? String(price.input_per_mtok) : '',
  cached_per_mtok: price ? String(price.cached_per_mtok) : '',
  output_per_mtok: price ? String(price.output_per_mtok) : '',
});

const saveButton =
  'flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-accent-contrast text-xs font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default';
const removeButton = 'flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-border text-fg-muted hover:text-fg text-xs cursor-pointer';

interface SpendCeilingProps {
  /** Nome del provider, o `total` per il tetto complessivo. */
  scope: string;
  label: string;
  costs: ProviderCosts | null;
  onChanged: () => Promise<void>;
  notify: Notify;
}

/** Tetto mensile in dollari di un provider (o del totale) con la spesa del mese: nessun tetto vuol dire nessun limite. */
export const SpendCeiling: React.FC<SpendCeilingProps> = ({ scope, label, costs, onChanged, notify }) => {
  const [draft, setDraft] = useState<string | null>(null);
  const ceiling = costs?.ceilings[scope];
  const spend = scope === 'total' ? costs?.spend.total : (costs?.spend.by_provider[scope] ?? 0);
  const value = draft ?? (ceiling === undefined ? '' : String(ceiling));
  const parsed = Number(value);
  const valid = value.trim() !== '' && Number.isFinite(parsed) && parsed > 0;

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      setDraft(null);
      notify('success', success);
      await onChanged();
    } catch (err) {
      notify('error', providerErrorMessage(err));
    }
  };

  return (
    <div className="stack-y-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
        <span>
          Speso a {costs?.spend.month ?? '…'}: <strong className="text-fg">{spend === undefined ? '—' : money(spend)}</strong>
        </span>
        {costs?.reached[scope] && (
          <span className="px-1.5 py-0.5 rounded-sm bg-rose-500/10 text-rose-300 border border-rose-500/25 font-medium">tetto raggiunto</span>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs font-medium text-fg-muted">
          {label}
          <input
            type="number"
            min="0"
            step="any"
            inputMode="decimal"
            value={value}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="nessun tetto"
            className={`${inputClass} mt-1 w-36`}
          />
        </label>
        <button
          type="button"
          disabled={!valid}
          onClick={() => run(() => setSpendCeiling(scope, parsed), 'Tetto salvato.')}
          aria-label={`Salva il tetto mensile (${label})`}
          className={saveButton}
        >
          <Save size={12} aria-hidden="true" /> Salva
        </button>
        {ceiling !== undefined && (
          <button
            type="button"
            onClick={() => run(() => deleteSpendCeiling(scope), 'Tetto tolto: nessun limite.')}
            aria-label={`Togli il tetto mensile (${label})`}
            className={removeButton}
          >
            <Trash2 size={12} aria-hidden="true" /> Togli
          </button>
        )}
      </div>
    </div>
  );
};

interface PricesProps {
  provider: string;
  /** I modelli del provider che si possono prezzare: quelli del catalogo, della configurazione e già prezzati. */
  models: string[];
  costs: ProviderCosts | null;
  onChanged: () => Promise<void>;
  notify: Notify;
}

/** Prezzi dei modelli del provider, in dollari per milione di token. */
export const ModelPrices: React.FC<PricesProps> = ({ provider, models, costs, onChanged, notify }) => {
  const [drafts, setDrafts] = useState<Record<string, PriceDraft>>({});
  const prices = new Map((costs?.prices ?? []).filter((p) => p.provider === provider).map((p) => [p.model, p]));
  const ids = [...new Set([...models, ...prices.keys()])];

  if (ids.length === 0) return <p className="text-xs text-fg-muted italic">Nessun modello a cui dare un prezzo.</p>;

  const run = async (model: string, action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      setDrafts((d) => without(d, model));
      notify('success', success);
      await onChanged();
    } catch (err) {
      notify('error', providerErrorMessage(err));
    }
  };

  return (
    <div className="stack-y-1.5">
      <p className="text-xs text-fg-muted">Dollari per milione di token. Senza un prezzo il modello costa zero.</p>
      {ids.map((model) => {
        const price = prices.get(model);
        const draft = drafts[model] ?? draftOf(price);
        const numbers = PRICE_FIELDS.map(({ key }) => Number(draft[key]));
        const valid = PRICE_FIELDS.every(({ key }, i) => draft[key].trim() !== '' && Number.isFinite(numbers[i]) && numbers[i] >= 0);
        return (
          <div key={model} className="flex flex-wrap items-end gap-2 p-2 rounded-lg border border-border bg-bg/40" role="group" aria-label={`Prezzo di ${model}`}>
            <span className="font-mono text-xs text-fg min-w-[8rem] self-center">{model}</span>
            {PRICE_FIELDS.map(({ key, label }) => (
              <label key={key} className="text-xs text-fg-muted">
                {label}
                <input
                  type="number"
                  min="0"
                  step="any"
                  inputMode="decimal"
                  value={draft[key]}
                  onChange={(e) => setDrafts((d) => ({ ...d, [model]: { ...draft, [key]: e.target.value } }))}
                  aria-label={`Prezzo di ${label} di ${model}`}
                  className={`${inputClass} mt-0.5 w-24`}
                />
              </label>
            ))}
            <button
              type="button"
              disabled={!valid}
              onClick={() =>
                run(
                  model,
                  () => setModelPrice(provider, model, { input_per_mtok: numbers[0], cached_per_mtok: numbers[1], output_per_mtok: numbers[2] }),
                  `Prezzo di ${model} salvato.`
                )
              }
              aria-label={`Salva il prezzo di ${model}`}
              className={saveButton}
            >
              <Save size={12} aria-hidden="true" /> Salva
            </button>
            {price && (
              <button
                type="button"
                onClick={() => run(model, () => deleteModelPrice(provider, model), `Prezzo di ${model} tolto.`)}
                aria-label={`Togli il prezzo di ${model}`}
                className={removeButton}
              >
                <Trash2 size={12} aria-hidden="true" /> Togli
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
};
