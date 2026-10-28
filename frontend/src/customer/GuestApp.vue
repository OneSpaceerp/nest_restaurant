<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import NButton from '@shared/components/NButton.vue'
import NIcon from '@shared/components/NIcon.vue'
import NQty from '@shared/components/NQty.vue'
import NSheet from '@shared/components/NSheet.vue'
import NState from '@shared/components/NState.vue'
import NStatus from '@shared/components/NStatus.vue'
import NInstall from '@shared/components/NInstall.vue'
import NToasts from '@shared/components/NToasts.vue'
import { toast } from '@shared/components/toast'
import { ApiError, call, newKey } from '@shared/lib/api'
import { lang, money, t } from '@shared/lib/i18n'
import { cycleTheme, toggleLanguage } from '@shared/app/surface'

const props = defineProps<{ root: HTMLElement }>()
const API = (m: string) => `nest_restaurant.api.guest.${m}`
const KEY = 'nest_rest_guest:visit'

interface Option { code: string; name: string; description?: string | null; image?: string | null; sold_out: boolean; price: number | null }
interface Group { group: string; min: number; max: number; options: Option[] }
interface Item { item_code: string; name: string; name_ar?: string | null; description?: string | null; allergens: string[]; dietary: string[]; image?: string | null; price: number; sold_out: boolean; options: Group[] }
interface CartLine { key: string; item: Item; qty: number; note: string; modifiers: string[] }
interface Status { table_label: string; submissions: { name: string; status: string; reject_reason?: string }[]; order: null | { status: string; order_number: number; subtotal_preview: number; paid_amount: number; lines: { item_name: string; qty: number; sent_qty: number; progress: Record<string, number>; void_reason?: string | null }[] } }

const visit = reactive({ token: '', table: '', outlet: '', needsCode: false, mode: '', cart: [] as CartLine[], pendingKey: null as string | null })
watch(visit, () => { try { localStorage.setItem(KEY, JSON.stringify(visit)) } catch { /* private */ } }, { deep: true })
const stage = ref<'scan' | 'code' | 'menu' | 'status'>('scan')
const menu = ref<{ currency: string; sections: { name: string; items: Item[] }[] } | null>(null)
const section = ref<string | null>(null)
const picking = ref<{ item: Item; qty: number; note: string; chosen: string[] } | null>(null)
const cartOpen = ref(false)
const codeInput = ref('')
const sending = ref(false)
const status = ref<Status | null>(null)
const error = ref('')
let pollTimer = 0

const currency = computed(() => menu.value?.currency ?? 'USD')
const total = computed(() => visit.cart.reduce((a, l) => a + l.qty * (l.item.price + l.modifiers.reduce((s, c) => s + (l.item.options.flatMap((g) => g.options).find((o) => o.code === c)?.price ?? 0), 0)), 0))
const count = computed(() => visit.cart.reduce((a, l) => a + l.qty, 0))
const items = computed(() => menu.value?.sections.find((s) => s.name === section.value)?.items ?? [])
const name = (i: Item) => (lang() === 'ar' && i.name_ar ? i.name_ar : i.name)

async function guarded<T>(fn: () => Promise<T>): Promise<T | undefined> {
  try {
    return await fn()
  } catch (e) {
    if (e instanceof ApiError && e.kind === 'permission' && !visit.needsCode) {
      Object.assign(visit, { token: '', cart: visit.cart, pendingKey: null })
      stage.value = 'scan'
    }
    toast((e as Error).message, e instanceof ApiError && e.kind === 'transient' ? 'warn' : 'danger')
    return undefined
  }
}

onMounted(async () => {
  try { Object.assign(visit, JSON.parse(localStorage.getItem(KEY) ?? '{}')) } catch { /* new */ }
  const code = location.pathname.match(/\/customer\/t\/([^/]+)/)?.[1]
  if (code) {
    const res = await guarded(() => call<{ token: string; table_label: string; needs_visit_code: boolean; outlet: string; mode: string }>(API('start'), { code: decodeURIComponent(code) }))
    history.replaceState(null, '', '/nest-restaurant/customer/')
    if (!res) return
    Object.assign(visit, { token: res.token, table: res.table_label, outlet: res.outlet, needsCode: res.needs_visit_code, mode: res.mode, pendingKey: null })
  }
  if (!visit.token) return
  stage.value = visit.needsCode ? 'code' : 'menu'
  await loadMenu()
})
onBeforeUnmount(() => clearTimeout(pollTimer))

