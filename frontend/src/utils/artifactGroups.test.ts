import { describe, expect, it } from 'vitest';
import type { AutomationArtifact } from '../api/artifacts';
import { groupArtifactsByAge } from './artifactGroups';

const art = (id: string, created_at: string) => ({ artifact_id: id, created_at }) as AutomationArtifact;

describe('groupArtifactsByAge', () => {
  it('assegna ogni artefatto al primo gruppo che lo contiene, saltando quelli vuoti', () => {
    const now = new Date(2026, 9, 28, 15, 0); // mercoledì 28 ottobre
    const groups = groupArtifactsByAge(
      [
        art('oggi', new Date(2026, 9, 28, 0, 5).toISOString()),
        art('ieri', new Date(2026, 9, 27, 23, 59).toISOString()),
        art('settimana', new Date(2026, 9, 22, 12).toISOString()),
        art('mese', new Date(2026, 9, 2, 12).toISOString()),
        art('vecchio', new Date(2026, 8, 30, 12).toISOString()),
      ],
      now
    );
    expect(groups.map((g) => [g.title, g.items.map((a) => a.artifact_id)])).toEqual([
      ['Oggi', ['oggi']],
      ['Ieri', ['ieri']],
      ['Ultimi 7 Giorni', ['settimana']],
      ['Questo Mese', ['mese']],
      ['Precedenti', ['vecchio']],
    ]);
  });

  it('a inizio mese "Ultimi 7 giorni" ha la precedenza su "Questo mese"', () => {
    const groups = groupArtifactsByAge([art('a', new Date(2026, 9, 29, 12).toISOString())], new Date(2026, 10, 2, 10));
    expect(groups.map((g) => g.title)).toEqual(['Ultimi 7 Giorni']);
  });
});
