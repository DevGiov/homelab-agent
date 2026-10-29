import React, { useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';

export interface ConfirmRequest {
  message: string;
  /** Testo del pulsante di conferma (default "Elimina"). */
  confirmLabel?: string;
}

interface ConfirmDialogProps {
  request: ConfirmRequest | null;
  onAnswer: (confirmed: boolean) => void;
}

/** Conferma di un'azione distruttiva dentro l'app: il `confirm()` nativo può essere soppresso dal browser senza avvisi. */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({ request, onAnswer }) => {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!request) return;
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onAnswer(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [request, onAnswer]);

  if (!request) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={() => onAnswer(false)}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label="Conferma"
        className="w-full max-w-sm rounded-xl border border-border bg-panel p-4 shadow-xl space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2.5">
          <AlertTriangle size={16} className="text-rose-400 shrink-0 mt-0.5" />
          <p className="text-xs text-fg leading-relaxed">{request.message}</p>
        </div>
        <div className="flex justify-end gap-1.5">
          <button onClick={() => onAnswer(false)} className="px-3 py-1.5 rounded-lg text-xs text-fg-muted hover:text-fg hover:bg-panel-hover cursor-pointer">
            Annulla
          </button>
          <button ref={confirmRef} onClick={() => onAnswer(true)} className="px-3 py-1.5 rounded-lg bg-rose-500 text-white text-xs font-semibold cursor-pointer">
            {request.confirmLabel ?? 'Elimina'}
          </button>
        </div>
      </div>
    </div>
  );
};
