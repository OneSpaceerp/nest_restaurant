// Preview twin of nest_core/promotions.py. The server is authoritative; this exists so the cart can
// show the expected discount instantly (and offline). Both are checked against fixtures/promotions.json.

import { Dec, allocate, sum } from '../lib/decimal'

export type Kind = 'percent' | 'amount' | 'fixed_price' | 'bxgy' | 'spend_save' | 'bundle'

export interface PromoLine {
  line_id: string
  item_code: string
  qty: string
  rate: string
  item_group?: string
  brand?: string
}

export interface Promotion {
  name: string
  kind: Kind
  disabled?: boolean | number
  priority?: number
  exclusive?: boolean | number
  stackable?: boolean | number
  value?: string | number
  buy_qty?: number
  get_qty?: number
  get_discount_percent?: string | number | null
  threshold?: string | number
  discount_amount?: string | number
  repeat?: boolean | number
  bundle_price?: string | number
  bundle_items?: { item_code: string; qty: string | number }[]
  valid_from?: string | null
  valid_to?: string | null
  days_of_week?: number[]
  time_from?: string | null
  time_to?: string | null
  customer_groups?: string[]
  profiles?: string[]
  coupon_code?: string | null
  min_qty?: string | number | null
  min_amount?: string | number | null
  max_applications?: number | null
  applies_to?: { items?: string[]; item_groups?: string[]; brands?: string[] }
}

export interface Context {
  at: Date
  customerGroup?: string
  profile?: string
  coupons?: string[]
}

export interface Result {
  lineDiscounts: Record<string, string>
  totalDiscount: string
  applied: { promotion: string; line_id: string; amount: string }[]
  rejectedCoupons: string[]
}

const KINDS = new Set<Kind>(['percent', 'amount', 'fixed_price', 'bxgy', 'spend_save', 'bundle'])

const gross = (l: PromoLine) => Dec.of(l.qty).times(l.rate)

function minutes(t: string) {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}

