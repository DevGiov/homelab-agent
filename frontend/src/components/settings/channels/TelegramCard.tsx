import React, { useId, useState } from 'react';
import { Loader2, Plus, PlugZap, Save, Undo2, X } from 'lucide-react';
import {
  testTelegramBot,
  type ChannelClearance,
  type ChannelSettings,
  type ChannelSettingsPatch,
  type TelegramTestResult,
} from '../../../api/settings';
import { SOURCE_LABELS } from '../../../utils/providerKinds';
import { LABEL_HINTS, LABEL_NAMES } from '../../../utils/sensitivity';
import { settingsErrorMessage } from '../../../utils/settingsErrors';
import { Toggle } from '../../Toggle';
import { inputClass, labelClass } from '../providers/providerStyles';
import { FieldHead, type ApplyPatch } from './channelParts';
import { saveButtonClass, secondaryButtonClass, tokenStatus } from './channelStyles';

const CLEARANCES: ChannelClearance[] = ['public', 'internal'];

const badge = 'px-1.5 py-0.5 rounded-sm text-xs font-medium border flex items-center gap-1';

/** Perché il canale è fermo, in ordine: la scelta dell'utente, poi quello che manca. `null` se non c'è un motivo da dire. */
function stoppedReason(settings: ChannelSettings): string | null {
  const t = settings.telegram;
  // Senza token l'interruttore resta spento da solo: il motivo vero è il token
  if (!t.secrets.bot_token.set) return 'manca il token';
  if (!t.enabled.value) return 'disattivato';
  if (t.allowed_users.value.length === 0) return 'nessun utente ammesso';
  return null;
}

/** Un id Telegram: intero positivo. Restituisce il numero, o il motivo per cui non va. */
function parseUserId(text: string, existing: number[]): { id: number } | { error: string } {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return { error: 'Scrivi l\'id numerico: solo cifre, intero positivo.' };
  const id = Number(t);
  if (!Number.isSafeInteger(id) || id <= 0) return { error: 'L\'id deve essere un intero positivo.' };
  if (existing.includes(id)) return { error: 'Questo id è già nell\'elenco.' };
  return { id };
}

const sameList = (a: number[], b: number[]) => a.length === b.length && a.every((v, i) => v === b[i]);

interface Props {
  settings: ChannelSettings;
  apply: ApplyPatch;
  /** Toglie ogni valore della UI dei canali, dopo la conferma. `false` se annullato o fallito. */
  reset: () => Promise<boolean>;
  disabled: boolean;
}

