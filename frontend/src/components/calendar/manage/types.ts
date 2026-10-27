/** Esegue l'operazione di un form: mostra l'esito e, se riesce, torna all'elenco dei calendari. */
export type Submit = (action: () => Promise<string>, failure: string) => Promise<boolean>;

export interface ManageFormProps {
  submit: Submit;
  isBusy: boolean;
  /** Messaggio di errore di validazione, senza chiamare il backend. */
  invalid: (message: string) => void;
}
