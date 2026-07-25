import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/static/frontend/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true
      }
    }
  },
  build: {
    outDir: '../static/frontend',
    // Build output is a deployment artifact and is intentionally ignored by Git.
    // Cleanup retains at most the current and previous manifests so open tabs can
    // finish lazy-loading while stale hashes are removed automatically.
    emptyOutDir: false,
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/zrender/')) return 'charts-renderer'
          if (id.includes('/node_modules/echarts/')) return 'charts'
          return undefined
        }
      }
    }
  }
})
