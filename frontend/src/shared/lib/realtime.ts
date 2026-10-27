// Frappe realtime (socket.io) with a polling fallback. Subscriptions are to document rooms, which
// Frappe only lets a client join after a read-permission check. Events are hints: on every event and
// on every reconnect the caller re-fetches authoritative state, so a missed event costs nothing.

import { ref } from 'vue'

export const connected = ref(false)

type Handler = (data: unknown) => void

interface SocketLike {
  on(ev: string, fn: (...a: unknown[]) => void): void
  emit(ev: string, ...a: unknown[]): void
  disconnect(): void
}

let socket: SocketLike | null = null
const rooms = new Set<string>()
const reconnectHooks = new Set<() => void>()

export async function connect(siteName: string, port?: number) {
  if (socket) return
  try {
    const { io } = await import('socket.io-client')
    const host = location.port && port && location.port !== String(port) && import.meta.env?.DEV ? `${location.hostname}:${port}` : location.host
    socket = io(`${location.protocol}//${host}/${siteName}`, { withCredentials: true, reconnectionAttempts: Infinity, transports: ['websocket', 'polling'] }) as unknown as SocketLike
    socket.on('connect', () => {
      connected.value = true
      for (const r of rooms) {
        const [doctype, name] = r.split('\u0000')
        socket!.emit('doc_subscribe', doctype, name)
      }
      for (const fn of reconnectHooks) fn()
    })
    socket.on('disconnect', () => (connected.value = false))
  } catch {
    connected.value = false
  }
}

export function subscribeDoc(doctype: string, name: string) {
  rooms.add(`${doctype}\u0000${name}`)
  socket?.emit('doc_subscribe', doctype, name)
  return () => {
    rooms.delete(`${doctype}\u0000${name}`)
    socket?.emit('doc_unsubscribe', doctype, name)
  }
}

export function on(event: string, fn: Handler) {
  socket?.on(event, fn as (...a: unknown[]) => void)
  return () => (socket as unknown as { off?: (e: string, f: Handler) => void })?.off?.(event, fn)
}

export function onReconnect(fn: () => void) {
  reconnectHooks.add(fn)
  return () => reconnectHooks.delete(fn)
}

/** Poll as a safety net; faster while disconnected, slow while realtime is healthy. */
export function poll(fn: () => Promise<unknown> | unknown, healthyMs = 30000, degradedMs = 5000) {
  let stopped = false
  let timer = 0
  const tick = async () => {
    if (stopped) return
    if (document.visibilityState === 'visible') {
      try {
        await fn()
      } catch {
        /* surfaced by the caller's own state */
      }
    }
    timer = window.setTimeout(tick, connected.value ? healthyMs : degradedMs)
  }
  timer = window.setTimeout(tick, connected.value ? healthyMs : degradedMs)
  return () => {
    stopped = true
    clearTimeout(timer)
  }
}
