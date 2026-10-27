import { useCallback, useEffect, useRef, useState } from 'react';

export type FeedbackType = 'success' | 'error';
export type Notify = (type: FeedbackType, text: string) => void;

/** Messaggio di esito di un'azione, visibile per 4 secondi. */
export function useFeedback() {
  const [feedback, setFeedback] = useState<{ type: FeedbackType; text: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  const notify: Notify = useCallback((type, text) => {
    setFeedback({ type, text });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setFeedback(null), 4000);
  }, []);

  return { feedback, notify };
}
