import React, { useId, useState } from 'react';
import { Save } from 'lucide-react';
import type { ChannelSettings, ChannelSettingsPatch } from '../../../api/settings';
import { inputClass } from '../providers/providerStyles';
import { FieldHead, type ApplyPatch } from './channelParts';
import { saveButtonClass } from './channelStyles';

export const TIMEOUT_MIN = 30;
export const TIMEOUT_MAX = 3600;

/** Errore di un indirizzo scritto a mano, o `null` se va bene (vuoto = nessun indirizzo). */
function urlError(text: string): string | null {
  const t = text.trim();
  if (t === '') return null;
  return /^https?:\/\/\S+$/i.test(t) ? null : 'Scrivi un indirizzo che inizi con http:// o https://, oppure lascia vuoto.';
}

function timeoutError(text: string): string | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return `Scrivi un numero intero di secondi, da ${TIMEOUT_MIN} a ${TIMEOUT_MAX}.`;
  const n = Number(t);
  return n >= TIMEOUT_MIN && n <= TIMEOUT_MAX ? null : `L'attesa va da ${TIMEOUT_MIN} a ${TIMEOUT_MAX} secondi.`;
}

interface Props {
  settings: ChannelSettings;
  apply: ApplyPatch;
  disabled: boolean;
}

/** Impostazioni comuni a tutti i canali: l'indirizzo della Web UI per i link nei messaggi, l'attesa massima della risposta. */
export const GeneralCard: React.FC<Props> = ({ settings, apply, disabled }) => {
  const id = useId();
  const [url, setUrl] = useState<string | null>(null);
  const [timeout, setTimeoutText] = useState<string | null>(null);

  const urlText = url ?? settings.web_ui_url.value;
  const timeoutText = timeout ?? String(settings.reply_timeout_seconds.value);
  const urlChanged = url !== null && url.trim() !== settings.web_ui_url.value;
  const timeoutChanged = timeout !== null && timeout.trim() !== String(settings.reply_timeout_seconds.value);
  const urlProblem = urlChanged ? urlError(urlText) : null;
  const timeoutProblem = timeoutChanged ? timeoutError(timeoutText) : null;
  const canSave = (urlChanged || timeoutChanged) && !urlProblem && !timeoutProblem && !disabled;

  const save = async () => {
    const fields: NonNullable<ChannelSettingsPatch['fields']> = {};
    if (urlChanged) fields.web_ui_url = urlText.trim();
    if (timeoutChanged) fields.reply_timeout_seconds = Number(timeoutText.trim());
    if (await apply({ fields }, 'Impostazioni generali salvate.')) {
      setUrl(null);
      setTimeoutText(null);
    }
  };

  const resetField = async (key: 'web_ui_url' | 'reply_timeout_seconds') => {
    if (await apply({ fields: { [key]: null } }, 'Il campo è tornato al valore del .env.')) {
      if (key === 'web_ui_url') setUrl(null);
      else setTimeoutText(null);
    }
  };

  return (
    <section className="bg-panel/70 border border-border rounded-xl p-3.5 stack-y-3" aria-labelledby={`${id}-title`} data-testid="channels-general">
      <h3 id={`${id}-title`} className="text-xs font-semibold text-fg">
        Generale
      </h3>

      <div className="stack-y-1">
        <FieldHead
          htmlFor={`${id}-url`}
          label="Indirizzo della Web UI"
          testKey="web_ui_url"
          source={settings.web_ui_url.source}
          onReset={() => resetField('web_ui_url')}
          disabled={disabled}
        />
        <input
          id={`${id}-url`}
          type="text"
          inputMode="url"
          value={urlText}
          onChange={(e) => setUrl(e.target.value)}
          disabled={disabled}
          placeholder="https://agente.example"
          aria-invalid={urlProblem ? true : undefined}
          aria-describedby={`${id}-url-hint`}
          className={`${inputClass} font-mono`}
        />
        <p id={`${id}-url-hint`} className="text-xs text-fg-muted">
          Serve per i link nei messaggi dei canali (per esempio «apri nella Web UI»). Vuoto: i messaggi non hanno link.
        </p>
        {urlProblem && (
          <p role="alert" className="text-xs text-rose-300">
            {urlProblem}
          </p>
        )}
      </div>

      <div className="stack-y-1">
        <FieldHead
          htmlFor={`${id}-timeout`}
          label="Attesa massima della risposta (secondi)"
          testKey="reply_timeout_seconds"
          source={settings.reply_timeout_seconds.source}
          onReset={() => resetField('reply_timeout_seconds')}
          disabled={disabled}
        />
        <input
          id={`${id}-timeout`}
          type="number"
          inputMode="numeric"
          min={TIMEOUT_MIN}
          max={TIMEOUT_MAX}
          value={timeoutText}
          onChange={(e) => setTimeoutText(e.target.value)}
          disabled={disabled}
          aria-invalid={timeoutProblem ? true : undefined}
          aria-describedby={`${id}-timeout-hint`}
          className={`${inputClass} font-mono w-32`}
        />
        <p id={`${id}-timeout-hint`} className="text-xs text-fg-muted">
          Quanto aspetta un canale la risposta dell'agente, da {TIMEOUT_MIN} a {TIMEOUT_MAX} secondi.
        </p>
        {timeoutProblem && (
          <p role="alert" className="text-xs text-rose-300">
            {timeoutProblem}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={!canSave} aria-label="Salva le impostazioni generali" className={saveButtonClass}>
          <Save size={12} aria-hidden="true" /> Salva
        </button>
      </div>
    </section>
  );
};
