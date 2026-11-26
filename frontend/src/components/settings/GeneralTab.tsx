import React, { useId, useState } from 'react';
import { AlertCircle, CheckCircle2, KeyRound, Loader2, Save } from 'lucide-react';
import { getApiKey, setApiKey } from '../../api/http';
import { formatApiError } from '../../utils/error';

const fieldClass =
  'w-full bg-input-bg border border-input-border rounded-xl px-3 py-2 text-xs text-fg focus:border-accent disabled:opacity-50';

/** API key del backend; il salvataggio chiude il modale. */
export const GeneralTab: React.FC<{ onSaved: () => void }> = ({ onSaved }) => {
  const fieldId = useId();
  const [apiKey, setLocalApiKey] = useState(getApiKey());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      setApiKey(apiKey);
      setSaved(true);
      setTimeout(onSaved, 800);
    } catch (err) {
      setError(formatApiError(err, 'Errore salvataggio impostazioni'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {error && (
        <div role="alert" className="flex items-center gap-2 bg-rose-950/70 border border-rose-800/80 rounded-xl p-2.5 text-xs text-rose-200">
          <AlertCircle size={14} className="text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="stack-y-1.5">
        <label htmlFor={`${fieldId}-key`} className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
          <KeyRound size={12} className="text-amber-400" />
          Chiave API (header X-API-Key)
        </label>
        <input
          id={`${fieldId}-key`}
          type="password"
          value={apiKey}
          onChange={(e) => setLocalApiKey(e.target.value)}
          placeholder="Inserisci la chiave API del backend..."
          className={`${fieldClass} font-mono`}
        />
        <p className="text-xs text-fg-muted leading-snug">Salvata in localStorage e inviata automaticamente alle chiamate API.</p>
      </div>

      <p className="text-xs text-fg-muted leading-snug">
        Provider e modelli si gestiscono nella scheda <strong>Provider</strong>; il modello si sceglie per ogni conversazione dal selettore della chat.
      </p>

      <button
        onClick={save}
        disabled={saving}
        className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition cursor-pointer disabled:opacity-50 ${
          saved ? 'bg-emerald-600/30 border border-emerald-500/50 text-emerald-300' : 'bg-accent hover:bg-accent-hover text-accent-contrast shadow-lg shadow-accent/25'
        }`}
      >
        {saved ? (
          <>
            <CheckCircle2 size={13} /> Salvato!
          </>
        ) : saving ? (
          <>
            <Loader2 size={13} className="animate-spin" /> Salvataggio...
          </>
        ) : (
          <>
            <Save size={13} /> Salva impostazioni
          </>
        )}
      </button>
    </>
  );
};
