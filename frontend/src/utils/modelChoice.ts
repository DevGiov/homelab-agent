// Scelta del modello per i lavori in background (step agentici delle automazioni, consolidamento della memoria).
// Nel form: '' = default del server, LOADED_MODEL = il modello caricato quando il lavoro parte, altrimenti il nome.
// Nel backend lo stesso valore, con null al posto di ''.

export const LOADED_MODEL = 'loaded';

export const choiceFromModel = (model: string | null | undefined): string => model || '';

export const modelFromChoice = (choice: string): string | null => choice || null;

export function describeModelChoice(model: string | null | undefined): string {
  if (!model) return 'modello di default';
  return model === LOADED_MODEL ? 'modello caricato in quel momento' : model;
}
