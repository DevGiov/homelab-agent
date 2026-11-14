import { useCallback, useState } from 'react';
import { compareLabels, type SensitivityLabel, type SensitivityTag } from '../../utils/sensitivity';

const STORAGE_KEY = 'sensitivity_bar_hidden';

/** Il livello a cui l'utente ha nascosto la fascia: resta nascosta finché la conversazione non va oltre. */
interface HiddenAt {
  label: SensitivityLabel;
  untrusted: boolean;
}

function read(): HiddenAt | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as HiddenAt;
    return typeof value?.label === 'string' ? { label: value.label, untrusted: Boolean(value.untrusted) } : null;
  } catch {
    return null;
  }
}

function write(value: HiddenAt | null): void {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Senza storage la scelta vale solo per questa pagina
  }
}

/** Vero se la fascia nascosta a `hidden` copre anche `tag`: stesso livello o più basso, e niente di non attendibile in più. */
export function hiddenCovers(hidden: HiddenAt | null, tag: SensitivityTag): boolean {
  if (!hidden) return false;
  return compareLabels(tag.label, hidden.label) <= 0 && (!tag.untrusted || hidden.untrusted);
}

/**
 * Fascia della sensibilità nascondibile. Nasconderla vale per tutte le conversazioni (resta la chip
 * nell'intestazione), ma ricompare quando il livello sale o arriva contenuto non attendibile: è un'informazione nuova.
 */
export function useSensitivityBarVisibility(tag: SensitivityTag) {
  const [hiddenAt, setHiddenAt] = useState<HiddenAt | null>(read);
  const label = tag.label;
  const untrusted = Boolean(tag.untrusted);

  const hide = useCallback(() => {
    const value = { label, untrusted };
    write(value);
    setHiddenAt(value);
  }, [label, untrusted]);

  const show = useCallback(() => {
    write(null);
    setHiddenAt(null);
  }, []);

  return { hidden: hiddenCovers(hiddenAt, tag), hide, show };
}
