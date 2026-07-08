import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})
