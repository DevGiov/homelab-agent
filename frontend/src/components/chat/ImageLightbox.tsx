import React from 'react';
import { X } from 'lucide-react';

export const ImageLightbox: React.FC<{ url: string; onClose: () => void }> = ({ url, onClose }) => (
  <div
    className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200"
    onClick={onClose}
  >
    <div className="relative max-w-5xl max-h-[90vh] flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={onClose}
        className="absolute -top-10 right-0 p-1.5 rounded-full bg-panel text-fg hover:text-rose-400 hover:bg-panel-border transition cursor-pointer shadow-lg"
        title="Chiudi"
      >
        <X size={20} />
      </button>
      <img
        src={url}
        alt="Ingrandimento immagine"
        className="max-h-[85vh] max-w-full object-contain rounded-xl shadow-2xl border border-border"
      />
    </div>
  </div>
);
