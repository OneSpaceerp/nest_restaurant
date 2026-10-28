// Till state shared by Nest POS (Sell) and Nest Restaurant (counter). One instance per app.
// - bootstrap, register choice and shift
// - offline catalog snapshot in IndexedDB (scoped by app/site/user/register)
// - cart with instant preview totals; authoritative quote from the server when online
// - submit online, or queue a cash sale in the durable outbox when offline and allowed

import { computed, reactive, ref, watch } from 'vue'
import { ApiError, call, newKey } from '../lib/api'
import { Dec, sum } from '../lib/decimal'
import { dbName, idb, openDb } from '../lib/idb'
import { Outbox, type OutboxEntry } from '../lib/outbox'
import { resolveLocally, type CatalogItem, type ScanOutcome } from '../lib/scan'
import { evaluate, type Promotion } from '../pricing/promotions'

export interface PaymentMode { mode_of_payment: string; default: number; type: 'Cash' | 'Bank' | 'General' | 'Phone' | string }
export interface RegisterInfo {
  register: string
  company: string
  pos_profile: string
  currency: string
  invoice_mode: 'Direct' | 'Consolidated'
  blind_close: number
  payment_modes: PaymentMode[]
  default_customer: string
  session: string | null
  outlet_label?: string
  print_format?: string | null
  letter_head?: string | null
}

/** Desk print view for an invoice: the POS Profile's print format and letter head when set, otherwise the
 *  app's own receipt format (`fallbackFormat`, e.g. "Nest POS Receipt"). */
export function receiptUrl(reg: RegisterInfo | null, doctype: string, name: string, fallbackFormat?: string) {
  const q = new URLSearchParams({ doctype, name, trigger_print: '1' })
  const format = reg?.print_format || fallbackFormat
  if (format) q.set('format', format)
  if (reg?.letter_head) q.set('letterhead', reg.letter_head)
  else q.set('no_letterhead', '0')
  return `/printview?${q}`
}
export interface Boot {
  user: string
  full_name: string
  roles: Record<string, boolean>
  registers: RegisterInfo[]
  settings: { pricing_authority: 'native' | 'nest'; allow_offline_cash_sales: number; offline_max_hours: number; offline_max_sale_value: number; cash_rounding_increment: number }
  return_reasons: { reason: string; needs_approval: number }[]
}
export interface CartLine {
  line_id: string
  item_code: string
  item_name: string
  qty: number
  rate: number | null
  uom?: string | null
  item_group?: string
  serial_nos?: string[]
  batch_no?: string | null
  rate_override?: string | null
  discount_percent?: number
  note?: string
}
export interface Quote {
  amount_due: number
  net_total: number
  total_taxes_and_charges: number
  discount_amount: number
  grand_total: number
  currency: string
  lines: { item_code: string; rate: number; amount: number; discount_amount: number }[]
}

