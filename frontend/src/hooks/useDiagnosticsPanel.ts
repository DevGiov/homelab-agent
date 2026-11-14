import { useState } from 'react';

const STORAGE_KEY = 'diagnostics_panel_open';
/** Da questa larghezza la chat resta larga anche con il pannello aperto (1600 - 320 - 384 = 896 px). */
const WIDE_SCREEN = '(min-width: 1600px)';

/** Aperto se l'utente l'ha lasciato aperto; senza una scelta salvata, solo sugli schermi larghi. */
export function initialDiagnosticsOpen(): boolean {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'true' || saved === 'false') return saved === 'true';
  } catch {
    // Senza storage vale il default
  }
  return typeof window.matchMedia === 'function' ? window.matchMedia(WIDE_SCREEN).matches : true;
}

/**
 * Pannello della diagnostica a destra. `toggle` è la scelta dell'utente e resta; `reveal` lo apre per un motivo del
 * momento (il cassetto su mobile, "Diagnostica" su un messaggio) senza cambiare la scelta salvata.
 */
export function useDiagnosticsPanel() {
  const [open, setOpen] = useState(initialDiagnosticsOpen);

  const toggle = () => {
    const next = !open;
    try {
      localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      // La scelta vale per questa pagina
    }
    setOpen(next);
  };

  return { open, toggle, reveal: () => setOpen(true) };
}
