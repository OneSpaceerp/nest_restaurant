// Frappe API client for the Nest PWAs and the Desk mount.
// Errors are classified so callers (and the outbox) can tell apart:
//   business  – the server understood and refused (validation, permission): do not retry blindly
//   transient – the request never reached a decision (offline, 502/503/504, rate limit): retry later
//   ambiguous – the request may have succeeded but the response was lost (timeout mid-flight):
//               retry with the SAME request key; the server's idempotency ledger resolves it

export type ErrorKind = 'business' | 'permission' | 'transient' | 'ambiguous' | 'conflict'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: ErrorKind,
    readonly status = 0,
    readonly excType = '',
    readonly title = '',
  ) {
    super(message)
  }
}

export interface ApiOptions {
  method?: 'GET' | 'POST'
  timeoutMs?: number
  signal?: AbortSignal
}

declare global {
  interface Window {
    csrf_token?: string
    nest_boot?: Record<string, unknown>
  }
}

let csrfOverride: string | null = null
export function setCsrfToken(token: string | null) {
  csrfOverride = token
}

function csrf(): string {
  const t = csrfOverride ?? window.csrf_token ?? ''
  return t && !t.includes('{{') ? t : ''
}

function stripHtml(s: string) {
  // DOMParser builds an inert document: no scripts run and no resources (img onerror) load.
  return new DOMParser().parseFromString(s, 'text/html').body.textContent ?? s
}

function messageFrom(body: Record<string, unknown>): { msg: string; title: string } {
  try {
    if (typeof body._server_messages === 'string') {
      const msgs = JSON.parse(body._server_messages) as string[]
      const parsed = msgs.map((m) => {
        try { return JSON.parse(m) as { message?: string; title?: string } } catch { return { message: m } }
      })
      const last = parsed.at(-1) ?? {}
      return { msg: stripHtml(last.message ?? ''), title: last.title ?? '' }
    }
  } catch {
    /* fall through */
  }
  return { msg: typeof body.message === 'string' ? body.message : 'Something went wrong on the server.', title: '' }
}

export async function call<T = unknown>(method: string, args: Record<string, unknown> = {}, opts: ApiOptions = {}): Promise<T> {
  const httpMethod = opts.method ?? 'POST'
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? 20000)
  opts.signal?.addEventListener('abort', () => controller.abort())
  let url = `/api/method/${method}`
  const init: RequestInit = {
    method: httpMethod,
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'X-Frappe-CSRF-Token': csrf() },
    signal: controller.signal,
  }
  if (httpMethod === 'GET') {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(args)) if (v !== undefined && v !== null) q.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v))
    url += `?${q}`
  } else {
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
    init.body = JSON.stringify(args)
  }
  let res: Response
  try {
    res = await fetch(url, init)
  } catch (e) {
    clearTimeout(timeout)
    const aborted = (e as Error).name === 'AbortError'
    if (opts.signal?.aborted) throw new ApiError('Cancelled', 'transient')
    // A timed-out POST may have been processed; a failed connection was not.
    throw new ApiError(
      aborted ? 'The server took too long to answer.' : 'No connection to the server.',
      aborted && httpMethod === 'POST' ? 'ambiguous' : 'transient',
    )
  }
  clearTimeout(timeout)
  let body: Record<string, unknown> = {}
  try {
    body = await res.json()
  } catch {
    /* non-JSON (proxy error page) */
  }
  if (res.ok) return body.message as T
  const { msg, title } = messageFrom(body)
  const exc = String(body.exc_type ?? '')
  if ([502, 503, 504].includes(res.status)) throw new ApiError('The server is busy. Trying again shortly.', 'transient', res.status, exc)
  if (res.status === 429) throw new ApiError('Too many requests. Wait a moment and try again.', 'transient', res.status, exc)
  if (res.status === 403 || exc === 'PermissionError' || exc === 'CSRFTokenError') throw new ApiError(msg || 'You do not have access to do this.', 'permission', res.status, exc, title)
  if (exc === 'RequestConflict') throw new ApiError(msg, 'conflict', res.status, exc, title)
  if (res.status >= 500 && !exc) throw new ApiError('The server hit a problem. Your work is kept; try again.', 'ambiguous', res.status, exc)
  throw new ApiError(msg, 'business', res.status, exc, title)
}

export function newKey(prefix = ''): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return prefix + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}
