import React, { useRef, useState } from 'react';
import { AlertTriangle, Image as ImageIcon, Loader2, Paperclip, Pause, Play, Send, Square, X } from 'lucide-react';
import type { ImageAttachments } from '../../hooks/useImageAttachments';

interface ChatComposerProps {
  attachments: ImageAttachments;
  isLoading: boolean;
  isPaused: boolean;
  /** Modello scelto che probabilmente non supporta le immagini allegate, se c'è. */
  textOnlyModel: string | null;
  onSend: (text: string) => void;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onOpenImage: (url: string) => void;
}

/** Campo di input con anteprima delle immagini allegate e controlli di invio, pausa e stop. */
export const ChatComposer: React.FC<ChatComposerProps> = ({
  attachments,
  isLoading,
  isPaused,
  textOnlyModel,
  onSend,
  onStop,
  onPause,
  onResume,
  onOpenImage,
}) => {
  const [input, setInput] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { images, isProcessing } = attachments;
  const canSend = input.trim() !== '' || images.length > 0;

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!canSend || isLoading) return;
    onSend(input.trim());
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const openFilePicker = () => fileInputRef.current?.click();

  const placeholder = isLoading
    ? isPaused
      ? 'Esecuzione in pausa...'
      : 'Generazione in corso...'
    : images.length > 0
    ? "Aggiungi istruzioni per l'immagine o premi Invia per descriverla..."
    : 'Send message (incolla immagini con Ctrl+V)...';

  return (
    <>
      {images.length > 0 && textOnlyModel && (
        <div className="max-w-4xl mx-auto w-full px-1 text-[11px] text-amber-400/90 flex items-center gap-1.5">
          <AlertTriangle size={12} className="shrink-0" />
          <span>
            Il modello selezionato (<strong>{textOnlyModel}</strong>) potrebbe non supportare la visione. Ti consigliamo{' '}
            <strong>Qwen3.6-35B</strong>.
          </span>
        </div>
      )}

      {images.length > 0 && (
        <div className="max-w-4xl mx-auto w-full flex items-center gap-2 overflow-x-auto py-1 px-1">
          {images.map((img) => (
            <div
              key={img.id}
              className="relative group shrink-0 rounded-xl overflow-hidden border border-border bg-panel shadow-md flex items-center"
            >
              <img
                src={img.dataUrl}
                alt={img.name}
                className="h-14 w-14 sm:h-16 sm:w-16 object-cover cursor-pointer hover:opacity-90 transition"
                onClick={() => onOpenImage(img.dataUrl)}
                title="Clicca per ingrandire"
              />
              <button
                type="button"
                onClick={() => attachments.remove(img.id)}
                className="absolute top-1 right-1 p-0.5 rounded-full bg-black/70 text-white/90 hover:text-white hover:bg-rose-600 transition shadow cursor-pointer"
                title="Rimuovi immagine"
              >
                <X size={12} />
              </button>
              <div className="absolute bottom-0 inset-x-0 bg-black/60 px-1 py-0.5 text-[9px] text-white truncate max-w-[56px] sm:max-w-[64px]">
                {img.name}
              </div>
            </div>
          ))}
          {isProcessing && (
            <div className="h-14 sm:h-16 px-3 rounded-xl border border-dashed border-accent/40 bg-accent/10 flex items-center gap-2 text-accent text-xs shrink-0 animate-pulse">
              <Loader2 size={16} className="animate-spin" />
              <span>Ottimizzazione...</span>
            </div>
          )}
          <button
            type="button"
            onClick={openFilePicker}
            className="h-14 w-14 sm:h-16 sm:w-16 rounded-xl border border-dashed border-border hover:border-accent flex flex-col items-center justify-center text-fg-muted hover:text-accent transition shrink-0 bg-panel/40 cursor-pointer"
            title="Aggiungi altra immagine"
          >
            <Paperclip size={16} />
            <span className="text-[9px] mt-1">+ Altro</span>
          </button>
        </div>
      )}

      {isProcessing && images.length === 0 && (
        <div className="max-w-4xl mx-auto w-full mb-2 flex items-center gap-2 text-xs text-accent px-2">
          <Loader2 size={14} className="animate-spin" />
          <span>Elaborazione e ottimizzazione foto in corso...</span>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,image/heic,image/heif,.heic,.heif,image/*"
        multiple
        onChange={(e) => {
          if (e.target.files?.length) {
            attachments.addFiles(e.target.files);
            e.target.value = '';
          }
        }}
        className="hidden"
      />

      <form onSubmit={submit} className="max-w-4xl mx-auto w-full relative flex items-center">
        <button
          type="button"
          onClick={openFilePicker}
          disabled={isLoading}
          className="absolute left-2 sm:left-2.5 p-1.5 text-fg-muted hover:text-accent hover:bg-panel rounded-lg transition cursor-pointer z-10 disabled:opacity-40"
          title="Allega immagine (o trascina/incolla con Ctrl+V)"
        >
          <ImageIcon size={17} />
        </button>
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          disabled={isLoading}
          className="w-full bg-input-bg border border-input-border rounded-xl pl-9 sm:pl-10 pr-20 py-2.5 sm:py-3 text-xs sm:text-sm text-fg placeholder:text-fg-muted/50 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40 resize-none transition"
        />
        {isLoading ? (
          <div className="absolute right-1.5 sm:right-2 flex items-center gap-1">
            <button
              type="button"
              onClick={isPaused ? onResume : onPause}
              className={`p-1.5 sm:p-2 rounded-lg transition active:scale-95 shadow-md cursor-pointer ${
                isPaused
                  ? 'bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 border border-amber-500/40 shadow-amber-500/20'
                  : 'glass-card border border-border text-fg-muted hover:text-fg hover:border-accent/40'
              }`}
              title={isPaused ? 'Riprendi esecuzione' : 'Metti in pausa'}
            >
              {isPaused ? <Play size={14} className="fill-current text-amber-400" /> : <Pause size={14} />}
            </button>
            <button
              type="button"
              onClick={onStop}
              className="p-1.5 sm:p-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg transition active:scale-95 shadow-md shadow-rose-600/30 cursor-pointer"
              title="Interrompi esecuzione"
            >
              <Square size={14} className="fill-current" />
            </button>
          </div>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            className="absolute right-1.5 sm:right-2 p-1.5 sm:p-2 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:hover:bg-accent text-white rounded-lg transition active:scale-95 shadow-md shadow-accent/25 cursor-pointer"
            title={images.length > 0 && !input.trim() ? "Invia immagine per l'analisi automatica" : "Send Message"}
          >
            <Send size={15} />
          </button>
        )}
      </form>
    </>
  );
};
