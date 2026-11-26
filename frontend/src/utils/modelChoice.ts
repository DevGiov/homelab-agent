// Scelta del modello per i lavori in background (step agentici delle automazioni, consolidamento della memoria, valutazioni).
// È la coppia (provider, modello) come per la chat. Nel form e nel backend è la stessa cosa, con null al posto di ''.
//   provider null  = il provider predefinito del server al momento dell'esecuzione (anche per i dati salvati prima dei provider)
//   model ''       = il modello predefinito di quel provider
//   model 'loaded' = il modello caricato sul provider quando il lavoro parte (un provider cloud non ne ha: vale il suo predefinito)

export const LOADED_MODEL = 'loaded';

export interface ModelChoice {
  provider: string | null;
  model: string;
}

/** Default del server: il modello predefinito del provider predefinito. */
export const DEFAULT_CHOICE: ModelChoice = { provider: null, model: '' };

/** Dalla coppia salvata (null = predefinito) alla scelta del form. */
export const choiceFromStored = (provider: string | null | undefined, model: string | null | undefined): ModelChoice => ({
  provider: provider || null,
  model: model || '',
});

/** Dalla scelta del form ai campi da salvare. */
export const storedFromChoice = (choice: ModelChoice): { provider: string | null; model: string | null } => ({
  provider: choice.provider,
  model: choice.model || null,
});

export function describeModelChoice(choice: ModelChoice): string {
  if (!choice.model) return choice.provider ? `modello di default di ${choice.provider}` : 'modello di default';
  if (choice.model === LOADED_MODEL) return choice.provider ? `modello caricato su ${choice.provider}` : 'modello caricato in quel momento';
  return choice.provider ? `${choice.model} (${choice.provider})` : choice.model;
}
