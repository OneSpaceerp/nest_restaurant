/* Nest service worker template. postbuild.mjs fills the placeholders per app and per surface.
 *
 * Rules (frappe-desk-pwa / erpnext-v16-pwa-builder skills):
 * - scope is exactly this surface's route; requests outside it are never touched
 * - GET + same-origin only; never cache /api/ (app data lives in scoped IndexedDB), login or logout
 * - hashed build assets: cache-first; navigations: network-first with the cached shell offline
 * - versioned caches with this app's own prefix; activation deletes only our old versions
 * - a new worker waits until the page sends SKIP_WAITING (never mid-sale)
 */
const VERSION = '__VERSION__'
const PREFIX = '__PREFIX__'
const SCOPE = '__SCOPE__'
const EXCLUDE = __EXCLUDE__
const PRECACHE = __PRECACHE__
const ASSETS = PREFIX + VERSION + '-assets'
const SHELL = PREFIX + VERSION + '-shell'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(ASSETS).then((c) => c.addAll(PRECACHE)).catch(() => undefined),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith(PREFIX) && k !== ASSETS && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting()
  if (event.data && event.data.type === 'PURGE') event.waitUntil(caches.delete(SHELL))
})

function inScope(url) {
  if (!url.pathname.startsWith(SCOPE) && url.pathname + '/' !== SCOPE) return false
  return !EXCLUDE.some((p) => url.pathname.startsWith(p))
}

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/socket.io')) return

  if (req.mode === 'navigate') {
    if (!inScope(url)) return
    event.respondWith(
      (async () => {
        try {
          const controller = new AbortController()
          const timer = setTimeout(() => controller.abort(), 4000)
          const res = await fetch(req, { signal: controller.signal })
          clearTimeout(timer)
          if (res.ok && !res.redirected) {
            const copy = res.clone()
            caches.open(SHELL).then((c) => c.put(SCOPE, copy))
          }
          return res
        } catch (e) {
          const cached = await caches.match(SCOPE, { cacheName: SHELL })
          return cached || new Response('<h1>Offline</h1><p>Reconnect to open this page for the first time.</p>', { status: 503, headers: { 'Content-Type': 'text/html' } })
        }
      })(),
    )
    return
  }

  if (PRECACHE.includes(url.pathname) || url.pathname.startsWith(PRECACHE_ROOT())) {
    event.respondWith(
      caches.match(req, { cacheName: ASSETS }).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) caches.open(ASSETS).then((c) => c.put(req, res.clone()))
            return res
          }),
      ),
    )
  }
})

function PRECACHE_ROOT() {
  return '__ASSET_ROOT__'
}
