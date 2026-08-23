import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-time proxy to the FastAPI backend (uvicorn default port 8000) so the
// frontend never needs CORS headers added to backend/app.py — same-origin
// as far as the browser is concerned. Override with VITE_BACKEND_ORIGIN if
// the backend runs elsewhere.
const backendOrigin = process.env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: backendOrigin, changeOrigin: true },
    },
  },
})
