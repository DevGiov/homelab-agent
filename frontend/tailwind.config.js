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
          DEFAULT: 'var(--bg)',
          secondary: 'var(--bg-secondary)',
        },
        panel: {
          DEFAULT: 'var(--panel)',
          header: 'var(--panel-header)',
        },
        border: {
          DEFAULT: 'var(--border)',
          subtle: 'var(--border-subtle)',
        },
        fg: {
          DEFAULT: 'var(--fg)',
          muted: 'var(--fg-muted)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          subtle: 'var(--accent-subtle)',
        },
        userBubble: {
          DEFAULT: 'var(--user-bubble-bg)',
          text: 'var(--user-bubble-fg)',
        },
        agentBubble: {
          DEFAULT: 'var(--agent-bubble-bg)',
        },
        input: {
          bg: 'var(--input-bg)',
          border: 'var(--input-border)',
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
  plugins: [],
}
