// Scanner input handling shared by keyboard-wedge scanners, phone cameras and paired phones.
// Pure functions + small classes so the behaviour is unit-tested without a camera or keyboard.

const AIM = /^\][A-Za-z][0-9A-Za-z]/
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x08\x0b-\x1c\x1e\x1f\x7f]/g
export const MAX_SCAN = 128

export function normaliseScan(raw: string): string | null {
  if (!raw) return null
  const v = raw.slice(0, MAX_SCAN).trim().replace(AIM, '').replace(CONTROL, '').trim()
  return v || null
}

export function gtinCheckDigit(body: string): number {
  let total = 0
  for (let i = 0; i < body.length; i++) {
    const digit = Number(body[body.length - 1 - i])
    total += digit * (i % 2 === 0 ? 3 : 1)
  }
  return (10 - (total % 10)) % 10
}

export function isValidGtin(code: string): boolean {
  return /^\d+$/.test(code) && [8, 12, 13, 14].includes(code.length) && gtinCheckDigit(code.slice(0, -1)) === Number(code.at(-1))
}

/**
 * Keyboard-wedge scanners type a whole code within a few milliseconds and finish with Enter.
 * People type slower. We classify a burst as a scan when it is long enough, fast enough and ends
 * with Enter — so the search box keeps working and scanning works without focusing anything.
 */
export class WedgeDetector {
  private buf = ''
  private first = 0
  private last = 0
  constructor(
    private readonly onScan: (code: string) => void,
    private readonly opts = { minLength: 4, maxGapMs: 35, maxTotalMsPerChar: 25 },
  ) {}

  /** Feed a keydown; returns true when the key was consumed as part of a scan. */
  key(key: string, t: number): boolean {
    if (key === 'Enter') {
      const code = this.buf
      const elapsed = this.last - this.first
      const fast = code.length >= this.opts.minLength && elapsed <= code.length * this.opts.maxTotalMsPerChar
      this.reset()
      if (fast) {
        const n = normaliseScan(code)
        if (n) this.onScan(n)
        return true
      }
      return false
    }
    if (key.length !== 1) return false
    if (this.buf && t - this.last > this.opts.maxGapMs) this.reset()
    if (!this.buf) this.first = t
    this.buf += key
    this.last = t
    return this.buf.length > 1 // swallow from the 2nd char on only while it still looks like a burst
  }

  reset() {
    this.buf = ''
    this.first = 0
    this.last = 0
  }
}

/**
 * A camera sees the same code on many consecutive frames. Accept a code once, then ignore it until
 * it has been out of view for `clearMs` (the item left the frame) or `repeatMs` has passed while the
 * user deliberately holds it there. A *different* code is always accepted immediately.
 */
export class FrameDeduper {
  private lastCode: string | null = null
  private acceptedAt = 0
  private lastSeen = 0
  constructor(private readonly clearMs = 700, private readonly repeatMs = 2500) {}

  accept(code: string, t: number): boolean {
    if (code !== this.lastCode) {
      this.lastCode = code
      this.acceptedAt = t
      this.lastSeen = t
      return true
    }
    const gone = t - this.lastSeen > this.clearMs
    const held = t - this.acceptedAt >= this.repeatMs
    this.lastSeen = t
    if (gone || held) {
      this.acceptedAt = t
      return true
    }
    return false
  }

  reset() {
    this.lastCode = null
  }
}

export type ScanOutcome =
  | { status: 'ok'; item_code: string; item_name: string; qty: string; uom?: string | null; rate?: number | null; price_override?: string | null; serial_no?: string | null; batch_no?: string | null }
  | { status: 'unknown'; code: string }
  | { status: 'ambiguous'; code: string; candidates: string[] }
  | { status: 'variant_required'; item_code: string; variants: string[] }
  | { status: 'unavailable' | 'invalid'; message?: string }

export interface CatalogItem {
  item_code: string
  item_name: string
  item_group?: string
  brand?: string | null
  rate: number | null
  stock_uom?: string
  image?: string | null
  barcodes: { barcode: string; uom?: string | null }[]
  available?: number | null
  has_serial_no?: number
  has_batch_no?: number
}

/** Offline-first local lookup: exact barcode, then GTIN forms, then exact item code. */
export function resolveLocally(code: string, items: CatalogItem[]): ScanOutcome {
  const n = normaliseScan(code)
  if (!n) return { status: 'invalid' }
  const keys = new Set([n])
  if (/^\d+$/.test(n) && [8, 12, 13, 14].includes(n.length)) {
    keys.add(n.padStart(14, '0'))
    const stripped = n.replace(/^0+/, '')
    for (const len of [13, 12, 8]) if (stripped.length <= len) keys.add(stripped.padStart(len, '0'))
  }
  const hits = new Map<string, { item: CatalogItem; uom?: string | null }>()
  for (const item of items) {
    for (const b of item.barcodes) if (keys.has(b.barcode)) hits.set(item.item_code, { item, uom: b.uom })
  }
  if (!hits.size) {
    const byCode = items.find((i) => i.item_code === n)
    if (byCode) hits.set(byCode.item_code, { item: byCode })
  }
  if (!hits.size) return { status: 'unknown', code: n }
  if (hits.size > 1) return { status: 'ambiguous', code: n, candidates: [...hits.keys()] }
  const [{ item, uom }] = hits.values()
  if (item.has_serial_no) return { status: 'unknown', code: n } // serials need the server
  return { status: 'ok', item_code: item.item_code, item_name: item.item_name, qty: '1', uom: uom ?? null, rate: item.rate }
}
