import { useCallback, useRef, useState } from 'react';
import type { ConfirmRequest } from '../components/ConfirmDialog';

/** Conferma asincrona: `await confirm({ message })` apre il `ConfirmDialog` e risolve con la risposta dell'utente. */
export function useConfirm() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const resolver = useRef<((confirmed: boolean) => void) | null>(null);

  const confirm = useCallback((req: ConfirmRequest) => {
    resolver.current?.(false);
    setRequest(req);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const answer = useCallback((confirmed: boolean) => {
    resolver.current?.(confirmed);
    resolver.current = null;
    setRequest(null);
  }, []);

  return { confirm, dialog: { request, onAnswer: answer } };
}
