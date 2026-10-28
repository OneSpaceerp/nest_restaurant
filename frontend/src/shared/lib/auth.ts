// Sign-in for the staff PWAs through Frappe's own /api/method/login (password rules, lockouts, rate
// limits and two-factor all stay Frappe's). A Guest session has no CSRF token to check, so none is sent.

export type SignInResult = { status: 'ok' } | { status: 'otp'; tmpId: string; prompt: string }

export class SignInError extends Error {
  constructor(message: string, readonly kind: 'credentials' | 'rate' | 'offline' | 'server') {
    super(message)
  }
}

function serverMessage(body: Record<string, unknown>): string {
  try {
    if (typeof body._server_messages === 'string') {
      const last = (JSON.parse(body._server_messages) as string[]).at(-1)
      if (last) {
        const m = (JSON.parse(last) as { message?: string }).message ?? last
        return new DOMParser().parseFromString(m, 'text/html').body.textContent ?? ''
      }
    }
  } catch {
    /* fall through */
  }
  return typeof body.message === 'string' ? body.message : ''
}

export async function signIn(args: { usr: string; pwd: string } | { otp: string; tmpId: string }): Promise<SignInResult> {
  const payload = 'otp' in args ? { otp: args.otp, tmp_id: args.tmpId } : { usr: args.usr, pwd: args.pwd }
  let res: Response
  try {
    res = await fetch('/api/method/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new SignInError('No connection to the server.', 'offline')
  }
  let body: Record<string, unknown> = {}
  try {
    body = await res.json()
  } catch {
    /* proxy error page */
  }
  if (res.ok) {
    const verification = body.verification as { prompt?: string; method?: string } | undefined
    if (verification && typeof body.tmp_id === 'string') {
      return { status: 'otp', tmpId: body.tmp_id, prompt: verification.prompt || '' }
    }
    return { status: 'ok' }
  }
  if (res.status === 429) throw new SignInError('Too many attempts. Wait a minute and try again.', 'rate')
  if (res.status === 401 || res.status === 403 || res.status === 417) {
    throw new SignInError(serverMessage(body) || 'Wrong email or password.', 'credentials')
  }
  throw new SignInError(serverMessage(body) || 'The server could not sign you in. Try again.', 'server')
}

/** Frappe keeps the signed-in user in the user_id cookie ("Guest" once the session ends). */
export function cookieUser(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)user_id=([^;]*)/)
  return m ? decodeURIComponent(m[1]) : null
}

export function isSignedOut(): boolean {
  const boot = (window as unknown as { nest_boot?: { user?: string } }).nest_boot
  return (boot?.user ?? 'Guest') === 'Guest'
}
