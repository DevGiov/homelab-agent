/**
 * Scorrimento morbido salvo `prefers-reduced-motion: reduce`. Le chiamate JS con `behavior: 'smooth'`
 * non seguono lo `scroll-behavior` del CSS, quindi la preferenza va letta qui.
 */
export function scrollBehavior(): ScrollBehavior {
  const reduce = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  return reduce ? 'auto' : 'smooth';
}
