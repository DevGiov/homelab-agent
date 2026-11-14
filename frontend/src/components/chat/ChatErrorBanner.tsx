import React from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * Avviso di errore sopra i messaggi. Il testo va a capo dentro la larghezza della chat, anche dentro un URL o una riga di
 * stack senza spazi (`overflow-wrap: anywhere`), e il pulsante resta visibile accanto.
 */
export const ChatErrorBanner: React.FC<{ message: string; onClose: () => void }> = ({ message, onClose }) => (
  <div className="bg-rose-950/80 border-b border-rose-800 px-4 sm:px-6 py-2.5 flex items-start justify-between gap-2 text-xs text-rose-200 shrink-0">
    <div className="flex items-start gap-2 min-w-0">
      <AlertTriangle size={16} className="text-rose-400 shrink-0" />
      <span className="min-w-0 [overflow-wrap:anywhere]" data-testid="chat-error-text">
        {message}
      </span>
    </div>
    <button type="button" onClick={onClose} className="text-rose-400 hover:text-rose-200 font-bold px-2 py-0.5 cursor-pointer shrink-0">
      Chiudi
    </button>
  </div>
);
