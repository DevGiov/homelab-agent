import React from 'react';
import { AlertCircle, Check } from 'lucide-react';
import type { FeedbackType } from '../hooks/useFeedback';

export const FeedbackToast: React.FC<{ feedback: { type: FeedbackType; text: string } | null }> = ({ feedback }) =>
  feedback && (
    <div
      className={`absolute top-14 right-4 z-50 px-3 py-1.5 rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-lg animate-in fade-in duration-200 max-w-[90vw] sm:max-w-sm ${
        feedback.type === 'success'
          ? 'bg-emerald-950/90 text-emerald-300 border border-emerald-800'
          : 'bg-rose-950/90 text-rose-300 border border-rose-800'
      }`}
    >
      {feedback.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
      <span className="truncate">{feedback.text}</span>
    </div>
  );