async function loadMenu() {
  const res = await guarded(() => call<typeof menu.value & { needs_visit_code: boolean }>(API('menu'), { token: visit.token }))
  if (!res) return
  menu.value = res
  section.value ??= res!.sections[0]?.name ?? null
}

async function confirmCode() {
  const res = await guarded(() => call<{ confirmed: boolean }>(API('confirm'), { token: visit.token, visit_code: codeInput.value }))
  if (res?.confirmed) {
    visit.needsCode = false
    stage.value = 'menu'
  }
}

function open(item: Item) {
  if (!item.sold_out) picking.value = { item, qty: 1, note: '', chosen: [] }
}
function toggle(code: string, g: Group) {
  const p = picking.value!
  const inGroup = g.options.map((o) => o.code)
  if (p.chosen.includes(code)) p.chosen = p.chosen.filter((c) => c !== code)
  else if (g.max === 1) p.chosen = [...p.chosen.filter((c) => !inGroup.includes(c)), code]
  else if (!g.max || p.chosen.filter((c) => inGroup.includes(c)).length < g.max) p.chosen.push(code)
}
const valid = computed(() => picking.value?.item.options.every((g) => {
  const n = picking.value!.chosen.filter((c) => g.options.some((o) => o.code === c)).length
  return n >= g.min && (!g.max || n <= g.max)
}))
function add() {
  const p = picking.value!
  visit.cart.push({ key: newKey('g'), item: p.item, qty: p.qty, note: p.note, modifiers: p.chosen })
  visit.pendingKey = null
  picking.value = null
  toast(t('{0} added', name(p.item)))
}

async function send() {
  sending.value = true
  visit.pendingKey ??= newKey('guest-')
  const res = await guarded(() =>
    call<{ status: string }>(API('submit'), { token: visit.token, lines: visit.cart.map((l) => ({ item_code: l.item.item_code, qty: l.qty, note: l.note, modifiers: l.modifiers })), request_key: visit.pendingKey }, { timeoutMs: 25000 }),
  )
  sending.value = false
  if (!res) return // kept locally with the same key: tapping Send again cannot double the order
  visit.cart = []
  visit.pendingKey = null
  cartOpen.value = false
  toast(res.status === 'Accepted' ? t('Your order is with the kitchen') : t('Sent — staff will confirm it shortly'))
  stage.value = 'status'
  await refresh()
}

async function refresh() {
  const res = await guarded(() => call<Status>(API('status'), { token: visit.token }))
  if (res) status.value = res
  clearTimeout(pollTimer)
  if (stage.value === 'status') pollTimer = window.setTimeout(refresh, 6000)
}

async function request(type: 'Bill' | 'Waiter') {
  const res = await guarded(() => call<{ status: string }>(API('service_request'), { token: visit.token, request_type: type }))
  if (res) toast(type === 'Bill' ? t('We’ll bring your bill') : t('A server is on the way'))
}

function lineState(l: { qty: number; sent_qty: number; progress: Record<string, number>; void_reason?: string | null }) {
  if (l.void_reason && !l.qty) return ['danger', 'Removed'] as const
  if ((l.progress.Served ?? 0) >= l.qty) return ['neutral', 'Served'] as const
  if ((l.progress.Ready ?? 0) + (l.progress.Served ?? 0) >= l.qty) return ['ok', 'Ready'] as const
  if (l.progress.Preparing) return ['warn', 'Preparing'] as const
  if (l.sent_qty >= l.qty) return ['info', 'With the kitchen'] as const
  return ['neutral', 'Received'] as const
}
</script>

