import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        // The dev server runs inside the `frontend` container on the compose
        // network, so the API is reachable by its service name, not localhost.
        // Override with VITE_API_TARGET when running Vite directly on the host.
        target: process.env.VITE_API_TARGET || 'http://api:8000',
        changeOrigin: true,
      },
    },
  },
})
