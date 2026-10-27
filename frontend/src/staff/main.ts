import '@shared/app/fonts'
import { createApp, h } from 'vue'
import { startSurface } from '@shared/app/surface'
import { setCsrfToken } from '@shared/lib/api'
import App from './App.vue'
import { makeRouter } from './router'

const root = document.getElementById('app')!
startSurface({ app: 'nest_restaurant', surface: 'staff', root, swUrl: '/nest-restaurant/sw.js', scope: '/nest-restaurant/' })
if (import.meta.env.DEV) setCsrfToken(null)

const router = makeRouter('pwa')
createApp({ render: () => h(App, { root }) }).use(router).mount(root)
