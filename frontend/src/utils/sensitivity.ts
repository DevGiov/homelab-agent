// Sensibilità dei dati (backend: app/security/flows.py): etichette, testi e colori per la UI.

export type SensitivityLabel = 'public' | 'internal' | 'private' | 'secret';
/** Livelli che l'utente può scegliere per una conversazione, un fatto o un documento. */
export type SensitivityLevel = 'public' | 'internal' | 'private';

export interface SensitivityTag {
  label: SensitivityLabel;
  untrusted?: boolean;
  reasons?: string[];
}

export const LEVELS: SensitivityLevel[] = ['public', 'internal', 'private'];
const ORDER: Record<SensitivityLabel, number> = { public: 0, internal: 1, private: 2, secret: 3 };

export const LABEL_NAMES: Record<SensitivityLabel, string> = {
  public: 'Pubblici',
  internal: 'Interni',
  private: 'Privati',
  secret: 'Segreti',
};

export const LABEL_HINTS: Record<SensitivityLabel, string> = {
  public: 'Potrebbero stare online: possono andare alla ricerca web',
  internal: 'Tuoi, ma possono andare a un provider che hai scelto: non alla ricerca web',
  private: 'Solo modelli locali',
  secret: 'Nessun modello',
};

export const LABEL_CHIPS: Record<SensitivityLabel, string> = {
  public: 'bg-bg/60 border-border text-fg-muted',
  internal: 'bg-sky-500/15 border-sky-500/40 text-sky-300',
  private: 'bg-amber-500/15 border-amber-500/40 text-amber-300',
  secret: 'bg-rose-500/15 border-rose-500/40 text-rose-300',
};

export function compareLabels(a: SensitivityLabel, b: SensitivityLabel): number {
  return ORDER[a] - ORDER[b];
}

export function isLevel(value: unknown): value is SensitivityLevel {
  return value === 'public' || value === 'internal' || value === 'private';
}

/** L'etichetta più alta, i motivi dell'etichetta risultante e la non attendibilità di ognuno. */
export function joinTags(...tags: Array<SensitivityTag | null | undefined>): SensitivityTag {
  const parts = tags.filter((t): t is SensitivityTag => Boolean(t && t.label));
  if (parts.length === 0) return { label: 'public', untrusted: false, reasons: [] };
  const label = parts.reduce<SensitivityLabel>((best, t) => (compareLabels(t.label, best) > 0 ? t.label : best), 'public');
  const reasons: string[] = [];
  for (const t of parts) {
    for (const r of t.reasons ?? []) {
      if (!reasons.includes(r) && (t.label === label || r.startsWith('untrusted:'))) reasons.push(r);
    }
  }
  return { label, untrusted: parts.some((t) => t.untrusted), reasons };
}

const DETECTOR_NAMES: Record<string, string> = {
  secret: 'un segreto',
  iban: 'un IBAN',
  codice_fiscale: 'un codice fiscale',
  card: 'un numero di carta',
  phone: 'un numero di telefono',
  email: 'un indirizzo email',
  person: 'il nome di una persona della memoria',
  internal_address: 'un indirizzo della rete locale',
};

const MEMORY_NAMES: Record<string, string> = {
  profilo: 'il profilo utente',
  fatto: 'un fatto della memoria',
  episodio: "un'esecuzione passata",
  procedura: 'una procedura approvata',
  manutenzione: 'la manutenzione della memoria',
};

/** Un motivo del backend ("memoria:fatto", "tool:web_search", "messaggio:iban"...) in italiano. */
export function describeReason(reason: string): string {
  const untrusted = reason.startsWith('untrusted:');
  const raw = untrusted ? reason.slice('untrusted:'.length) : reason;
  const [kind, ...rest] = raw.split(':');
  const detail = rest.join(':');
  let text: string;
  if (kind === 'memoria') {
    // "memoria:episodio:iban": un rilevatore ha trovato un dato personale nell'elemento della memoria
    const [item, found] = detail.split(':');
    const base = MEMORY_NAMES[item] ?? `memoria (${item})`;
    text = found ? `${base} con ${DETECTOR_NAMES[found] ?? found}` : base;
  }
  else if (kind === 'tool') text = `risultato di ${detail}`;
  else if (kind === 'risultato') text = `dati trovati nel risultato di ${detail}`;
  else if (kind === 'messaggio' || kind === 'rilevatore') text = DETECTOR_NAMES[detail] ? `${DETECTOR_NAMES[detail]} nel messaggio` : 'un messaggio della conversazione';
  else if (kind === 'conversazione') text = 'il livello scelto per la conversazione';
  else if (kind === 'riassunto') text = 'il riassunto della conversazione';
  else if (kind === 'web_prefetch') text = 'pagine web della ricerca preventiva';
  else if (kind === 'immagine') text = 'un’immagine allegata';
  else if (kind === 'automazione') text = detail === 'webhook' ? 'dati arrivati da un webhook' : 'un’automazione';
  else text = raw;
  return untrusted ? `contenuto non attendibile: ${text}` : text;
}

/** Motivi senza doppioni, in italiano; quelli di non attendibilità a parte. */
export function describeTag(tag: SensitivityTag): { reasons: string[]; untrusted: string[] } {
  const reasons: string[] = [];
  const untrusted: string[] = [];
  for (const r of tag.reasons ?? []) {
    const text = describeReason(r);
    const bucket = r.startsWith('untrusted:') ? untrusted : reasons;
    if (!bucket.includes(text)) bucket.push(text);
  }
  return { reasons, untrusted };
}

export interface FlowCapability {
  destination: string;
  label: SensitivityLabel;
}

/** "flow:search:web:private" -> {destination: "search:web", label: "private"}; null se non è un'uscita di dati. */
export function parseFlowCapability(prefix?: string | null): FlowCapability | null {
  if (!prefix?.startsWith('flow:')) return null;
  const body = prefix.slice('flow:'.length);
  const cut = body.lastIndexOf(':');
  if (cut <= 0) return null;
  const label = body.slice(cut + 1) as SensitivityLabel;
  return ORDER[label] === undefined ? null : { destination: body.slice(0, cut), label };
}

/** Una destinazione in parole: "search:web" -> "la ricerca web (motori pubblici)". */
export function describeDestination(destination: string): string {
  const [kind, ...rest] = destination.split(':');
  const name = rest.join(':');
  if (kind === 'search') return 'la ricerca web (motori pubblici)';
  if (kind === 'http') return `il sito ${name}`;
  if (kind === 'mcp') return `il server MCP ${name}`;
  if (kind === 'provider') return `il provider di modelli ${name}`;
  if (kind === 'sandbox') return 'la sandbox del codice';
  return destination;
}

/** I server MCP di un catalogo: il prefisso dei nomi dei tool (`files` per `files__read`), senza doppioni e in ordine. */
export function serverScopes(toolNames: string[]): string[] {
  const scopes = new Set<string>();
  for (const name of toolNames) {
    const cut = name.indexOf('__');
    if (cut > 0) scopes.add(name.slice(0, cut));
  }
  return [...scopes].sort();
}
