/**
 * Colore del tema da variabile CSS. Con color-mix i modificatori di opacità (`bg-accent/15`) funzionano
 * anche se le variabili sono esadecimali: Tailwind sostituisce `<alpha-value>` con l'opacità richiesta.
 */
const themed = (variable) => `color-mix(in srgb, var(${variable}) calc(<alpha-value> * 100%), transparent)`;

import plugin from 'tailwindcss/plugin';

const STATUS_HUES = ['emerald', 'green', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose', 'red', 'orange', 'amber', 'yellow', 'zinc'];
const OPACITIES = ['', ...Array.from({ length: 19 }, (_, i) => `/${(i + 1) * 5}`)];

/**
 * I colori di stato sono scritti per sfondi scuri (testi 100-400, fondi 900-950, bordi 700-900).
 * Sui temi chiari (body senza `.dark`) diventano testi 700, fondi tenui e bordi 300. Tailwind genera
 * solo le regole delle classi effettivamente usate nel codice, varianti (`hover:`…) comprese.
 */
const lightThemeStatusColors = plugin(({ addComponents, theme }) => {
  const esc = (cls) => cls.replace('/', '\\/');
  const rules = {};
  for (const hue of STATUS_HUES) {
    const shade = (n) => theme(`colors.${hue}.${n}`);
    for (const n of [100, 200, 300, 400]) {
      rules[`body:not(.dark) .text-${hue}-${n}`] = { color: shade(700) };
    }
    for (const opacity of OPACITIES) {
      for (const n of [900, 950]) {
        rules[`body:not(.dark) .${esc(`bg-${hue}-${n}${opacity}`)}`] = { backgroundColor: `color-mix(in srgb, ${shade(500)} 12%, transparent)` };
      }
      for (const n of [700, 800, 900]) {
        rules[`body:not(.dark) .${esc(`border-${hue}-${n}${opacity}`)}`] = { borderColor: shade(300) };
      }
    }
  }
  addComponents(rules);
});

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: themed('--bg'),
          secondary: themed('--bg-secondary'),
        },
        panel: {
          DEFAULT: themed('--panel'),
          header: themed('--panel-header'),
          // Superficie al passaggio del mouse: il pannello spostato di poco verso il colore del testo
          hover: themed('--panel-hover'),
        },
        border: {
          DEFAULT: themed('--border'),
          subtle: themed('--border-subtle'),
        },
        fg: {
          DEFAULT: themed('--fg'),
          muted: themed('--fg-muted'),
        },
        accent: {
          DEFAULT: themed('--accent'),
          hover: themed('--accent-hover'),
          subtle: themed('--accent-subtle'),
          contrast: '#ffffff',
        },
        userBubble: {
          DEFAULT: themed('--user-bubble-bg'),
          text: themed('--user-bubble-fg'),
        },
        agentBubble: {
          DEFAULT: themed('--agent-bubble-bg'),
        },
        input: {
          DEFAULT: themed('--input-bg'),
          bg: themed('--input-bg'),
          border: themed('--input-border'),
        },
        brand: {
          50: '#f0f7ff',
          100: '#e0effe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },
      },
      // Bordo di default (preflight) per gli elementi con `border` senza colore esplicito
      borderColor: {
        DEFAULT: 'var(--border)',
      },
      keyframes: {
        'ambient-slow': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '50%': { transform: 'translate3d(60px, 40px, 0) scale(1.08)' },
        },
        'ambient-reverse': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '50%': { transform: 'translate3d(-50px, -30px, 0) scale(1.12)' },
        },
        'ambient-pulse': {
          '0%, 100%': { opacity: '0.3', transform: 'scale(0.95)' },
          '50%': { opacity: '0.55', transform: 'scale(1.05)' },
        },
      },
      animation: {
        'ambient-slow': 'ambient-slow 24s ease-in-out infinite',
        'ambient-reverse': 'ambient-reverse 28s ease-in-out infinite',
        'ambient-pulse': 'ambient-pulse 16s ease-in-out infinite',
      },
    },
  },
  plugins: [lightThemeStatusColors],
}
