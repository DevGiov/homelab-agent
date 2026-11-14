import { useCallback, useEffect, useRef, useState } from 'react';
import { setThreadSensitivity } from '../../api/threads';
import type { ConfirmRequest } from '../ConfirmDialog';
import { compareLabels, LABEL_NAMES, type SensitivityLevel } from '../../utils/sensitivity';

/**
 * Livello minimo della conversazione. Per una chat già salvata il cambio va subito al backend; per una chat nuova parte
 * con il primo messaggio. Abbassarlo chiede conferma: i messaggi successivi potranno uscire verso destinazioni che
 * prima non li ricevevano.
 */
export function useConversationLevel(threadId: string | null, savedLevel: SensitivityLevel | null,
                                     onSaved?: (level: SensitivityLevel) => void) {
  const [level, setLevel] = useState<SensitivityLevel>(savedLevel ?? 'public');
  const [pending, setPending] = useState<SensitivityLevel | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Un'altra conversazione riparte dal suo livello; il thread nato dal primo messaggio di una chat nuova (da null a un
  // id) è la stessa chat e tiene la scelta finché il backend non restituisce il livello salvato
  const previousThread = useRef(threadId);
  useEffect(() => {
    const bornFromNewChat = previousThread.current === null && threadId !== null;
    previousThread.current = threadId;
    if (bornFromNewChat && savedLevel === null) return;
    setLevel(savedLevel ?? 'public');
  }, [threadId, savedLevel]);

  const apply = useCallback(
    async (next: SensitivityLevel) => {
      setError(null);
      if (threadId) {
        try {
          await setThreadSensitivity(threadId, next);
        } catch (err) {
          console.error('Livello della conversazione non salvato:', err);
          setError('Livello della conversazione non salvato: riprova.');
          return;
        }
        onSaved?.(next);
      }
      setLevel(next);
    },
    [threadId, onSaved]
  );

  const requestChange = (next: SensitivityLevel) => {
    if (next === level) return;
    if (compareLabels(next, level) < 0) setPending(next);
    else void apply(next);
  };

  const confirmRequest: ConfirmRequest | null = pending
    ? {
        message:
          `Abbassare la conversazione da "${LABEL_NAMES[level]}" a "${LABEL_NAMES[pending]}"? I messaggi che scriverai da ` +
          'ora potranno andare a destinazioni che oggi non li ricevono (per esempio la ricerca web). Il cambio resta nell’audit.',
        confirmLabel: 'Abbassa',
      }
    : null;

  const answer = (confirmed: boolean) => {
    const next = pending;
    setPending(null);
    if (confirmed && next) void apply(next);
  };

  return { level, requestChange, confirmRequest, answer, error };
}
