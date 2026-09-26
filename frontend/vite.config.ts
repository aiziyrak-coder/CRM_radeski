import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Local dev: proxy API to the backend container (docker compose publishes web on 9250)
    proxy: { '/api': 'http://127.0.0.1:9250' },
  },
})
