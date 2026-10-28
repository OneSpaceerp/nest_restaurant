// Service worker registration and the safe update lifecycle: a new worker waits until the app says
// so, the app asks only when the person is idle (no sale in progress), and nothing unsynced is lost.

import { ref } from 'vue'

export const updateReady = ref(false)
export const installAvailable = ref(false)
let waiting: ServiceWorker | null = null
let deferredInstall: (Event & { prompt(): Promise<void> }) | null = null

export async function registerWorker(swUrl: string, scope: string) {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return null
  const reg = await navigator.serviceWorker.register(swUrl, { scope })
  const track = (w: ServiceWorker | null) => {
    if (!w) return
    w.addEventListener('statechange', () => {
      if (w.state === 'installed' && navigator.serviceWorker.controller) {
        waiting = w
        updateReady.value = true
      }
    })
  }
  if (reg.waiting && navigator.serviceWorker.controller) {
    waiting = reg.waiting
    updateReady.value = true
  }
  reg.addEventListener('updatefound', () => track(reg.installing))
  let reloading = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return
    reloading = true
    location.reload()
  })
  // check for updates when the app returns to the foreground
  document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && reg.update().catch(() => {}))
  if ('storage' in navigator && navigator.storage.persist) navigator.storage.persist().catch(() => {})
  return reg
}

/** Call only when it is safe (no open cart / unsent order). */
export function applyUpdate() {
  waiting?.postMessage({ type: 'SKIP_WAITING' })
}

window.addEventListener?.('beforeinstallprompt', (e) => {
  e.preventDefault()
  deferredInstall = e as typeof deferredInstall
  installAvailable.value = true
})

window.addEventListener?.('appinstalled', () => {
  deferredInstall = null
  installAvailable.value = false
})

export async function promptInstall() {
  if (!deferredInstall) return false
  await deferredInstall.prompt()
  deferredInstall = null
  installAvailable.value = false
  return true
}

export const isStandalone = () =>
  window.matchMedia?.('(display-mode: standalone)').matches || (navigator as unknown as { standalone?: boolean }).standalone === true

/** On logout or user switch: drop this app's runtime caches and local databases (not other apps'). */
export async function purgeLocal(appPrefix: string) {
  if ('caches' in window) {
    for (const k of await caches.keys()) if (k.startsWith(appPrefix) && !k.endsWith('-shell')) await caches.delete(k)
  }
  const dbs = (await (indexedDB as unknown as { databases?: () => Promise<{ name?: string }[]> }).databases?.()) ?? []
  for (const d of dbs) if (d.name?.startsWith(appPrefix)) indexedDB.deleteDatabase(d.name)
}