function isoDate(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function isActive(p: Promotion, ctx: Context): boolean {
  if (p.disabled) return false
  const day = isoDate(ctx.at)
  if (p.valid_from && day < p.valid_from) return false
  if (p.valid_to && day > p.valid_to) return false
  const weekday = (ctx.at.getDay() + 6) % 7 // Monday = 0, like Python
  if (p.days_of_week?.length && !p.days_of_week.includes(weekday)) return false
  if (p.time_from && p.time_to) {
    const now = ctx.at.getHours() * 60 + ctx.at.getMinutes()
    const s = minutes(p.time_from)
    const e = minutes(p.time_to)
    const within = s <= e ? now >= s && now < e : now >= s || now < e
    if (!within) return false
  }
  if (p.customer_groups?.length && !p.customer_groups.includes(ctx.customerGroup ?? '')) return false
  if (p.profiles?.length && !p.profiles.includes(ctx.profile ?? '')) return false
  if (p.coupon_code) {
    const have = new Set((ctx.coupons ?? []).map((c) => c.toUpperCase()))
    if (!have.has(p.coupon_code.toUpperCase())) return false
  }
  return true
}

function eligible(p: Promotion, l: PromoLine) {
  const s = p.applies_to ?? {}
  if (!s.items?.length && !s.item_groups?.length && !s.brands?.length) return true
  return Boolean(
    s.items?.includes(l.item_code) || (l.item_group && s.item_groups?.includes(l.item_group)) || (l.brand && s.brands?.includes(l.brand)),
  )
}

function perLine(p: Promotion, lines: PromoLine[], places: number): Map<string, Dec> {
  const out = new Map<string, Dec>()
  const value = Dec.of(p.value ?? 0)
  if (p.min_qty && sum(lines.map((l) => Dec.of(l.qty))).lt(p.min_qty)) return out
  if (p.min_amount && sum(lines.map(gross)).lt(p.min_amount)) return out
  switch (p.kind) {
    case 'percent':
      for (const l of lines) out.set(l.line_id, gross(l).times(value).div(100).round(places))
      break
    case 'amount':
      for (const l of lines) out.set(l.line_id, value.min(l.rate).times(l.qty).round(places))
      break
    case 'fixed_price':
      for (const l of lines) if (Dec.of(l.rate).gt(value)) out.set(l.line_id, Dec.of(l.rate).minus(value).times(l.qty).round(places))
      break
    case 'bxgy': {
      const buy = p.buy_qty ?? 0
      const get = p.get_qty ?? 0
      const pct = Dec.of(p.get_discount_percent ?? 100)
      const units: { rate: Dec; id: string }[] = []
      for (const l of lines) for (let i = 0n; i < Dec.of(l.qty).intPart(); i++) units.push({ rate: Dec.of(l.rate), id: l.line_id })
      let groups = Math.floor(units.length / (buy + get))
      if (p.max_applications) groups = Math.min(groups, p.max_applications)
      units.sort((a, b) => a.rate.cmp(b.rate) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
      for (const u of units.slice(0, groups * get)) out.set(u.id, (out.get(u.id) ?? Dec.zero).plus(u.rate.times(pct).div(100)))
      for (const [k, v] of out) out.set(k, v.round(places))
      break
    }
    case 'spend_save': {
      const threshold = Dec.of(p.threshold ?? 0)
      const total = sum(lines.map(gross))
      if (threshold.gt(0) && total.gte(threshold)) {
        const times = p.repeat ? total.div(threshold).trunc(0) : Dec.of(1)
        const amount = Dec.of(p.discount_amount ?? 0).times(times).min(total)
        allocate(amount, lines.map(gross), places).forEach((part, i) => { if (!part.isZero()) out.set(lines[i].line_id, part) })
      }
      break
    }
    case 'bundle': {
      const need = new Map((p.bundle_items ?? []).map((b) => [b.item_code, Dec.of(b.qty)]))
      const have = new Map<string, Dec>()
      for (const l of lines) have.set(l.item_code, (have.get(l.item_code) ?? Dec.zero).plus(l.qty))
      let sets = Infinity
      for (const [code, q] of need) sets = Math.min(sets, Number((have.get(code) ?? Dec.zero).div(q).trunc(0).toFixed(0)))
      if (!Number.isFinite(sets) || sets <= 0) break
      const remaining = new Map([...need].map(([c, q]) => [c, q.times(sets)]))
      const consumed: [PromoLine, Dec][] = []
      for (const l of lines) {
        if (!need.has(l.item_code)) continue
        const take = Dec.of(l.qty).min(remaining.get(l.item_code)!)
        if (take.gt(0)) {
          consumed.push([l, take])
          remaining.set(l.item_code, remaining.get(l.item_code)!.minus(take))
        }
      }
      const atPrice = sum(consumed.map(([l, q]) => Dec.of(l.rate).times(q)))
      const discount = atPrice.minus(Dec.of(p.bundle_price ?? 0).times(sets)).max(0)
      allocate(discount, consumed.map(([l, q]) => Dec.of(l.rate).times(q)), places).forEach((part, i) => {
        const id = consumed[i][0].line_id
        if (!part.isZero()) out.set(id, (out.get(id) ?? Dec.zero).plus(part))
      })
      break
    }
  }
  for (const [k, v] of out) if (!v.gt(0)) out.delete(k)
  return out
}

export function evaluate(lines: PromoLine[], promotions: Promotion[], ctx: Context, places = 2): Result {
  const byId = new Map(lines.map((l) => [l.line_id, l]))
  const discount = new Map(lines.map((l) => [l.line_id, Dec.zero]))
  const locked = new Set<string>()
  const taken = new Set<string>()
  const applied: Result['applied'] = []
  const couponPromos = new Set(promotions.filter((p) => p.coupon_code).map((p) => p.coupon_code!.toUpperCase()))
  const rejectedCoupons = (ctx.coupons ?? []).filter((c) => !couponPromos.has(c.toUpperCase())).sort()

  const ordered = promotions
    .filter((p) => KINDS.has(p.kind) && isActive(p, ctx))
    .sort((a, b) => (a.exclusive ? 0 : 1) - (b.exclusive ? 0 : 1) || (a.priority ?? 100) - (b.priority ?? 100) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))

  for (const p of ordered) {
    const stackable = Boolean(p.stackable) && !p.exclusive
    const candidates = lines.filter(
      (l) => eligible(p, l) && !locked.has(l.line_id) && (stackable || !taken.has(l.line_id)) && Dec.of(l.qty).gt(0),
    )
    if (!candidates.length) continue
    for (const [id, amt0] of perLine(p, candidates, places)) {
      const room = gross(byId.get(id)!).minus(discount.get(id)!)
      const amt = amt0.min(room.max(0))
      if (!amt.gt(0)) continue
      discount.set(id, discount.get(id)!.plus(amt))
      applied.push({ promotion: p.name, line_id: id, amount: amt.toFixed(places) })
      if (p.exclusive) locked.add(id)
      if (!stackable) taken.add(id)
    }
  }
  const lineDiscounts: Record<string, string> = {}
  for (const [k, v] of discount) if (v.gt(0)) lineDiscounts[k] = v.round(places).toFixed(places)
  return {
    lineDiscounts,
    totalDiscount: sum(Object.values(lineDiscounts).map((v) => Dec.of(v))).toFixed(places),
    applied,
    rejectedCoupons,
  }
}
