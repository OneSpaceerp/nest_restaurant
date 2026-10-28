import '@shared/app/fonts'
import { createApp, h } from 'vue'
import { dismissSplash, startSurface } from '@shared/app/surface'
import NLogin from '@shared/components/NLogin.vue'
import { setCsrfToken } from '@shared/lib/api'
import { isSignedOut } from '@shared/lib/auth'
import App from './App.vue'
import { makeRouter } from './router'

const root = document.getElementById('app')!
startSurface({ app: 'nest_restaurant', surface: 'staff', root, swUrl: '/nest-restaurant/sw.js', scope: '/nest-restaurant/' })
if (import.meta.env.DEV) setCsrfToken(null)

if (isSignedOut()) {
  // signed out: the app's own sign-in screen; a successful sign-in reloads into the till
  createApp({ render: () => h(NLogin, { app: 'nest_restaurant', name: 'Nest Restaurant', tagline: 'Floor, kitchen and counter', logo: '/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e', brand: '#1e1d1d', root }) }).mount(root)
} else {
  const router = makeRouter('pwa')
  createApp({ render: () => h(App, { root }) }).use(router).mount(root)
  // the session ended while the till was open (expired, or signed out elsewhere): back to sign-in;
  // unsynced sales stay in this device's outbox and sync after signing in again
  window.addEventListener('nest:signed-out', () => location.reload(), { once: true })
}
dismissSplash()
