import React, { useId, useState } from 'react';
import { AlertTriangle, ChevronDown, Cloud, Loader2, PlugZap, Save, Server, ShieldCheck, Trash2, Undo2 } from 'lucide-react';
import {
  deleteProvider,
  resetProvider,
  setProviderClearance,
  testProvider,
  updateProvider,
  type FieldValue,
  type ProviderConfig,
  type ProviderCosts,
  type ProviderPatch,
  type ProviderTestResult,
} from '../../../api/providers';
import { ApiError } from '../../../api/http';
import type { Confirm } from '../../../hooks/useConfirm';
import { useFeedback } from '../../../hooks/useFeedback';
import { compareLabels, LABEL_HINTS, LABEL_NAMES, LEVELS, type SensitivityLevel } from '../../../utils/sensitivity';
import { fieldLabel, fromFormValue, PROVIDER_KINDS, toFormValue, without } from '../../../utils/providerKinds';
import { providerErrorMessage } from '../../../utils/providerErrors';
import { Toggle } from '../../Toggle';
import { ModelPrices, SpendCeiling } from './CostsSection';
import { ModelDiscovery } from './ModelDiscovery';
import { ProviderFields, ProviderSecrets } from './ProviderFields';
import { inputClass, labelClass } from './providerStyles';

const CLEARANCE_TEXT: Record<SensitivityLevel, string> = { public: 'pubblici', internal: 'interni', private: 'privati' };

const MODELS_FIELD = { key: 'models', label: 'Modelli', type: 'list' } as const;

const badge = 'px-1.5 py-0.5 rounded-sm text-xs font-medium border flex items-center gap-1';

interface ProviderCardProps {
  provider: ProviderConfig;
  canStoreSecrets: boolean;
  costs: ProviderCosts | null;
  /** Modelli del provider nel catalogo, per i prezzi. */
  catalogModels: string[];
  confirm: Confirm;
  /** Ricarica l'elenco dopo una modifica. */
  onChanged: () => Promise<void>;
}

/** Dove manda i dati il provider, per il dialogo che chiede conferma del livello: l'indirizzo, o la regione di Bedrock. */
function addressOf(provider: ProviderConfig): string {
  const def = PROVIDER_KINDS[provider.kind];
  const value = provider.fields[def.addressField]?.value;
  const text = Array.isArray(value) ? value.join(', ') : value == null ? '' : String(value);
  if (!text) return 'un indirizzo non ancora impostato';
  return def.addressField === 'region' ? `la regione ${text}` : text;
}

