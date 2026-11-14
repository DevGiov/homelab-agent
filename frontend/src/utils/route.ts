// Percorsi dell'app: una URL per ogni vista e per ogni conversazione. Funzioni pure, la History API sta in useRoute.

export type AppView = 'chat' | 'automations' | 'calendar' | 'memory' | 'metrics';

export type Route =
  /** `threadId` null: una conversazione nuova, che riceve il suo id al primo messaggio. */
  | { view: 'chat'; threadId: string | null }
  /** `eventUid`: l'evento aperto da un link della chat. */
  | { view: 'calendar'; eventUid: string | null }
  | { view: 'automations' | 'memory' | 'metrics' };

export const APP_TITLE = 'Main-Agent UI';

export const VIEW_LABELS: Record<AppView, string> = {
  chat: 'Chat',
  automations: 'Automazioni',
  calendar: 'Calendario',
  memory: 'Memoria',
  metrics: 'Metriche',
};

/** Primo segmento del percorso delle viste diverse dalla chat, in italiano come l'interfaccia. */
const VIEW_SLUGS = {
  automations: 'automazioni',
  calendar: 'calendario',
  memory: 'memoria',
  metrics: 'metriche',
} as const satisfies Record<Exclude<AppView, 'chat'>, string>;

const SLUG_VIEWS = new Map<string, Exclude<AppView, 'chat'>>(
  Object.entries(VIEW_SLUGS).map(([view, slug]) => [slug, view as Exclude<AppView, 'chat'>]),
);

const THREAD_SEGMENT = 'c';
const EVENT_PARAM = 'evento';

/** La pagina iniziale: la chat su una conversazione nuova. */
export const HOME: Route = { view: 'chat', threadId: null };

/** Ingresso di una vista: la chat su una conversazione nuova, il calendario senza un evento aperto. */
export function viewRoute(view: AppView): Route {
  if (view === 'chat') return HOME;
  if (view === 'calendar') return { view, eventUid: null };
  return { view };
}

const decodeSegment = (segment: string): string | null => {
  try {
    return decodeURIComponent(segment);
  } catch {
    // Sequenza % non valida: la URL non nomina niente
    return null;
  }
};

/**
 * Rotta di un percorso con la sua query (`location.pathname + location.search`). Un percorso sconosciuto è la pagina
 * iniziale: chi lo riceve corregge la URL con `formatRoute`, che dà sempre la forma canonica.
 */
export function parseRoute(url: string): Route {
  const [pathAndQuery] = url.split('#', 1);
  const queryStart = pathAndQuery.indexOf('?');
  const rawPath = queryStart === -1 ? pathAndQuery : pathAndQuery.slice(0, queryStart);
  const query = queryStart === -1 ? '' : pathAndQuery.slice(queryStart + 1);
  // Una sola barra finale è tollerata: /memoria/ è /memoria
  const path = rawPath.length > 1 && rawPath.endsWith('/') ? rawPath.slice(0, -1) : rawPath;
  const segments = path.split('/').slice(1);

  if (segments.length === 2 && segments[0] === THREAD_SEGMENT) {
    const threadId = decodeSegment(segments[1]);
    return threadId ? { view: 'chat', threadId } : HOME;
  }
  if (segments.length === 1) {
    const view = SLUG_VIEWS.get(segments[0]);
    if (view === 'calendar') return { view, eventUid: new URLSearchParams(query).get(EVENT_PARAM) || null };
    if (view) return { view };
  }
  return HOME;
}

/** URL canonica di una rotta, relativa alla radice del sito. */
export function formatRoute(route: Route): string {
  switch (route.view) {
    case 'chat':
      return route.threadId ? `/${THREAD_SEGMENT}/${encodeURIComponent(route.threadId)}` : '/';
    case 'calendar':
      return route.eventUid
        ? `/${VIEW_SLUGS.calendar}?${new URLSearchParams({ [EVENT_PARAM]: route.eventUid })}`
        : `/${VIEW_SLUGS.calendar}`;
    default:
      return `/${VIEW_SLUGS[route.view]}`;
  }
}

/** Titolo della scheda del browser: il posto, poi il nome dell'app. */
export function documentTitle(route: Route, threadTitle?: string | null): string {
  const place =
    route.view === 'chat'
      ? route.threadId
        ? threadTitle || 'Conversazione'
        : 'Nuova conversazione'
      : VIEW_LABELS[route.view];
  return `${place} · ${APP_TITLE}`;
}

interface ClickLike {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  defaultPrevented: boolean;
}

/**
 * Clic su un link interno da gestire nella pagina: tasto sinistro senza modificatori. Gli altri (Ctrl o Cmd per una
 * nuova scheda, Maiusc per una nuova finestra) restano al browser, che apre l'`href` come un link qualsiasi.
 */
export function isPlainClick(e: ClickLike): boolean {
  return e.button === 0 && !e.defaultPrevented && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}
