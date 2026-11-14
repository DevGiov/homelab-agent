/**
 * Fondi pieni con colore di stato e testo bianco: conferme distruttive, approvazioni, pausa, badge di conteggio.
 * Ogni tonalità dà almeno 4.5:1 col bianco, anche al passaggio del mouse, che scurisce di un grado. Sono uguali in ogni
 * tema: il plugin dei temi chiari (tailwind.config.js) cambia solo i fondi 900 e 950. Controllati in themes.test.ts.
 */
export const STATUS_FILL = {
  danger: 'bg-rose-600 text-white',
  success: 'bg-emerald-700 text-white',
  warning: 'bg-amber-700 text-white',
} as const;

/** Gli stessi fondi per i pulsanti, con il passaggio del mouse. */
export const STATUS_BUTTON = {
  danger: `${STATUS_FILL.danger} hover:bg-rose-700`,
  success: `${STATUS_FILL.success} hover:bg-emerald-800`,
  warning: `${STATUS_FILL.warning} hover:bg-amber-800`,
} as const;
