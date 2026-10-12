import { defineConfig, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

// Two servers share the same /api proxy and host allow-list:
// - `server`  (vite dev): local development only, with hot reload;
// - `preview` (vite preview): the public link. It serves the compiled
//   `dist/` (scripts/deploy/build_frontend.sh) with no hot reload and no
//   access to source files; see deploy/README.md.
const BACKEND_URL = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8010'
const ALLOWED_HOSTS = ['.trycloudflare.com']

function apiProxy(): Record<string, ProxyOptions> {
  return {
    '/api': {
      target: BACKEND_URL,
      changeOrigin: true,
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    allowedHosts: ALLOWED_HOSTS,
    proxy: apiProxy(),
  },
  preview: {
    allowedHosts: ALLOWED_HOSTS,
    proxy: apiProxy(),
  },
})
