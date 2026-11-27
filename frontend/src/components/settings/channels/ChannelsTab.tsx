import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import {
  getChannelSettings,
  patchChannelSettings,
  resetChannelSettings,
  type ChannelSettings,
  type ChannelSettingsPatch,
} from '../../../api/settings';
import { ApiError } from '../../../api/http';
import { useConfirm } from '../../../hooks/useConfirm';
import { useFeedback } from '../../../hooks/useFeedback';
import { formatApiError } from '../../../utils/error';
import { settingsErrorMessage } from '../../../utils/settingsErrors';
import { ConfirmDialog } from '../../ConfirmDialog';
import { GeneralCard } from './GeneralCard';
import { TelegramCard } from './TelegramCard';

/** Il testo della conferma: quello del backend se c'è, altrimenti lo si ricava dalla modifica che si sta salvando. */
function confirmMessage(err: ApiError, patch: ChannelSettingsPatch, current: ChannelSettings | null): string {
  const fromBackend = (err.detail as { message?: unknown } | null)?.message;
  if (typeof fromBackend === 'string' && fromBackend.trim()) {
    const text = fromBackend.trim();
    return text.endsWith('?') ? text : `${text} Confermi?`;
  }
  const fields = patch.telegram?.fields;
  const added = (fields?.allowed_users ?? []).filter((id) => !current?.telegram.allowed_users.value.includes(id));
  if (added.length > 0) {
    return added.length === 1
      ? `L'utente ${added[0]} potrà dare comandi all'agente. Confermi?`
      : `Gli utenti ${added.join(', ')} potranno dare comandi all'agente. Confermi?`;
  }
  if (fields?.clearance === 'internal') return 'Le risposte fino a dati interni arriveranno su Telegram senza conferma. Confermi?';
  return 'Questa modifica allarga chi può comandare l\'agente o i dati che riceve su Telegram. Confermi?';
}

/**
 * Canali: Telegram (stato, token in sola scrittura, utenti ammessi, livello dei dati) e le impostazioni comuni.
 * Le modifiche valgono subito: il backend riavvia il canale da solo.
 */
export const ChannelsTab: React.FC = () => {
  const [data, setData] = useState<ChannelSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const { feedback, notify } = useFeedback();
  const { confirm, dialog } = useConfirm();

  const load = useCallback(async () => {
    try {
      setData(await getChannelSettings());
    } catch (err) {
      notify('error', `Canali non caricati: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    load();
  }, [load]);

  /** PATCH che, su 409 `confirm_required`, mostra la conferma e lo ripete con `confirm: true`. Restituisce l'esito
   * per i moduli: `false` se l'utente annulla o la chiamata fallisce (l'errore è già mostrato). */
  const apply = async (patch: ChannelSettingsPatch, success?: string): Promise<boolean> => {
    setBusy(true);
    try {
      let next: ChannelSettings;
      try {
        next = await patchChannelSettings(patch);
      } catch (err) {
        const code = err instanceof ApiError && err.status === 409 ? (err.detail as { code?: unknown } | null)?.code : null;
        if (code !== 'confirm_required') throw err;
        const confirmed = await confirm({ message: confirmMessage(err as ApiError, patch, data), confirmLabel: 'Conferma' });
        if (!confirmed) return false;
        next = await patchChannelSettings({ ...patch, confirm: true });
      }
      setData(next);
      if (success) notify('success', success);
      return true;
    } catch (err) {
      notify('error', settingsErrorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const reset = async (): Promise<boolean> => {
    const confirmed = await confirm({
      message: 'Ripristinare i canali al .env? Tutte le modifiche fatte dalla UI (Telegram e impostazioni generali, token compreso) vengono tolte.',
      confirmLabel: 'Ripristina',
    });
    if (!confirmed) return false;
    setBusy(true);
    try {
      setData(await resetChannelSettings());
      notify('success', 'Canali ripristinati al .env.');
      return true;
    } catch (err) {
      notify('error', settingsErrorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack-y-3">
      <ConfirmDialog {...dialog} />
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-fg-muted leading-relaxed min-w-0">
          Canali di messaggistica. I valori vengono dal <code>.env</code> finché non li cambi qui; «torna al .env» toglie il valore della UI.
          Il token si scrive e non si rilegge. Le modifiche valgono subito: il canale si riavvia da solo.
        </p>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            load();
          }}
          disabled={loading}
          aria-label="Ricarica i canali"
          className="p-1.5 rounded-lg border border-border text-fg-muted hover:text-fg hover:bg-panel-hover shrink-0 cursor-pointer"
          title="Ricarica i canali"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
        </button>
      </div>

      {feedback && (
        <div
          role={feedback.type === 'error' ? 'alert' : 'status'}
          className={`p-2 rounded-lg text-xs border break-words ${
            feedback.type === 'success' ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300' : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
          }`}
        >
          {feedback.text}
        </div>
      )}

      {loading && !data && (
        <p className="flex items-center gap-2 text-xs text-fg-muted">
          <Loader2 size={13} className="animate-spin" aria-hidden="true" /> Caricamento dei canali...
        </p>
      )}

      {data && (
        <>
          <TelegramCard settings={data} apply={apply} reset={reset} disabled={busy} />
          <GeneralCard settings={data} apply={apply} disabled={busy} />
        </>
      )}
    </div>
  );
};