<template>
  <div class="gst">
    <header class="gst__top">
      <img src="/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e" alt="" width="32" height="32" class="gst__logo" />
      <div class="gst__where"><strong>{{ visit.outlet || 'Nest Restaurant' }}</strong><span v-if="visit.table">{{ t('Table {0}', visit.table) }}</span></div>
      <span class="spacer" />
      <button type="button" class="gst__util" :aria-label="t('Language')" @click="toggleLanguage('nest_rest_guest', props.root)"><NIcon name="globe" /></button>
      <button type="button" class="gst__util" :aria-label="t('Theme')" @click="cycleTheme('nest_rest_guest', props.root)"><NIcon name="moon" /></button>
    </header>

    <main class="gst__main scroll">
      <NState v-if="stage === 'scan'" kind="empty" icon="scan" :title="t('Scan the code on your table')" :detail="t('It opens this menu for your table. You can also order with your server.')" />

      <section v-else-if="stage === 'code'" class="gst__panel">
        <h1>{{ t('Joining table {0}', visit.table) }}</h1>
        <p class="muted">{{ t('This table already has an order. Enter the visit code from your bill, or ask your server.') }}</p>
        <form class="row" @submit.prevent="confirmCode">
          <input v-model="codeInput" class="gst__code code" inputmode="numeric" maxlength="4" autocomplete="one-time-code" :aria-label="t('Visit code')" />
          <NButton type="submit" variant="primary" :disabled="codeInput.length !== 4">{{ t('Join') }}</NButton>
        </form>
      </section>

      <template v-else-if="stage === 'menu'">
        <NState v-if="!menu" kind="loading" :title="t('Loading the menu')" />
        <template v-else>
          <nav class="gst__sections" :aria-label="t('Menu sections')">
            <button v-for="s in menu.sections" :key="s.name" type="button" :aria-pressed="section === s.name" class="gst__sec" @click="section = s.name">{{ s.name }}</button>
          </nav>
          <ul class="gst__items" role="list">
            <li v-for="i in items" :key="i.item_code">
              <button type="button" class="gst__item" :disabled="i.sold_out" @click="open(i)">
                <img v-if="i.image" :src="i.image" alt="" loading="lazy" class="gst__img" />
                <span class="gst__item-body">
                  <span class="gst__name">{{ name(i) }}</span>
                  <span v-if="i.description" class="gst__desc">{{ i.description }}</span>
                  <span v-if="i.dietary.length || i.allergens.length" class="gst__tags">
                    <span v-for="d in i.dietary" :key="d" class="gst__tag">{{ d }}</span>
                    <span v-if="i.allergens.length" class="gst__tag gst__tag--warn">{{ t('Contains') }}: {{ i.allergens.join(', ') }}</span>
                  </span>
                  <span class="gst__price num">{{ i.sold_out ? t('Sold out') : money(i.price, currency) }}</span>
                </span>
              </button>
            </li>
          </ul>
        </template>
      </template>

      <section v-else-if="stage === 'status'" class="gst__panel">
        <h1>{{ t('Your order') }}</h1>
        <NState v-if="!status" kind="loading" :title="t('Loading')" />
        <template v-else>
          <p v-for="s in status.submissions.filter((x) => x.status !== 'Accepted')" :key="s.name" class="gst__note">
            {{ s.status === 'Rejected' ? t('Staff could not accept part of your order: {0}', s.reject_reason ?? '') : t('Waiting for staff to confirm your order') }}
          </p>
          <ul v-if="status.order" class="gst__lines" role="list">
            <li v-for="(l, i) in status.order.lines" :key="i">
              <span><span class="num">{{ l.qty }}×</span> {{ l.item_name }}</span>
              <NStatus :tone="lineState(l)[0]" :label="t(lineState(l)[1])" />
            </li>
          </ul>
          <p v-if="status.order" class="gst__sum">{{ t('So far') }} <strong class="num">{{ money(status.order.subtotal_preview, currency) }}</strong></p>
          <p class="muted">{{ t('Pay with your server or at the counter.') }}</p>
        </template>
        <div class="row">
          <NButton icon="plus" @click="stage = 'menu'">{{ t('Order more') }}</NButton>
          <NButton icon="bell" @click="request('Waiter')">{{ t('Call a waiter') }}</NButton>
          <NButton variant="primary" icon="receipt" @click="request('Bill')">{{ t('Request the bill') }}</NButton>
        </div>
      </section>
    </main>

    <footer v-if="stage === 'menu'" class="gst__bar">
      <NButton variant="ghost" icon="clock" @click="stage = 'status'; refresh()">{{ t('My order') }}</NButton>
      <NButton v-if="visit.cart.length" variant="primary" size="lg" icon="basket" @click="cartOpen = true">
        {{ t('Review {0} items', count) }} · <span class="num">{{ money(total, currency) }}</span>
      </NButton>
    </footer>

    <NSheet :open="!!picking" :title="picking ? name(picking.item) : ''" @close="picking = null">
      <div v-if="picking" class="stack">
        <p v-if="picking.item.description" class="muted">{{ picking.item.description }}</p>
        <p v-if="picking.item.allergens.length" class="gst__allergy"><strong>{{ t('Allergens') }}:</strong> {{ picking.item.allergens.join(', ') }}</p>
        <img v-if="picking.item.image" :src="picking.item.image" alt="" class="gst__pick-img" />
        <fieldset v-for="g in picking.item.options" :key="g.group" class="gst__group">
          <legend class="gst__group-head">
            <span class="gst__group-name">{{ g.group }}<small class="muted">{{ g.max === 1 ? t('Choose 1') : t('Choose up to {0}', g.max) }}</small></span>
            <span :class="['gst__badge', { 'gst__badge--req': g.min }]">{{ g.min ? t('Required') : t('Optional') }}</span>
          </legend>
          <button v-for="o in g.options" :key="o.code" type="button" :class="['gst__opt', { 'gst__opt--rich': o.image || o.description }]" :aria-pressed="picking.chosen.includes(o.code)" :disabled="o.sold_out" @click="toggle(o.code, g)">
            <img v-if="o.image" :src="o.image" alt="" class="gst__opt-img" loading="lazy" />
            <span class="gst__opt-text"><span class="gst__opt-name">{{ o.name }}</span><span v-if="o.description" class="gst__opt-desc">{{ o.description }}</span><span v-if="o.sold_out" class="gst__opt-desc">{{ t('Sold out') }}</span></span>
            <span v-if="o.price" class="gst__opt-price num">+ {{ money(o.price, currency) }}</span>
          </button>
        </fieldset>
        <label class="stack"><span>{{ t('Anything we should know?') }}</span><input v-model="picking.note" class="gst__input" maxlength="140" :placeholder="t('e.g. no onions')" /></label>
        <NQty v-model="picking.qty" :min="1" :max="20" :label="t('Quantity')" />
      </div>
      <template #actions><NButton variant="primary" :disabled="!valid" @click="add">{{ t('Add to order') }}</NButton></template>
    </NSheet>

    <NSheet :open="cartOpen" :title="t('Your order')" @close="cartOpen = false">
      <ul class="gst__lines" role="list">
        <li v-for="(l, i) in visit.cart" :key="l.key">
          <span>{{ name(l.item) }}<span v-if="l.note" class="muted"> — “{{ l.note }}”</span></span>
          <NQty :model-value="l.qty" :min="0" :max="20" :label="t('Quantity of {0}', name(l.item))" @update:model-value="(v: number) => { v ? (l.qty = v) : visit.cart.splice(i, 1); visit.pendingKey = null }" />
        </li>
      </ul>
      <p class="gst__sum">{{ t('Total') }} <strong class="num">{{ money(total, currency) }}</strong></p>
      <p class="muted">{{ visit.mode === 'Direct to kitchen' ? t('Your order goes straight to the kitchen. You pay at the end.') : t('Staff confirm your order before it goes to the kitchen.') }}</p>
      <template #actions><NButton variant="primary" size="lg" icon="send" :busy="sending" :disabled="!visit.cart.length" @click="send">{{ t('Send order') }}</NButton></template>
    </NSheet>
    <NToasts />
    <NInstall app="nest_rest_guest" name="Nest Restaurant" logo="/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e" />
  </div>
