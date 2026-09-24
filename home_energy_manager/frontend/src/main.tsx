import './index.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// Fas 4b rollout diagnostic (2026-09-24): confirms a fresh git push actually
// reaches the frontend bundle Supervisor builds and serves. Safe to remove
// once the Nibe settings card is confirmed showing up in the live UI.
console.log('BUILD-DIAG-FAS4B-0002')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)