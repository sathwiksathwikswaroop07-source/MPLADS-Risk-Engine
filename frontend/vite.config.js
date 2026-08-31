import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend's CORS allow_origins lists :5173 only. If Vite silently falls
// back to 5174 because the port is busy, every API call fails CORS with a
// message that does not mention the port. strictPort turns that into an
// immediate, obvious startup error instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
