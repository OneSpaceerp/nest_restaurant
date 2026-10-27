// Mounted by the Desk page inside Frappe's own shell: the native Dock and module Sidebar stay on
// screen, this bundle renders only the page body. No service worker is registered from Desk.
import { createApp, h, type App as VueApp } from 'vue'
import { startSurface } from '@shared/app/surface'
import { setCsrfToken } from '@shared/lib/api'
import App from '../staff/App.vue'
import { makeRouter } from '../staff/router'

interface MountOptions { csrfToken?: string; user?: string; lang?: string; embedded?: boolean }

export function mount(el: HTMLElement, opts: MountOptions = {}) {
  setCsrfToken(opts.csrfToken ?? null)
  ;(window as unknown as { nest_boot: unknown }).nest_boot ??= { site_name: location.hostname, user: opts.user ?? '', lang: opts.lang ?? 'en' }
  const root = document.createElement('div')
  el.appendChild(root)
  startSurface({ app: 'nest_restaurant', surface: 'desk', root, standalone: false })
  const router = makeRouter('desk')
  const app: VueApp = createApp({ render: () => h(App, { root, embedded: opts.embedded ?? true }) })
  app.use(router)
  void router.push('/floor')
  app.mount(root)
  return {
    resume: () => router.currentRoute.value,
    unmount: () => app.unmount(),
  }
}
