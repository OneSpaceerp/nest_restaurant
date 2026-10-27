import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const APP = 'nest_restaurant'

// Staff PWA (/nest-restaurant/) and customer PWA (/nest-restaurant/customer/) share one build so they share
// chunks; the Desk bundle is built separately (vite.desk.config.ts) as a self-contained IIFE.
export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls: { includeAbsolute: false } } })],
  base: `/assets/${APP}/frontend/`,
  define: { __NEST_ASSET_ROOT__: JSON.stringify(`/assets/${APP}/frontend/`) },
  resolve: { alias: { '@shared': fileURLToPath(new URL('./src/shared', import.meta.url)) } },
  build: {
    outDir: `../${APP}/public/frontend`,
    emptyOutDir: true,
    target: 'es2020',
    sourcemap: false,
    rollupOptions: { input: { staff: 'staff.html', customer: 'customer.html' } },
  },
  server: {
    port: 8080,
    proxy: { '^/(api|assets|files|private|login|socket.io)': { target: 'http://127.0.0.1:8000', ws: true, changeOrigin: false } },
  },
})
