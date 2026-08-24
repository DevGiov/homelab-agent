import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initApiConfig } from './api'

// Carica config.json (API key iniettata a runtime) prima del render.
// In dev senza Docker, il fetch fallisce silenziosamente.
initApiConfig().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
