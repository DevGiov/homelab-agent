/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          // React cambia solo con gli aggiornamenti delle dipendenze: chunk a parte che resta in cache tra i deploy
          groups: [{ name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ }],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    restoreMocks: true,
    unstubGlobals: true,
    // Vitest svuota i CSS importati; il testo grezzo (`index.css?raw`) serve ai test che ne controllano le regole
    css: { include: [/\.css\?raw$/] },
  },
})