/** Un provider: stato in testa, e aperto il modulo, la prova di connessione, il livello, i costi e le azioni in fondo. */
export const ProviderCard: React.FC<ProviderCardProps> = ({ provider, canStoreSecrets, costs, catalogModels, confirm, onChanged }) => {
  const bodyId = useId();
  const nameId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string | boolean>>({});
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [test, setTest] = useState<ProviderTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const { feedback, notify } = useFeedback();

  const kind = PROVIDER_KINDS[provider.kind];
  const dirtyFields = kind.fields.filter((def) => def.key in edits && edits[def.key] !== toFormValue(def, provider.fields[def.key]?.value));
  const typedSecrets = Object.entries(typed).filter(([, value]) => value !== '');
  const nameChanged = displayName !== null && displayName.trim() !== provider.display_name;
  const dirty = dirtyFields.length > 0 || typedSecrets.length > 0 || nameChanged;

  /** Esegue una chiamata: in caso di errore lo dice nella scheda, altrimenti ricarica l'elenco. */
  // `action` che restituisce `false`: annullata dall'utente, nessun messaggio
  const run = async (action: () => Promise<unknown>, success?: string): Promise<boolean> => {
    setBusy(true);
    try {
      if ((await action()) === false) return false;
      if (success) notify('success', success);
      await onChanged();
      return true;
    } catch (err) {
      notify('error', providerErrorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  /** Le modifiche non ancora salvate, come corpo di un PATCH (anche per provare senza salvare). */
  const draftPatch = (): ProviderPatch => {
    const patch: ProviderPatch = {};
    if (nameChanged) patch.display_name = displayName!.trim();
    if (dirtyFields.length > 0) {
      patch.fields = Object.fromEntries(dirtyFields.map((def) => [def.key, fromFormValue(def, edits[def.key])])) as Record<string, FieldValue>;
    }
    if (typedSecrets.length > 0) patch.secrets = Object.fromEntries(typedSecrets);
    return patch;
  };

  /** PATCH che, se cambia l'indirizzo del provider di ripiego (409 `confirm_required`), chiede la conferma e lo
   * ripete con `confirm: true`. `false` se l'utente annulla. */
  const patchConfirmed = async (patch: ProviderPatch): Promise<boolean> => {
    try {
      await updateProvider(provider.name, patch);
      return true;
    } catch (err) {
      const code = err instanceof ApiError && err.status === 409 ? (err.detail as { code?: unknown } | null)?.code : null;
      if (code !== 'confirm_required') throw err;
      const confirmed = await confirm({ message: `${err instanceof Error ? err.message : ''} Confermi?`, confirmLabel: 'Conferma' });
      if (!confirmed) return false;
      await updateProvider(provider.name, { ...patch, confirm: true });
      return true;
    }
  };

  const save = async () => {
    const ok = await run(() => patchConfirmed(draftPatch()), 'Provider salvato.');
    if (ok) {
      setEdits({});
      setTyped({});
      setDisplayName(null);
    }
  };

  const resetField = (key: string) =>
    run(async () => {
      if (!(await patchConfirmed({ fields: { [key]: null } }))) return false;
      setEdits((e) => without(e, key));
    }, 'Il campo è tornato al valore del .env.');

  const removeSecret = (key: string) =>
    run(() => updateProvider(provider.name, { secrets: { [key]: null } }), 'Credenziale tolta dalla UI.');

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await testProvider(provider.name, dirty ? draftPatch() : undefined));
    } catch (err) {
      setTest({ ok: false, latency_ms: null, models_count: null, error: providerErrorMessage(err) });
    } finally {
      setTesting(false);
    }
  };

  const changeClearance = async (next: SensitivityLevel) => {
    const current = provider.clearance.effective;
    if (next === current) return;
    // Abbassare non chiede nulla; alzare dice dove andranno i dati e aspetta la conferma
    if (compareLabels(next, current) > 0) {
      const confirmed = await confirm({
        message:
          `Il provider «${provider.display_name}» (${addressOf(provider)}) potrà ricevere dati ${CLEARANCE_TEXT[next]}. ` +
          `${LABEL_HINTS[next]}. Il livello vale per questo indirizzo: se lo cambi torna «pubblici». Il cambio resta nell'audit.`,
        confirmLabel: 'Concedi',
      });
      if (!confirmed) return;
      await run(() => setProviderClearance(provider.name, next, true), `Il provider riceve dati ${CLEARANCE_TEXT[next]}.`);
    } else {
      await run(() => setProviderClearance(provider.name, next, false), `Il provider riceve dati ${CLEARANCE_TEXT[next]}.`);
    }
  };

  const remove = async () => {
    const confirmed = await confirm({
      message: `Eliminare il provider «${provider.display_name}» con i suoi prezzi e il suo tetto? Le metriche passate restano.`,
      confirmLabel: 'Elimina',
    });
    if (confirmed) await run(() => deleteProvider(provider.name));
  };

  const restore = async () => {
    const confirmed = await confirm({
      message: `Ripristinare «${provider.display_name}» al .env? Tutte le modifiche fatte dalla UI (campi, credenziali, livello) vengono tolte.`,
      confirmLabel: 'Ripristina',
    });
    if (!confirmed) return;
    const ok = await run(() => resetProvider(provider.name), 'Provider ripristinato al .env.');
    if (ok) {
      setEdits({});
      setTyped({});
      setDisplayName(null);
    }
  };

  const reachability = provider.healthy === null ? 'non provato' : provider.healthy ? 'raggiungibile' : 'non raggiungibile';
  const modelIds = [...new Set([...catalogModels, ...(Array.isArray(provider.fields.models?.value) ? (provider.fields.models.value as string[]) : [])])];

  return (
    <section className="bg-panel/70 border border-border rounded-xl" aria-labelledby={nameId} data-testid={`provider-${provider.name}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 p-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`${open ? 'Chiudi' : 'Apri'} il provider ${provider.display_name}`}
          className="p-1 rounded-md text-fg-muted hover:text-fg cursor-pointer"
        >
          <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
        <div className="min-w-0">
          <h3 id={nameId} className="text-xs font-semibold text-fg truncate">
            {provider.display_name}
          </h3>
          <p className="text-xs text-fg-muted font-mono truncate">{provider.name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`${badge} bg-panel-header/70 text-fg-muted border-border`}>
            {provider.cloud ? <Cloud size={9} aria-hidden="true" /> : <Server size={9} aria-hidden="true" />}
            {kind.label}
          </span>
          <span className={`${badge} ${provider.enabled ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25' : 'bg-bg/60 text-fg-muted border-border'}`}>
            {provider.enabled ? 'attivo' : 'disattivato'}
          </span>
          <span
            className={`${badge} ${
              provider.healthy === false ? 'bg-amber-500/10 text-amber-300 border-amber-500/25' : 'bg-bg/60 text-fg-muted border-border'
            }`}
          >
            {reachability}
          </span>
          <span className={`${badge} bg-sky-500/10 text-sky-300 border-sky-500/25`} title={LABEL_HINTS[provider.clearance.effective]}>
            <ShieldCheck size={9} aria-hidden="true" />
            riceve dati {CLEARANCE_TEXT[provider.clearance.effective]}
          </span>
          {!provider.configured && (
            <span className={`${badge} bg-amber-500/10 text-amber-300 border-amber-500/25`}>non configurato</span>
          )}
          {provider.is_default && <span className={`${badge} bg-accent/10 text-accent-text border-accent/30`}>predefinito</span>}
          {provider.is_fallback && <span className={`${badge} bg-accent/10 text-accent-text border-accent/30`}>ripiego</span>}
        </div>
        <div className="ml-auto">
          <Toggle
            checked={provider.enabled}
            onChange={(enabled) => run(() => updateProvider(provider.name, { enabled }), enabled ? 'Provider attivato.' : 'Provider disattivato.')}
            disabled={busy}
            label={`Attivo: ${provider.display_name}`}
            size="sm"
            title={provider.enabled ? 'Disattiva il provider' : 'Attiva il provider'}
          />
        </div>
      </div>

      {feedback && (
        <p
          role={feedback.type === 'error' ? 'alert' : 'status'}
          className={`mx-3 mb-3 p-2 rounded-lg text-xs border ${
            feedback.type === 'success' ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300' : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
          }`}
        >
          {feedback.text}
        </p>
      )}

      {open && (
        <div id={bodyId} className="border-t border-border p-3 stack-y-4">
          {!provider.configured && provider.missing.length > 0 && (
            <p className="text-xs text-amber-300">
              Non è nel catalogo dei modelli finché mancano: {provider.missing.map((key) => fieldLabel(provider.kind, key)).join(', ')}.
            </p>
          )}
          {provider.error && <p className="text-xs text-rose-300">Ultimo errore: {provider.error}</p>}

          <div className="stack-y-1">
            <label htmlFor={`${bodyId}-display-name`} className={labelClass}>
              Nome visibile
            </label>
            <input
              id={`${bodyId}-display-name`}
              type="text"
              value={displayName ?? provider.display_name}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={busy}
              className={inputClass}
            />
          </div>

          <ProviderFields
            kind={provider.kind}
            origin={provider.origin}
            fields={provider.fields}
            edits={edits}
            onEdit={(key, value) => setEdits((e) => ({ ...e, [key]: value }))}
            onResetField={resetField}
            extras={
              kind.discoverable
                ? {
                    models: (
                      <ModelDiscovery
                        provider={provider.name}
                        kind={provider.kind}
                        getDraft={() => (dirty ? draftPatch() : undefined)}
                        currentModels={fromFormValue(MODELS_FIELD, edits.models ?? toFormValue(MODELS_FIELD, provider.fields.models?.value)) as string[]}
                        onUse={(ids) => setEdits((e) => ({ ...e, models: ids.join('\n') }))}
                        disabled={busy}
                      />
                    ),
                  }
                : undefined
            }
            disabled={busy}
          />

          <ProviderSecrets
            kind={provider.kind}
            secrets={provider.secrets}
            unreadable={provider.secrets_unreadable}
            canStoreSecrets={canStoreSecrets}
            typed={typed}
            onType={(key, value) => setTyped((t) => ({ ...t, [key]: value }))}
            onRemove={removeSecret}
            disabled={busy}
          />

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={!dirty || busy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-accent-contrast text-xs font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default"
            >
              <Save size={12} aria-hidden="true" /> Salva
            </button>
            <button
              type="button"
              onClick={runTest}
              disabled={testing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-fg-muted hover:text-fg text-xs cursor-pointer disabled:opacity-50"
            >
              {testing ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <PlugZap size={12} aria-hidden="true" />}
              Prova connessione
            </button>
            {test && (
              <span role="status" className={`text-xs ${test.ok ? 'text-emerald-300' : 'text-rose-300'}`}>
                {test.ok
                  ? `Connesso in ${test.latency_ms ?? '?'} ms${test.models_count != null ? `, ${test.models_count} modelli` : ''}.`
                  : `Connessione non riuscita${test.error ? `: ${test.error}` : '.'}`}
              </span>
            )}
          </div>
          {dirty && <p className="text-xs text-fg-muted">La prova usa le modifiche non ancora salvate.</p>}

          <div className="stack-y-1.5 border-t border-border pt-3">
            <h4 className="text-xs font-semibold text-fg">Dati che può ricevere</h4>
            {provider.clearance.reset_by_address_change && (
              <p role="alert" className="flex items-start gap-1.5 text-xs text-amber-300">
                <AlertTriangle size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
                <span>
                  L'indirizzo è cambiato{provider.clearance.granted_for ? ` (il livello era stato concesso per ${provider.clearance.granted_for})` : ''}: il
                  livello è tornato a «{LABEL_NAMES.public}». Alzalo di nuovo se l'indirizzo attuale è quello giusto.
                </span>
              </p>
            )}
            <label className="text-xs font-medium text-fg-muted">
              Livello effettivo
              <select
                value={provider.clearance.effective}
                onChange={(e) => changeClearance(e.target.value as SensitivityLevel)}
                disabled={busy}
                className={`${inputClass} mt-1 w-48 cursor-pointer`}
              >
                {LEVELS.map((level) => (
                  <option key={level} value={level} className="bg-panel text-fg">
                    {LABEL_NAMES[level]}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-xs text-fg-muted">{LABEL_HINTS[provider.clearance.effective]}. Alzarlo chiede conferma.</p>
          </div>

          <div className="stack-y-2 border-t border-border pt-3">
            <h4 className="text-xs font-semibold text-fg">Prezzi, tetto e spesa</h4>
            <ModelPrices provider={provider.name} models={modelIds} costs={costs} onChanged={onChanged} notify={notify} />
            <SpendCeiling scope={provider.name} label="Tetto mensile ($)" costs={costs} onChanged={onChanged} notify={notify} />
          </div>

          <div className="flex justify-end border-t border-border pt-3">
            {provider.origin === 'ui' ? (
              <button
                type="button"
                onClick={remove}
                disabled={busy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 text-xs cursor-pointer disabled:opacity-50"
              >
                <Trash2 size={12} aria-hidden="true" /> Elimina
              </button>
            ) : (
              <button
                type="button"
                onClick={restore}
                disabled={busy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-fg-muted hover:text-fg text-xs cursor-pointer disabled:opacity-50"
              >
                <Undo2 size={12} aria-hidden="true" /> Ripristina il .env
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
};