/** Il canale Telegram: stato, interruttore, token in sola scrittura con prova, utenti ammessi e livello dei dati. */
export const TelegramCard: React.FC<Props> = ({ settings, apply, reset, disabled }) => {
  const id = useId();
  const t = settings.telegram;
  const [users, setUsers] = useState<number[] | null>(null);
  const [newUser, setNewUser] = useState('');
  const [userError, setUserError] = useState<string | null>(null);
  const [level, setLevel] = useState<ChannelClearance | null>(null);
  const [token, setToken] = useState('');
  const [test, setTest] = useState<TelegramTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const canStore = settings.can_store_secrets;
  const shownUsers = users ?? t.allowed_users.value;
  const shownLevel = level ?? t.clearance.value;
  const usersChanged = users !== null && !sameList(users, t.allowed_users.value);
  const levelChanged = level !== null && level !== t.clearance.value;
  const dirty = usersChanged || levelChanged || token !== '';
  const levelOptions = CLEARANCES.includes(t.clearance.value) ? CLEARANCES : [...CLEARANCES, t.clearance.value];

  const reason = stoppedReason(settings);
  const ignoredTotal = Object.values(t.status.ignored).reduce((sum, n) => sum + n, 0);

  const clearDrafts = () => {
    setUsers(null);
    setNewUser('');
    setUserError(null);
    setLevel(null);
    setToken('');
  };

  const addUser = () => {
    const parsed = parseUserId(newUser, shownUsers);
    if ('error' in parsed) {
      setUserError(parsed.error);
      return;
    }
    setUsers([...shownUsers, parsed.id]);
    setNewUser('');
    setUserError(null);
  };

  const save = async () => {
    const fields: NonNullable<NonNullable<ChannelSettingsPatch['telegram']>['fields']> = {};
    if (usersChanged) fields.allowed_users = shownUsers;
    if (levelChanged) fields.clearance = shownLevel;
    const patch: NonNullable<ChannelSettingsPatch['telegram']> = {};
    if (Object.keys(fields).length > 0) patch.fields = fields;
    if (token !== '') patch.secrets = { bot_token: token };
    // Il token scritto non resta nel modulo né dopo un errore: va riscritto (sola scrittura)
    const ok = await apply({ telegram: patch }, 'Telegram salvato.');
    setToken('');
    if (ok) clearDrafts();
  };

  const resetField = async (key: 'enabled' | 'allowed_users' | 'clearance') => {
    if (await apply({ telegram: { fields: { [key]: null } } }, 'Il campo è tornato al valore del .env.')) {
      if (key === 'allowed_users') setUsers(null);
      if (key === 'clearance') setLevel(null);
    }
  };

  const runTest = async () => {
    const draft = token;
    setTesting(true);
    setTest(null);
    try {
      setTest(await testTelegramBot(draft || undefined));
    } catch (err) {
      setTest({ ok: false, bot_username: null, error: settingsErrorMessage(err) });
    } finally {
      setTesting(false);
      // Il token digitato non resta nella pagina nemmeno dopo la prova
      setToken('');
    }
  };

  const restore = async () => {
    if (await reset()) clearDrafts();
  };

  return (
    <section className="bg-panel/70 border border-border rounded-xl p-3.5 stack-y-4" aria-labelledby={`${id}-title`} data-testid="channels-telegram">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h3 id={`${id}-title`} className="text-xs font-semibold text-fg">
          Telegram
        </h3>
        <span
          data-testid="telegram-status"
          className={`${badge} ${t.status.running ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25' : 'bg-amber-500/10 text-amber-300 border-amber-500/25'}`}
        >
          {t.status.running ? 'attivo' : reason ? `fermo: ${reason}` : 'fermo'}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Toggle
          checked={t.enabled.value}
          onChange={(enabled) => apply({ telegram: { fields: { enabled } } }, enabled ? 'Telegram attivato.' : 'Telegram disattivato.')}
          disabled={disabled}
          label="Telegram attivo"
          size="sm"
          title={t.enabled.value ? 'Disattiva il canale Telegram' : 'Attiva il canale Telegram'}
        />
        <span className="text-xs font-medium text-fg-muted">{t.enabled.value ? 'Acceso' : 'Spento'}</span>
        <span className="text-xs text-fg-muted" data-testid="origin-enabled">
          ({SOURCE_LABELS[t.enabled.source]})
        </span>
        {t.enabled.source === 'ui' && (
          <button
            type="button"
            onClick={() => resetField('enabled')}
            disabled={disabled}
            aria-label="Riporta «Telegram attivo» al .env"
            className="px-1.5 py-0.5 rounded-md text-xs text-accent-text hover:bg-accent/10 cursor-pointer disabled:opacity-40"
          >
            torna al .env
          </button>
        )}
      </div>

      {t.status.last_error && (
        <p className="text-xs text-rose-300 break-words" data-testid="telegram-last-error">
          Ultimo errore: {t.status.last_error}
        </p>
      )}
      {ignoredTotal > 0 && (
        <p className="text-xs text-fg-muted">
          Messaggi scartati (tipo non supportato o utente non ammesso): {ignoredTotal}.
        </p>
      )}

      <details className="text-xs text-fg-muted">
        <summary className="cursor-pointer text-fg">Come si configura</summary>
        <ol className="list-decimal pl-5 mt-1.5 stack-y-1 leading-relaxed">
          <li>
            Crea il bot scrivendo a <strong>@BotFather</strong> su Telegram: il comando è <code>/newbot</code>. Ti dà il token.
          </li>
          <li>
            Trova il tuo id numerico scrivendo a un bot come <strong>@userinfobot</strong>.
          </li>
          <li>Incolla qui il token e l'id, poi salva. Il canale parte da solo.</li>
        </ol>
      </details>

      <div className="stack-y-1" role="group" aria-label="Credenziale del bot">
        <label htmlFor={`${id}-token`} className={labelClass}>
          Token del bot
        </label>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-xs text-fg-muted" data-testid="secret-bot_token">
            {tokenStatus(t.secrets.bot_token)}
          </span>
          {t.secrets.bot_token.source === 'ui' && (
            <button
              type="button"
              onClick={() => apply({ telegram: { secrets: { bot_token: null } } }, 'Token tolto dalla UI.')}
              disabled={disabled}
              aria-label="Togli il token salvato dalla UI"
              className="px-1.5 py-0.5 rounded-md text-xs text-accent-text hover:bg-accent/10 cursor-pointer disabled:opacity-40"
            >
              Togli
            </button>
          )}
        </div>
        {!canStore && (
          <p id={`${id}-reason`} className="text-xs text-amber-300">
            Il token non si può salvare dalla UI: imposta API_SECRET_KEY nel .env e ricrea il backend.
          </p>
        )}
        <input
          id={`${id}-token`}
          type="password"
          autoComplete="new-password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          disabled={disabled || !canStore}
          aria-describedby={canStore ? undefined : `${id}-reason`}
          placeholder={canStore ? 'Scrivi il nuovo token (sola scrittura)' : 'imposta API_SECRET_KEY nel .env'}
          className={`${inputClass} font-mono`}
        />
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button type="button" onClick={runTest} disabled={testing || disabled} className={secondaryButtonClass}>
            {testing ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <PlugZap size={12} aria-hidden="true" />}
            Prova il bot
          </button>
          {test && (
            <span role="status" className={`text-xs break-words min-w-0 ${test.ok ? 'text-emerald-300' : 'text-rose-300'}`}>
              {test.ok ? `Il bot risponde: @${test.bot_username ?? '?'}.` : `Prova non riuscita${test.error ? `: ${test.error}` : '.'}`}
            </span>
          )}
        </div>
        <p className="text-xs text-fg-muted">La prova usa il token scritto qui, se c'è; altrimenti quello salvato. Dopo la prova il campo si svuota.</p>
      </div>

      <div className="stack-y-1.5">
        <FieldHead
          label="Utenti ammessi"
          testKey="allowed_users"
          source={t.allowed_users.source}
          onReset={() => resetField('allowed_users')}
          disabled={disabled}
        />
        <p className="text-xs text-fg-muted">Solo questi id Telegram possono dare comandi all'agente: aggiungerne uno chiede conferma.</p>
        {shownUsers.length === 0 ? (
          <p className="text-xs text-amber-300">Nessun utente ammesso: il canale resta fermo.</p>
        ) : (
          <ul aria-label="Utenti ammessi" className="flex flex-wrap gap-1.5">
            {shownUsers.map((user) => (
              <li key={user} className="flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-md bg-bg/60 border border-border text-xs font-mono min-w-0">
                <span className="break-all">{user}</span>
                <button
                  type="button"
                  onClick={() => setUsers(shownUsers.filter((u) => u !== user))}
                  disabled={disabled}
                  aria-label={`Togli l'utente ${user}`}
                  className="p-0.5 rounded-sm text-fg-muted hover:text-fg cursor-pointer disabled:opacity-40"
                >
                  <X size={11} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <input
            id={`${id}-new-user`}
            type="text"
            inputMode="numeric"
            value={newUser}
            onChange={(e) => {
              setNewUser(e.target.value);
              setUserError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addUser();
              }
            }}
            disabled={disabled}
            placeholder="id numerico, es. 123456789"
            aria-label="Id Telegram da aggiungere"
            aria-invalid={userError ? true : undefined}
            className={`${inputClass} font-mono flex-1 min-w-0`}
          />
          <button type="button" onClick={addUser} disabled={disabled || newUser.trim() === ''} className={secondaryButtonClass}>
            <Plus size={12} aria-hidden="true" /> aggiungi
          </button>
        </div>
        {userError && (
          <p role="alert" className="text-xs text-rose-300">
            {userError}
          </p>
        )}
      </div>

      <div className="stack-y-1">
        <FieldHead
          htmlFor={`${id}-clearance`}
          label="Dati che può ricevere"
          testKey="clearance"
          source={t.clearance.source}
          onReset={() => resetField('clearance')}
          disabled={disabled}
        />
        <select
          id={`${id}-clearance`}
          value={shownLevel}
          onChange={(e) => setLevel(e.target.value as ChannelClearance)}
          disabled={disabled}
          className={`${inputClass} w-48 cursor-pointer`}
        >
          {levelOptions.map((l) => (
            <option key={l} value={l} className="bg-panel text-fg">
              {LABEL_NAMES[l]}
            </option>
          ))}
        </select>
        <p className="text-xs text-fg-muted">
          {LABEL_HINTS[shownLevel]}. «Privati» non si concede a un canale. Alzare il livello chiede conferma.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={!dirty || disabled} aria-label="Salva Telegram" className={saveButtonClass}>
          <Save size={12} aria-hidden="true" /> Salva
        </button>
        {dirty && <span className="text-xs text-fg-muted">Ci sono modifiche non salvate.</span>}
        <button type="button" onClick={restore} disabled={disabled} className={`${secondaryButtonClass} ml-auto`}>
          <Undo2 size={12} aria-hidden="true" /> Ripristina il .env
        </button>
      </div>
    </section>
  );
};