export function createTill(app: 'nest_pos' | 'nest_restaurant', site: string) {
  const api = (m: string) => `${app}.api.staff.${m}`
  const boot = ref<Boot | null>(null)
  const registerName = ref<string | null>(null)
  const online = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
  const catalog = ref<CatalogItem[]>([])
  const catalogState = ref<'empty' | 'loading' | 'ready' | 'stale' | 'error'>('empty')
  const promotions = ref<Promotion[]>([])
  const outboxEntries = ref<OutboxEntry[]>([])
  const syncing = ref(false)
  let db: IDBDatabase | null = null
  let outbox: Outbox | null = null

  const register = computed(() => boot.value?.registers.find((r) => r.register === registerName.value) ?? null)
  const sessionOpen = computed(() => Boolean(register.value?.session))

  const cart = reactive({
    id: newKey('cart-'),
    lines: [] as CartLine[],
    customer: null as string | null,
    customerName: null as string | null,
    coupons: [] as string[],
    basket: null as string | null,
    note: '',
  })
  const quote = ref<Quote | null>(null)
  const quoteState = ref<'idle' | 'loading' | 'fresh' | 'stale' | 'error'>('idle')
  const quoteError = ref('')

  if (typeof window !== 'undefined') {
    window.addEventListener('online', () => { online.value = true; void outbox?.flush() })
    window.addEventListener('offline', () => (online.value = false))
  }

  async function loadBoot() {
    boot.value = await call<Boot>(api('bootstrap'), {}, { method: 'GET' })
    const remembered = localStorage.getItem(`${app}:register`)
    const choices = boot.value.registers
    registerName.value = choices.find((r) => r.register === remembered)?.register ?? (choices.length === 1 ? choices[0].register : null)
    if (registerName.value) await useRegister(registerName.value)
  }

  async function useRegister(name: string) {
    registerName.value = name
    try { localStorage.setItem(`${app}:register`, name) } catch { /* private mode */ }
    db?.close()
    db = await openDb(dbName(app, site, boot.value?.user ?? 'unknown', name))
    outbox = new Outbox(db, sendEntry, `${app}:${site}:${name}:outbox`)
    outbox.subscribe((e) => (outboxEntries.value = e))
    const saved = await idb.get<{ id: string; lines: CartLine[]; customer: string | null; customerName?: string | null; basket: string | null }>(db, 'carts', 'active')
    if (saved?.lines?.length) Object.assign(cart, { id: saved.id, lines: saved.lines, customer: saved.customer, customerName: saved.customerName ?? null, basket: saved.basket })
    await loadCatalog()
    void outbox.flush()
  }

  async function loadCatalog() {
    if (!db || !registerName.value) return
    const cached = await idb.all<CatalogItem>(db, 'catalog')
    if (cached.length) {
      catalog.value = cached
      catalogState.value = 'stale'
    } else {
      catalogState.value = 'loading'
    }
    try {
      const all: CatalogItem[] = []
      let start: number | null = 0
      while (start !== null) {
        const page: { items: CatalogItem[]; next_start: number | null } = await call(api('catalog_page'), { register_name: registerName.value, start }, { method: 'GET' })
        all.push(...page.items)
        start = page.next_start
      }
      catalog.value = all
      await idb.clear(db, 'catalog')
      await idb.putMany(db, 'catalog', all)
      await idb.put(db, 'meta', { k: 'catalog_at', v: Date.now() })
      catalogState.value = 'ready'
      if (boot.value?.settings.pricing_authority === 'nest') {
        promotions.value = await call<Promotion[]>(api('promotions'), { register_name: registerName.value }, { method: 'GET' })
      }
    } catch (e) {
      catalogState.value = cached.length ? 'stale' : 'error'
      if (!(e instanceof ApiError) || e.kind !== 'transient') throw e
    }
  }

  // ---------------------------------------------------------------- cart
  function addItem(item: { item_code: string; item_name: string; rate: number | null; uom?: string | null; item_group?: string }, qty = 1, extra: Partial<CartLine> = {}) {
    const mergeable = !extra.serial_nos?.length && !extra.batch_no && !extra.rate_override
    const existing = mergeable ? cart.lines.find((l) => l.item_code === item.item_code && (l.uom ?? null) === (item.uom ?? null) && !l.serial_nos?.length && !l.rate_override && !l.note) : null
    if (existing) existing.qty = Math.round((existing.qty + qty) * 1000) / 1000
    else cart.lines.push({ line_id: newKey('l'), item_code: item.item_code, item_name: item.item_name, qty, rate: item.rate, uom: item.uom, item_group: item.item_group, ...extra })
  }

  function setQty(lineId: string, qty: number) {
    const i = cart.lines.findIndex((l) => l.line_id === lineId)
    if (i < 0) return
    if (qty <= 0) cart.lines.splice(i, 1)
    else cart.lines[i].qty = qty
  }

  function clearCart() {
    Object.assign(cart, { id: newKey('cart-'), lines: [], customer: null, customerName: null, coupons: [], basket: null, note: '' })
    quote.value = null
    quoteState.value = 'idle'
  }

  /** Scan → item. Local snapshot first (instant, works offline); the server for serials/batches/weights/unknowns. */
  async function scan(code: string): Promise<ScanOutcome> {
    const local = resolveLocally(code, catalog.value)
    if (local.status === 'ok') {
      const item = catalog.value.find((i) => i.item_code === local.item_code)!
      addItem({ ...item, uom: local.uom ?? null })
      return local
    }
    if (!online.value) return local
    const remote = await call<ScanOutcome>(api('resolve_scan'), { register_name: registerName.value, code }, { method: 'GET', timeoutMs: 6000 })
    if (remote.status === 'ok') {
      const item = catalog.value.find((i) => i.item_code === remote.item_code)
      addItem(
        { item_code: remote.item_code, item_name: remote.item_name, rate: remote.rate ?? item?.rate ?? null, uom: remote.uom ?? null, item_group: item?.item_group },
        Number(remote.qty) || 1,
        { serial_nos: remote.serial_no ? [remote.serial_no] : undefined, batch_no: remote.batch_no ?? null, rate_override: remote.price_override ?? null },
      )
    }
    return remote
  }

  // ---------------------------------------------------------------- previews
  const preview = computed(() => {
    const places = 2
    const lines = cart.lines.map((l) => ({ line_id: l.line_id, item_code: l.item_code, qty: String(l.qty), rate: String(l.rate_override ?? l.rate ?? 0), item_group: l.item_group }))
    const promo = boot.value?.settings.pricing_authority === 'nest' ? evaluate(lines, promotions.value, { at: new Date(), coupons: cart.coupons }, places) : null
    const gross = sum(lines.map((l) => Dec.of(l.qty).times(l.rate)))
    const discount = Dec.of(promo?.totalDiscount ?? 0)
    return { gross: gross.toFixed(places), discount: discount.toFixed(places), total: gross.minus(discount).toFixed(places), lineDiscounts: promo?.lineDiscounts ?? {} }
  })
  const itemCount = computed(() => cart.lines.reduce((n, l) => n + l.qty, 0))

  function payload(extra: Record<string, unknown> = {}) {
    return {
      session: register.value?.session,
      customer: cart.customer,
      coupons: cart.coupons,
      basket: cart.basket,
      note: cart.note,
      lines: cart.lines.map((l) => ({ line_id: l.line_id, item_code: l.item_code, qty: l.qty, uom: l.uom, serial_nos: l.serial_nos, batch_no: l.batch_no, rate_override: l.rate_override, discount_percent: l.discount_percent, note: l.note })),
      ...extra,
    }
  }

  let quoteTimer = 0
  let quoteSeq = 0
  async function refreshQuote() {
    if (!cart.lines.length || !sessionOpen.value) { quote.value = null; quoteState.value = 'idle'; return }
    if (!online.value) { quoteState.value = 'stale'; return }
    const seq = ++quoteSeq
    quoteState.value = 'loading'
    try {
      const q = await call<Quote>(api('quote'), { register_name: registerName.value, payload: payload() }, { timeoutMs: 8000 })
      if (seq !== quoteSeq) return // a newer edit superseded this quote
      quote.value = q
      quoteState.value = 'fresh'
      quoteError.value = ''
    } catch (e) {
      if (seq !== quoteSeq) return
      quoteState.value = e instanceof ApiError && e.kind === 'business' ? 'error' : 'stale'
      quoteError.value = e instanceof Error ? e.message : String(e)
    }
  }
  watch(
    () => JSON.stringify([cart.lines, cart.customer, cart.coupons]),
    () => {
      quoteState.value = cart.lines.length ? 'loading' : 'idle'
      clearTimeout(quoteTimer)
      quoteTimer = window.setTimeout(refreshQuote, 350)
      if (db) void idb.put(db, 'carts', { id: 'active', lines: JSON.parse(JSON.stringify(cart.lines)), customer: cart.customer, customerName: cart.customerName, basket: cart.basket, cartId: cart.id })
    },
  )

  // ---------------------------------------------------------------- submit
  async function sendEntry(e: OutboxEntry) {
    return call(api('submit_sale'), { register_name: registerName.value, payload: e.payload, request_key: e.key, source: 'Offline replay' }, { timeoutMs: 30000 })
  }

  /** Online: post now with a stable key (retries reuse it). Offline: queue a cash-only sale if policy allows. */
  async function submit(tenders: { mode_of_payment: string; amount: string }[], opts: { onAccount?: boolean; approval?: string } = {}) {
    const key = newKey('sale-')
    const body = payload({ tenders, on_account: opts.onAccount, approval: opts.approval, client_created_at: new Date().toISOString().replace('T', ' ').slice(0, 19) })
    if (online.value) {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const res = await call<{ status: string; invoice?: { name: string; amount_due: number }; change?: string }>(api('submit_sale'), { register_name: registerName.value, payload: body, request_key: key }, { timeoutMs: 30000 })
          clearCart()
          return { mode: 'online' as const, ...res }
        } catch (e) {
          if (e instanceof ApiError && e.kind === 'ambiguous') continue // same key: the ledger answers
          if (e instanceof ApiError && e.kind === 'transient') break
          throw e
        }
      }
    }
    const settings = boot.value!.settings
    const cashModes = new Set(register.value!.payment_modes.filter((m) => m.type === 'Cash').map((m) => m.mode_of_payment))
    if (!settings.allow_offline_cash_sales) throw new ApiError('Offline sales are switched off. Reconnect to take payment.', 'business')
    if (tenders.some((tn) => !cashModes.has(tn.mode_of_payment))) throw new ApiError('Only cash can be taken while offline.', 'business')
    if (cart.lines.some((l) => l.serial_nos?.length)) throw new ApiError('Serial-numbered items need a connection.', 'business')
    if (settings.offline_max_sale_value && Dec.of(preview.value.total).gt(settings.offline_max_sale_value)) throw new ApiError('This sale is above the offline limit.', 'business')
    await outbox!.add(key, 'sale', body)
    clearCart()
    return { mode: 'queued' as const, status: 'queued', preview: preview.value }
  }

  async function syncNow() {
    if (!outbox) return
    syncing.value = true
    try { await outbox.flush() } finally { syncing.value = false }
  }

  const pendingCount = computed(() => outboxEntries.value.filter((e) => ['Queued', 'Sending', 'Ambiguous'].includes(e.status)).length)
  const reviewCount = computed(() => outboxEntries.value.filter((e) => ['Rejected', 'Needs Review'].includes(e.status)).length)

  return {
    app, api, boot, register, registerName, online, catalog, catalogState, promotions, cart, quote, quoteState, quoteError,
    preview, itemCount, sessionOpen, outboxEntries, pendingCount, reviewCount, syncing,
    loadBoot, useRegister, loadCatalog, addItem, setQty, clearCart, scan, refreshQuote, submit, syncNow, payload,
    exportPending: () => outbox?.exportPending(),
  }
}

export type Till = ReturnType<typeof createTill>
