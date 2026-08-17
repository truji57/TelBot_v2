import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5175,
    proxy: {
      '/api': 'http://localhost:8766',
      '/ws': {
        target: 'ws://localhost:8766',
        ws: true,
      },
    },
  },
})
