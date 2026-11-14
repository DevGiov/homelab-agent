import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { formatRoute, parseRoute, type Route } from '../utils/route';

// La URL è la fonte di verità per la vista e la conversazione: la rotta si legge da `location`, si cambia con la History
// API, e chi la usa si aggiorna sia con `navigate` sia con indietro e avanti del browser (`popstate`).

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener('popstate', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('popstate', listener);
  };
}

const currentUrl = () => window.location.pathname + window.location.search;

interface NavigateOptions {
  /**
   * Sostituisce la voce corrente della cronologia invece di aggiungerne una. Per le correzioni automatiche: la
   * conversazione nuova che riceve il suo id, una URL che nomina qualcosa che non c'è più.
   */
  replace?: boolean;
}

/** Va a `route`. La navigazione dell'utente aggiunge una voce; verso la URL corrente non fa nulla. */
export function navigate(route: Route, { replace = false }: NavigateOptions = {}) {
  const url = formatRoute(route);
  if (url === currentUrl()) return;
  if (replace) window.history.replaceState(null, '', url);
  else window.history.pushState(null, '', url);
  listeners.forEach((listener) => listener());
}

/** Rotta della URL corrente. Una URL sconosciuta o non canonica è corretta sul posto, senza lasciare voci in più. */
export function useRoute(): Route {
  const url = useSyncExternalStore(subscribe, currentUrl);
  const route = useMemo(() => parseRoute(url), [url]);

  useEffect(() => {
    if (formatRoute(route) !== url) navigate(route, { replace: true });
  }, [route, url]);

  return route;
}
