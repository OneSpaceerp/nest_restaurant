// Exact decimal arithmetic for previews (BigInt scaled by 10^9). Matches the server's Decimal
// + ROUND_HALF_UP behaviour so a preview total equals the posted total in ordinary cases.

const SCALE = 9
const F = 10n ** BigInt(SCALE)

export class Dec {
  private constructor(readonly v: bigint) {}

  static of(x: Dec | string | number | bigint | null | undefined): Dec {
    if (x instanceof Dec) return x
    if (x === null || x === undefined || x === '') return new Dec(0n)
    if (typeof x === 'bigint') return new Dec(x * F)
    const s = typeof x === 'number' ? numToString(x) : x.trim()
    const m = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(s)
    if (!m || (m[2] === '' && (m[3] ?? '') === '')) throw new Error(`Not a number: ${s}`)
    const [, sign, int, frac = ''] = m
    const fracPadded = (frac + '0'.repeat(SCALE)).slice(0, SCALE)
    let v = BigInt(int || '0') * F + BigInt(fracPadded || '0')
    // round the dropped digits half-up
    if (frac.length > SCALE && Number(frac[SCALE]) >= 5) v += 1n
    return new Dec(sign === '-' ? -v : v)
  }

  static zero = new Dec(0n)

  plus(o: Dec | string | number): Dec { return new Dec(this.v + Dec.of(o).v) }
  minus(o: Dec | string | number): Dec { return new Dec(this.v - Dec.of(o).v) }
  times(o: Dec | string | number): Dec { return new Dec(divRound(this.v * Dec.of(o).v, F)) }
  div(o: Dec | string | number): Dec {
    const d = Dec.of(o).v
    if (d === 0n) throw new Error('Division by zero')
    return new Dec(divRound(this.v * F, d))
  }
  neg(): Dec { return new Dec(-this.v) }
  abs(): Dec { return this.v < 0n ? this.neg() : this }
  cmp(o: Dec | string | number): number { const d = this.v - Dec.of(o).v; return d === 0n ? 0 : d > 0n ? 1 : -1 }
  gt(o: Dec | string | number) { return this.cmp(o) > 0 }
  gte(o: Dec | string | number) { return this.cmp(o) >= 0 }
  lt(o: Dec | string | number) { return this.cmp(o) < 0 }
  lte(o: Dec | string | number) { return this.cmp(o) <= 0 }
  isZero() { return this.v === 0n }
  min(o: Dec | string | number) { return this.lte(o) ? this : Dec.of(o) }
  max(o: Dec | string | number) { return this.gte(o) ? this : Dec.of(o) }

  /** Round half-up (away from zero) to `places` decimals. */
  round(places: number): Dec {
    const q = 10n ** BigInt(SCALE - places)
    return new Dec(divRound(this.v, q) * q)
  }
  /** Floor toward zero to `places` decimals. */
  trunc(places: number): Dec {
    const q = 10n ** BigInt(SCALE - places)
    return new Dec((this.v / q) * q)
  }
  intPart(): bigint { return this.v / F }

  toFixed(places: number): string {
    const r = this.round(places).v
    const neg = r < 0n
    const a = neg ? -r : r
    const int = a / F
    const frac = (a % F).toString().padStart(SCALE, '0').slice(0, places)
    return `${neg ? '-' : ''}${int}${places ? '.' + frac : ''}`
  }
  toNumber(): number { return Number(this.toFixed(SCALE)) }
  toString(): string {
    const s = this.toFixed(SCALE)
    return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s
  }
}

function divRound(n: bigint, d: bigint): bigint {
  const q = n / d
  const r = n % d
  if (r === 0n) return q
  const twice = (r < 0n ? -r : r) * 2n
  const ad = d < 0n ? -d : d
  if (twice >= ad) return q + ((n < 0n) !== (d < 0n) ? -1n : 1n)
  return q
}

function numToString(n: number): string {
  if (!Number.isFinite(n)) throw new Error('Not a finite number')
  // avoid exponent notation for small/large values
  return Math.abs(n) < 1e-6 && n !== 0 ? n.toFixed(12) : String(n)
}

export const sum = (xs: Iterable<Dec>): Dec => {
  let t = Dec.zero
  for (const x of xs) t = t.plus(x)
  return t
}

/** Largest-remainder allocation; parts sum exactly to `total` (same algorithm as nest_core.money.allocate). */
export function allocate(total: Dec | string, weights: (Dec | string | number)[], places = 2): Dec[] {
  const t = Dec.of(total).round(places)
  const w = weights.map((x) => Dec.of(x))
  if (!w.length) return []
  let ws = sum(w)
  const ww = ws.isZero() ? w.map(() => Dec.of(1)) : w
  if (ws.isZero()) ws = Dec.of(w.length)
  const q = Dec.of(1).div(Dec.of(10n ** BigInt(places)))
  const sign = t.lt(0) ? -1 : 1
  const raw = ww.map((x) => t.times(x).div(ws))
  const floored = raw.map((r) => r.abs().trunc(places).times(sign))
  const rem = raw.map((r, i) => r.abs().minus(floored[i].abs()))
  let left = Number(t.abs().minus(sum(floored.map((f) => f.abs()))).div(q).toFixed(0))
  const order = raw.map((_, i) => i).sort((a, b) => rem[b].cmp(rem[a]) || a - b)
  for (const i of order) {
    if (left <= 0) break
    floored[i] = floored[i].plus(q.times(sign))
    left--
  }
  return floored
}
