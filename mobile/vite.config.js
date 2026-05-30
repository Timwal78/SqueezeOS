import { defineConfig } from 'vite'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [
    nodePolyfills({
      globals: { Buffer: true, global: true, process: true },
      protocolImports: true,
    }),
  ],
  build: {
    lib: {
      entry: resolve(__dirname, 'src/main.js'),
      name: 'NOS',
      fileName: () => 'neural-os',
      formats: ['iife'],
    },
    outDir: 'www/js',
    emptyOutDir: true,
    target: 'es2020',
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
})
