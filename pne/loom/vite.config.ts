import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8402',
        changeOrigin: true,
      },
      '/v1': {
        target: 'http://localhost:8402',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8402',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'esnext',
    minify: 'terser',
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          react: ['react', 'react-dom'],
        },
      },
    },
  },
})
