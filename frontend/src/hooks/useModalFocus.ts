import { useEffect, useRef, type RefObject } from 'react';

const TABBABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'audio[controls]',
  'video[controls]',
  'summary',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]',
].join(',');

/** Di un gruppo di radio il Tab raggiunge solo quella scelta, o la prima se nessuna lo è. */
const isTabStopRadio = (el: HTMLElement) => {
  if (!(el instanceof HTMLInputElement) || el.type !== 'radio' || !el.name) return true;
  const group = Array.from(el.form?.elements ?? el.ownerDocument.querySelectorAll('input[type="radio"]')).filter(
    (r): r is HTMLInputElement => r instanceof HTMLInputElement && r.type === 'radio' && r.name === el.name,
  );
  return el.checked || (!group.some((r) => r.checked) && group[0] === el);
};

/** Elementi raggiungibili con Tab dentro `container`, nell'ordine del documento. */
export function tabbableIn(container: HTMLElement): HTMLElement[] {
  // Senza layout (jsdom) non si sa cosa è nascosto: valgono tutti
  const hasLayout = container.getClientRects().length > 0;
  return Array.from(container.querySelectorAll<HTMLElement>(TABBABLE)).filter(
    (el) => el.tabIndex >= 0 && !el.closest('[inert]') && (!hasLayout || el.getClientRects().length > 0) && isTabStopRadio(el),
  );
}

// Finestre aperte, dall'ultima in cima: Tab ed Escape valgono solo per quella in cima (una conferma dentro le impostazioni)
const openModals: HTMLElement[] = [];

interface ModalFocusOptions {
  /** Falso mentre la finestra è chiusa, per i componenti che restano montati. */
  active?: boolean;
  /** Chiude con Escape; senza, Escape non fa nulla (per esempio durante un salvataggio). */
  onClose?: () => void;
  /** Dove va il focus all'apertura; senza, al primo elemento raggiungibile o alla finestra stessa. */
  initialFocus?: RefObject<HTMLElement | null>;
}

/**
 * Focus di una finestra modale: all'apertura entra nella finestra, Tab e Maiusc+Tab restano dentro, Escape chiude, e alla
 * chiusura torna all'elemento che l'ha aperta. Il focus iniziale si sceglie con `initialFocus`, non con `autoFocus`:
 * l'elemento da cui tornare è quello che ha il focus quando la finestra si apre.
 */
export function useModalFocus(ref: RefObject<HTMLElement | null>, { active = true, onClose, initialFocus }: ModalFocusOptions = {}) {
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    const dialog = ref.current;
    if (!active || !dialog) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    openModals.push(dialog);

    if (!dialog.contains(document.activeElement)) {
      const target = initialFocus?.current ?? tabbableIn(dialog)[0] ?? dialog;
      if (target === dialog && !dialog.hasAttribute('tabindex')) dialog.tabIndex = -1;
      target.focus();
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (openModals[openModals.length - 1] !== dialog || e.defaultPrevented || e.isComposing) return;
      if (e.key === 'Escape') {
        if (!onCloseRef.current) return;
        e.preventDefault();
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = tabbableIn(dialog);
      const current = document.activeElement;
      if (items.length === 0) {
        e.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (!dialog.contains(current)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && (current === first || current === dialog)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && current === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      openModals.splice(openModals.indexOf(dialog), 1);
      // Torna a chi l'ha aperta, se c'è ancora e se il focus non è già andato altrove (un clic fuori, un'altra vista)
      const current = document.activeElement;
      const lost = !current || current === document.body || dialog.contains(current);
      if (opener?.isConnected && lost) opener.focus();
    };
  }, [active, ref, initialFocus]);
}
