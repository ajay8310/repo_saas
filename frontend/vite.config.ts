import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// API proxy target. Defaults to localhost for running `npm run dev` natively;
// inside docker-compose it is set to the API service name (http://api:8000).
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

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
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
