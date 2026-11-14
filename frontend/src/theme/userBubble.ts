/**
 * Pulsante pieno dentro il fumetto dell'utente (Invia, nella modifica del prompt): i colori del fumetto invertiti.
 * L'accento non basta: in ogni tema è vicino al fondo del fumetto (da 1.3:1 a 2.4:1) e il pulsante vi si confonde.
 * Invertiti, il fondo sul fumetto e il testo sul fondo hanno lo stesso rapporto del testo nel fumetto, che ogni tema tiene
 * ad almeno 4.5:1, anche col vetro smerigliato (themes.test.ts). Al passaggio del mouse cambia l'anello, non il fondo:
 * schiarito o velato, il fondo porterebbe il testo sotto 4.5:1.
 */
export const USER_BUBBLE_BUTTON = 'bg-userBubble-text text-userBubble hover:ring-2 hover:ring-userBubble-text/50';
