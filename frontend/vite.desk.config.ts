import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const APP = 'nest_restaurant'

// Loaded by the Desk page (nest_restaurant_service/page/nest_restaurant/nest_restaurant.js) with frappe.require().
export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls: { includeAbsolute: false } } })],
  resolve: { alias: { '@shared': fileURLToPath(new URL('./src/shared', import.meta.url)) } },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: `../${APP}/public/desk`,
    emptyOutDir: true,
    target: 'es2020',
    cssCodeSplit: false,
    lib: { entry: 'src/desk/main.ts', name: 'NestRestaurantDesk', formats: ['iife'], fileName: () => 'nest-restaurant-desk.js', cssFileName: 'nest-restaurant-desk' },
  },
})
