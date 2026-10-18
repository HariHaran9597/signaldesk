import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const runtime = globalThis as typeof globalThis & { process?: { env?: Record<string, string | undefined> } }

export default defineConfig({
  base: runtime.process?.env?.VITE_BASE_PATH || '/',
  plugins: [react()],
  server: { port: 5173, strictPort: false, proxy: { '/api': 'http://127.0.0.1:8787', '/health': 'http://127.0.0.1:8787' } },
})
