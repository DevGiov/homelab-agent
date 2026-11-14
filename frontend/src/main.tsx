import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Font serviti dal bundle (nessuna richiesta a host esterni): pesi variabili, solo i sottoinsiemi usati vengono scaricati
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import App from './App.tsx'
import { initApiConfig } from './api/http';

// Carica config.json (API key iniettata a runtime) prima del render.
// In dev senza Docker, il fetch fallisce silenziosamente.
initApiConfig().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
