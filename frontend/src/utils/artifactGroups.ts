import type { AutomationArtifact } from '../api/artifacts';

const DAY_MS = 86_400_000;

export interface ArtifactGroup {
  key: string;
  title: string;
  items: AutomationArtifact[];
}

/** Raggruppa per età rispetto a `now`: Oggi, Ieri, Ultimi 7 giorni, Questo mese, Precedenti (gruppi vuoti esclusi). */
export function groupArtifactsByAge(artifacts: AutomationArtifact[], now = new Date()): ArtifactGroup[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const bounds: Array<[string, string, number]> = [
    ['today', 'Oggi', startOfToday],
    ['yesterday', 'Ieri', startOfToday - DAY_MS],
    ['last7Days', 'Ultimi 7 Giorni', startOfToday - 7 * DAY_MS],
    ['thisMonth', 'Questo Mese', new Date(now.getFullYear(), now.getMonth(), 1).getTime()],
    ['older', 'Precedenti', -Infinity],
  ];
  const groups = bounds.map(([key, title]) => ({ key, title, items: [] as AutomationArtifact[] }));

  for (const art of artifacts) {
    const created = art.created_at ? new Date(art.created_at).getTime() : 0;
    groups[bounds.findIndex(([, , from]) => created >= from)].items.push(art);
  }
  return groups.filter((g) => g.items.length > 0);
}