</template>

<style>
.gst { display: flex; flex-direction: column; block-size: 100%; }
.gst__top { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-4); min-block-size: 56px; background: var(--nest-ink-900); color: #f6f5f3; }
.gst__logo { border-radius: 8px; }
.gst__where { display: grid; line-height: 1.2; }
.gst__where span { color: var(--nest-yellow-400); font-weight: 600; font-size: var(--text-sm); }
.gst__util { inline-size: var(--touch); block-size: var(--touch); border: 0; background: transparent; color: inherit; display: grid; place-items: center; border-radius: var(--radius-md); cursor: pointer; }
.gst__main { flex: 1; min-block-size: 0; padding: var(--space-4); }
.gst__panel { max-inline-size: 560px; margin-inline: auto; display: grid; gap: var(--space-4); }
.gst__code { inline-size: 7rem; min-block-size: var(--touch-lg); font-size: var(--text-xl); text-align: center; letter-spacing: 0.3em; border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); }
.gst__sections { display: flex; gap: var(--space-2); overflow-x: auto; position: sticky; inset-block-start: calc(-1 * var(--space-4)); background: var(--surface-page); padding-block: var(--space-2); z-index: 1; }
.gst__sec { flex: none; min-block-size: 44px; padding-inline: var(--space-4); border-radius: var(--radius-pill); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-body); font-weight: 600; cursor: pointer; }
.gst__sec[aria-pressed='true'] { background: var(--nest-ink-900); color: var(--nest-yellow-400); border-color: transparent; }
.gst__items { list-style: none; margin: var(--space-3) 0 0; padding: 0; display: grid; gap: var(--space-3); max-inline-size: 760px; margin-inline: auto; }
.gst__item { inline-size: 100%; display: grid; grid-template-columns: auto 1fr; gap: var(--space-3); text-align: start; padding: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-subtle); background: var(--surface-card); cursor: pointer; color: var(--text-body); }
.gst__item:disabled { opacity: 0.6; }
.gst__img { inline-size: 88px; block-size: 88px; object-fit: cover; border-radius: var(--radius-sm); }
.gst__item-body { display: grid; gap: 4px; }
.gst__name { font-weight: 600; color: var(--text-strong); font-size: var(--text-lg); }
.gst__desc { color: var(--text-muted); font-size: var(--text-sm); }
.gst__tags { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.gst__tag { font-size: var(--text-xs); padding: 2px 8px; border-radius: var(--radius-pill); background: var(--surface-sunken); }
.gst__tag--warn { background: var(--warn-bg); color: var(--warn-fg); font-weight: 600; }
.gst__price { font-weight: 700; color: var(--text-strong); }
.gst__bar { display: flex; gap: var(--space-2); padding: var(--space-2) var(--space-3) calc(var(--space-2) + var(--safe-bottom)); background: var(--surface-card); border-block-start: 1px solid var(--border-subtle); }
.gst__bar .n-btn--lg { flex: 1; min-inline-size: 0; }
.gst__group { border: 0; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.gst__group-head { inline-size: 100%; display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); margin-block-end: var(--space-2); padding: 0; }
.gst__group-name { display: grid; font-weight: 700; font-size: var(--text-md); }
.gst__group-name small { font-weight: 400; font-size: var(--text-sm); }
.gst__badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 10px; border-radius: var(--radius-pill); border: 1px solid var(--border-strong); color: var(--text-muted); white-space: nowrap; }
.gst__badge--req { border-color: var(--ok-fg); color: var(--ok-fg); background: var(--ok-bg); }
.gst__pick-img { inline-size: 100%; max-block-size: 240px; object-fit: contain; border-radius: var(--radius-md); background: var(--surface-sunken); }
.gst__opt--rich { inline-size: 100%; display: flex; align-items: center; gap: var(--space-3); text-align: start; padding-block: var(--space-2); min-block-size: 64px; }
.gst__opt-img { inline-size: 48px; block-size: 48px; object-fit: cover; border-radius: var(--radius-sm); flex: none; background: #fff; }
.gst__opt-text { flex: 1; min-inline-size: 0; display: grid; gap: 2px; }
.gst__opt-name { font-weight: 600; }
.gst__opt-desc { font-size: var(--text-sm); font-weight: 400; opacity: 0.8; }
.gst__opt-price { flex: none; font-weight: 600; white-space: nowrap; }
.gst__opt { min-block-size: var(--touch); padding-inline: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); cursor: pointer; color: var(--text-body); }
.gst__opt[aria-pressed='true'] { background: var(--nest-ink-900); color: var(--nest-yellow-400); border-color: transparent; font-weight: 600; }
.gst__input { min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); padding-inline: var(--space-3); background: var(--surface-card); color: var(--text-strong); }
.gst__allergy { background: var(--warn-bg); color: var(--warn-fg); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); }
.gst__lines { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.gst__lines li { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); padding-block: var(--space-2); border-block-end: 1px dashed var(--border-subtle); }
.gst__sum { text-align: end; font-size: var(--text-lg); margin-block-start: var(--space-3); }
.gst__note { background: var(--info-bg); color: var(--info-fg); padding: var(--space-3); border-radius: var(--radius-md); }
</style>
