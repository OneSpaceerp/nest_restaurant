<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import NButton from '@shared/components/NButton.vue'
import NIcon from '@shared/components/NIcon.vue'
import NQty from '@shared/components/NQty.vue'
import NSheet from '@shared/components/NSheet.vue'
import NState from '@shared/components/NState.vue'
import NStatus from '@shared/components/NStatus.vue'
import { toast } from '@shared/components/toast'
import { ApiError, call, newKey } from '@shared/lib/api'
import { money, t } from '@shared/lib/i18n'
import { on, onReconnect } from '@shared/lib/realtime'
import PaySheet from '@shared/till/PaySheet.vue'
import { SVC, lineStage, useTill, type Menu, type MenuItem, type Order, type OrderLine } from '../state'

const props = defineProps<{ name: string }>()
const till = useTill()
const router = useRouter()
const order = ref<Order | null>(null)
const menu = ref<Menu | null>(null)
const error = ref('')
const section = ref<string | null>(null)
const busy = ref<string | null>(null)
const currency = computed(() => menu.value?.currency ?? till.register.value?.currency ?? 'USD')
const canPay = computed(() => Boolean(till.boot.value?.roles.cashier || till.boot.value?.roles.supervisor || till.boot.value?.roles.manager))

// ---- the round being taken: kept on this device until the server accepts it ----
interface Draft { key: string; item: MenuItem; qty: number; seat: number | null; course: number; note: string; modifiers: string[] }
const DRAFT_KEY = computed(() => `nest_rest:draft:${props.name}`)
const draft = reactive<{ lines: Draft[]; addKey: string | null; sendKey: string | null }>({ lines: [], addKey: null, sendKey: null })
const seat = ref<number | null>(null)
const course = ref(1)
watch(draft, () => { try { localStorage.setItem(DRAFT_KEY.value, JSON.stringify(draft)) } catch { /* private mode */ } }, { deep: true })

const picking = ref<{ item: MenuItem; chosen: string[]; qty: number; note: string } | null>(null)
const editing = ref<{ line: OrderLine; qty: number; note: string; reason: string } | null>(null)
const more = ref(false)
const paying = ref(false)
const part = ref<{ mode: 'all' | 'seat' | 'items'; seat: number | null; selection: Record<string, number> }>({ mode: 'all', seat: null, selection: {} })
const payError = ref('')
const target = ref<{ kind: 'transfer' | 'merge'; options: { value: string; label: string }[] } | null>(null)
const cancelReason = ref('')

async function load() {
  try {
    order.value = await call<Order>(SVC('get_order'), { order: props.name }, { method: 'GET' })
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
  }
}
async function loadMenu() {
  menu.value = await call<Menu>(SVC('menu_detail'), { register_name: till.registerName.value }, { method: 'GET' })
  section.value ??= menu.value.sections[0]?.name ?? null
}

const offs: (() => void)[] = []
onMounted(async () => {
  try { Object.assign(draft, JSON.parse(localStorage.getItem(DRAFT_KEY.value) ?? '{}')) } catch { /* new round */ }
  await Promise.all([load(), loadMenu().catch((e) => (error.value = e.message))])
  offs.push(
    on('nest_rest:order', (d) => { if ((d as { order: string }).order === props.name) void load() }),
    on('nest_rest:ticket', (d) => { if ((d as { order?: string }).order === props.name) void load() }),
    onReconnect(() => void load()),
  )
})
onBeforeUnmount(() => offs.forEach((f) => f()))

const items = computed(() => menu.value?.sections.find((s) => s.name === section.value)?.items ?? [])
const courses = computed(() => {
  const by = new Map<number, OrderLine[]>()
  for (const l of order.value?.lines ?? []) by.set(l.course, [...(by.get(l.course) ?? []), l])
  return [...by.entries()].sort((a, b) => a[0] - b[0])
})
const unsent = computed(() => (order.value?.lines ?? []).filter((l) => l.sent_qty < l.qty && !l.held).length)
const heldCourses = computed(() => [...new Set((order.value?.lines ?? []).filter((l) => l.held && l.sent_qty < l.qty).map((l) => l.course))])
const remaining = computed(() => (order.value?.lines ?? []).reduce((a, l) => a + (l.qty - l.paid_qty) * l.rate_preview, 0))
const draftTotal = computed(() => draft.lines.reduce((a, d) => a + d.qty * d.item.price, 0))
const editable = computed(() => ['Open', 'Bill Requested'].includes(order.value?.status ?? ''))
const seats = computed(() => Array.from({ length: Math.max(order.value?.covers ?? 0, 1) }, (_, i) => i + 1))
const STAGE_TONE = { 'Not sent': 'neutral', Sent: 'info', Preparing: 'warn', Ready: 'ok', Served: 'neutral', Voided: 'danger' } as const

function tapItem(item: MenuItem) {
  if (item.sold_out) return
  if (item.options.length) picking.value = { item, chosen: [], qty: 1, note: '' }
  else addDraft(item, 1, [], '')
}
function toggleOption(code: string, group: { max: number; options: { code: string }[] }) {
  const p = picking.value!
  const inGroup = group.options.map((o) => o.code)
  if (p.chosen.includes(code)) p.chosen = p.chosen.filter((c) => c !== code)
  else {
    const already = p.chosen.filter((c) => inGroup.includes(c))
    if (group.max === 1) p.chosen = [...p.chosen.filter((c) => !inGroup.includes(c)), code]
    else if (!group.max || already.length < group.max) p.chosen.push(code)
  }
}
const pickValid = computed(() => picking.value?.item.options.every((g) => {
  const n = picking.value!.chosen.filter((c) => g.options.some((o) => o.code === c)).length
  return n >= g.min && (!g.max || n <= g.max)
}))
function addDraft(item: MenuItem, qty: number, modifiers: string[], note: string) {
  draft.lines.push({ key: newKey('d'), item, qty, seat: seat.value, course: course.value || item.course || 1, note, modifiers })
  draft.addKey = null // the round changed: a new idempotency key for the next submit
  picking.value = null
}

/** Add the round to the check and, unless `hold`, send it to the kitchen. Keys are persisted so a
 *  retry after a lost response neither duplicates lines nor re-fires tickets. */
async function submitRound(send: boolean) {
  if (!draft.lines.length && !(send && unsent.value)) return
  busy.value = 'send'
  try {
    if (draft.lines.length) {
      draft.addKey ??= newKey('add-')
      await call(SVC('add_lines'), {
        order: props.name,
        lines: draft.lines.map((d) => ({ item_code: d.item.item_code, qty: d.qty, seat: d.seat, course: d.course, note: d.note, modifiers: d.modifiers })),
        request_key: draft.addKey,
      })
      draft.lines = []
      draft.addKey = null
    }
    if (send) {
      draft.sendKey ??= newKey('send-')
      const res = await call<{ tickets: { station: string }[] }>(SVC('send'), { order: props.name, request_key: draft.sendKey })
      draft.sendKey = null
      toast(res.tickets.length ? t('Sent to {0}', [...new Set(res.tickets.map((x) => x.station))].join(', ')) : t('Nothing new to send'))
    }
    await load()
  } catch (e) {
    const err = e as ApiError
    toast(err.kind === 'ambiguous' || err.kind === 'transient' ? t('Not confirmed yet — your round is kept. Tap again to retry safely.') : err.message, 'danger')
  } finally {
    busy.value = null
  }
}

async function fire(c: number) {
  busy.value = `fire${c}`
  try {
    await call(SVC('fire_course'), { order: props.name, course: c, request_key: newKey('fire-') })
    toast(t('Course {0} fired', c))
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    busy.value = null
  }
}

async function saveEdit() {
  const ed = editing.value!
  try {
    await call(SVC('update_line'), { order: props.name, line_id: ed.line.line_id, qty: ed.qty, note: ed.note, expected_version: order.value!.version, void_reason: ed.reason })
    editing.value = null
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
    await load()
  }
}

async function printBill() {
  busy.value = 'bill'
  try {
    order.value = await call<Order>(SVC('print_bill'), { order: props.name })
    toast(t('Bill is ready — the check is locked for payment'))
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    busy.value = null
  }
}

const partDue = computed(() => {
  const o = order.value
  if (!o) return 0
  if (part.value.mode === 'all') return remaining.value
  if (part.value.mode === 'seat') return o.lines.filter((l) => l.seat === part.value.seat).reduce((a, l) => a + (l.qty - l.paid_qty) * l.rate_preview, 0)
  return o.lines.reduce((a, l) => a + (part.value.selection[l.line_id] ?? 0) * l.rate_preview, 0)
})

async function pay(tenders: { mode_of_payment: string; amount: string }[]) {
  busy.value = 'pay'
  payError.value = ''
  try {
    const p = part.value
    const res = await call<{ order: Order; invoice: { name: string } }>(SVC('pay'), {
      order: props.name,
      register_name: till.registerName.value,
      part: p.mode === 'all' ? { mode: 'all' } : p.mode === 'seat' ? { mode: 'seat', seat: p.seat, label: t('Seat {0}', p.seat ?? '') } : { mode: 'items', selection: p.selection },
      tenders,
      request_key: newKey('pay-'),
    }, { timeoutMs: 45000 })
    order.value = res.order
    paying.value = false
    toast(t('Paid — invoice {0}', res.invoice.name))
    if (res.order.status === 'Paid') await router.push('/floor')
  } catch (e) {
    payError.value = (e as Error).message
  } finally {
    busy.value = null
  }
}

async function chooseTarget(kind: 'transfer' | 'merge') {
  const floor = await call<{ tables: { name: string; table_label: string; status: string; current_order: string | null }[] }>(SVC('floor_state'), { register_name: till.registerName.value }, { method: 'GET' })
  const options = kind === 'transfer'
    ? floor.tables.filter((x) => ['Free', 'Reserved'].includes(x.status)).map((x) => ({ value: x.name, label: t('Table {0}', x.table_label) }))
    : floor.tables.filter((x) => x.current_order && x.current_order !== props.name).map((x) => ({ value: x.current_order!, label: t('Table {0}', x.table_label) }))
  more.value = false
  target.value = { kind, options }
}
async function applyTarget(value: string) {
  const kind = target.value!.kind
  try {
    if (kind === 'transfer') await call(SVC('transfer'), { order: props.name, to_table: value, request_key: newKey('mv-') })
    else {
      await call(SVC('merge'), { source: props.name, target: value, request_key: newKey('mg-') })
      target.value = null
      return router.replace(`/order/${value}`)
    }
    target.value = null
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
  }
}
async function cancelOrder() {
  try {
    await call(SVC('cancel_order'), { order: props.name, reason: cancelReason.value, request_key: newKey('cx-') })
    await router.push('/floor')
  } catch (e) {
    toast((e as Error).message, 'danger')
  }
}
</script>

<template>
  <div class="ord">
    <NState v-if="error" kind="error" :title="t('This order could not be loaded')" :detail="error" :retry="load" />
    <NState v-else-if="!order" kind="loading" :title="t('Loading the order')" />
    <template v-else>
      <section class="ord__menu" :aria-label="t('Menu')">
        <div class="ord__sections" role="tablist">
          <button v-for="s in menu?.sections ?? []" :key="s.name" type="button" role="tab" :aria-selected="section === s.name" class="ord__sec" @click="section = s.name">{{ s.name }}</button>
        </div>
        <div class="ord__pickers">
          <div class="ord__seg" role="radiogroup" :aria-label="t('Seat')">
            <span class="muted">{{ t('Seat') }}</span>
            <button type="button" role="radio" :aria-checked="seat === null" class="ord__segb" @click="seat = null">{{ t('Shared') }}</button>
            <button v-for="s in seats" :key="s" type="button" role="radio" :aria-checked="seat === s" class="ord__segb num" @click="seat = s">{{ s }}</button>
          </div>
          <div class="ord__seg" role="radiogroup" :aria-label="t('Course')">
            <span class="muted">{{ t('Course') }}</span>
            <button v-for="c in [1, 2, 3]" :key="c" type="button" role="radio" :aria-checked="course === c" class="ord__segb num" @click="course = c">{{ c }}</button>
          </div>
        </div>
        <ul class="ord__items scroll" role="list">
          <li v-for="m in items" :key="m.item_code">
            <button type="button" class="ord__item" :disabled="m.sold_out || !editable" @click="tapItem(m)">
              <span class="ord__item-name">{{ m.name }}</span>
              <span v-if="m.allergens.length" class="ord__allergens">{{ m.allergens.join(', ') }}</span>
              <span class="ord__item-foot">
                <span class="num">{{ money(m.price, currency) }}</span>
                <span v-if="m.sold_out" class="ord__soldout">{{ t('Sold out') }}</span>
                <span v-else-if="m.options.length" class="muted">{{ t('Options') }}</span>
              </span>
            </button>
          </li>
        </ul>
      </section>

      <aside class="ord__check" :aria-label="t('Check')">
        <header class="ord__head">
          <button type="button" class="ord__back" :aria-label="t('Back')" @click="router.push('/floor')"><NIcon name="back" /></button>
          <div>
            <h1>{{ order.table_label ? t('Table {0}', order.table_label) : t(order.service_type) }} <span class="muted num">#{{ order.order_number }}</span></h1>
            <p class="muted">{{ t('{0} guests', order.covers) }} · {{ t(order.status) }}<template v-if="order.visit_code"> · {{ t('Visit code') }} <strong class="code">{{ order.visit_code }}</strong></template></p>
          </div>
          <button type="button" class="ord__back" :aria-label="t('More actions')" @click="more = true"><NIcon name="more" /></button>
        </header>

        <div class="ord__lines scroll">
          <section v-for="[c, lines] in courses" :key="c" class="ord__course">
            <h2 class="ord__course-h">
              {{ t('Course {0}', c) }}
              <NButton v-if="heldCourses.includes(c)" size="sm" variant="brand" :busy="busy === `fire${c}`" @click="fire(c)">{{ t('Fire course {0}', c) }}</NButton>
            </h2>
            <ul role="list" class="ord__list">
              <li v-for="l in lines" :key="l.line_id">
                <button type="button" class="ord__line" :disabled="!editable" @click="editing = { line: l, qty: l.qty, note: l.note ?? '', reason: '' }">
                  <span class="ord__qty num">{{ l.qty }}×</span>
                  <span class="ord__lname">
                    {{ l.item_name }}
                    <span v-if="l.modifiers.length" class="ord__mods">{{ l.modifiers.map((m) => m.name).join(', ') }}</span>
                    <span v-if="l.note" class="ord__note">“{{ l.note }}”</span>
                    <span v-if="l.seat" class="muted">{{ t('Seat {0}', l.seat) }}</span>
                    <span v-if="l.source === 'Guest'" class="muted">{{ t('Ordered by guest') }}</span>
                  </span>
                  <NStatus :tone="STAGE_TONE[lineStage(l)]" :label="t(lineStage(l))" />
                </button>
              </li>
            </ul>
          </section>
          <section v-if="draft.lines.length" class="ord__draft">
            <h2 class="ord__course-h">{{ t('New round — not sent yet') }}</h2>
            <ul role="list" class="ord__list">
              <li v-for="(d, i) in draft.lines" :key="d.key" class="ord__line ord__line--draft">
                <span class="ord__qty num">{{ d.qty }}×</span>
                <span class="ord__lname">{{ d.item.name }}<span class="muted">{{ d.seat ? t('Seat {0}', d.seat) : '' }} · {{ t('Course {0}', d.course) }}</span></span>
                <button type="button" class="ord__x" :aria-label="t('Remove {0}', d.item.name)" @click="draft.lines.splice(i, 1); draft.addKey = null"><NIcon name="close" :size="18" /></button>
              </li>
            </ul>
          </section>
          <NState v-if="!order.lines.length && !draft.lines.length" kind="empty" icon="clipboard" :title="t('No items yet')" :detail="t('Pick dishes from the menu. They are sent together when you tap Send.')" />
        </div>

        <footer class="ord__foot">
          <p class="ord__total"><span>{{ t('To pay') }}</span><strong class="num">{{ money(remaining + draftTotal, currency) }}</strong></p>
          <div class="ord__actions">
            <NButton v-if="draft.lines.length" :busy="busy === 'save'" @click="submitRound(false)">{{ t('Save') }}</NButton>
            <NButton variant="primary" size="lg" icon="send" :busy="busy === 'send'" :disabled="!draft.lines.length && !unsent" @click="submitRound(true)">
              {{ t('Send to kitchen') }}<span v-if="draft.lines.length + unsent" class="num"> ({{ draft.lines.length + unsent }})</span>
            </NButton>
            <NButton v-if="canPay && editable" icon="receipt" :busy="busy === 'bill'" :disabled="!!draft.lines.length || !!unsent || !order.lines.length" @click="printBill">{{ t('Bill') }}</NButton>
            <NButton v-if="canPay && ['Billed', 'Partly Paid'].includes(order.status)" variant="brand" size="lg" icon="cash" @click="paying = true; part = { mode: 'all', seat: null, selection: {} }">{{ t('Pay') }}</NButton>
          </div>
        </footer>
      </aside>

      <NSheet :open="!!picking" :title="picking?.item.name ?? ''" @close="picking = null">
        <div v-if="picking" class="stack">
          <p v-if="picking.item.description" class="muted">{{ picking.item.description }}</p>
          <p v-if="picking.item.allergens.length" class="ord__allergy"><strong>{{ t('Allergens') }}:</strong> {{ picking.item.allergens.join(', ') }}</p>
          <fieldset v-for="g in picking.item.options" :key="g.group" class="ord__group">
            <legend>{{ g.group }} <span class="muted">{{ g.min ? t('choose {0}', g.min === g.max ? g.min : `${g.min}–${g.max}`) : t('optional') }}</span></legend>
            <button v-for="o in g.options" :key="o.code" type="button" class="ord__opt" :aria-pressed="picking.chosen.includes(o.code)" :disabled="o.sold_out" @click="toggleOption(o.code, g)">
              {{ o.name }}<span v-if="o.price" class="num muted"> + {{ money(o.price, currency) }}</span><span v-if="o.sold_out" class="muted"> · {{ t('Sold out') }}</span>
            </button>
          </fieldset>
          <label class="stack"><span>{{ t('Note for the kitchen') }}</span><input v-model="picking.note" class="ord__input" maxlength="140" /></label>
          <NQty v-model="picking.qty" :min="1" :label="t('Quantity')" />
        </div>
        <template #actions>
          <NButton variant="primary" :disabled="!pickValid" @click="addDraft(picking!.item, picking!.qty, picking!.chosen, picking!.note)">{{ t('Add to order') }}</NButton>
        </template>
      </NSheet>

      <NSheet :open="!!editing" :title="editing?.line.item_name ?? ''" @close="editing = null">
        <div v-if="editing" class="stack">
          <NQty v-model="editing.qty" :min="editing.line.paid_qty" :label="t('Quantity')" />
          <label class="stack"><span>{{ t('Note') }}</span><input v-model="editing.note" class="ord__input" maxlength="140" /></label>
          <label v-if="editing.qty < editing.line.sent_qty" class="stack">
            <span>{{ t('Why are sent items being removed?') }}</span>
            <input v-model="editing.reason" class="ord__input" maxlength="140" />
            <span class="muted">{{ t('The kitchen gets a void ticket. A supervisor approves this.') }}</span>
          </label>
        </div>
        <template #actions>
          <NButton @click="editing = null">{{ t('Cancel') }}</NButton>
          <NButton variant="primary" :disabled="!!editing && editing.qty < editing.line.sent_qty && !editing.reason.trim()" @click="saveEdit">{{ t('Save') }}</NButton>
        </template>
      </NSheet>

      <NSheet :open="more" :title="t('More actions')" @close="more = false">
        <div class="stack">
          <NButton block icon="table" :disabled="!order.table || !editable" @click="chooseTarget('transfer')">{{ t('Move to another table') }}</NButton>
          <NButton block icon="inbox" :disabled="!editable" @click="chooseTarget('merge')">{{ t('Merge into another check') }}</NButton>
          <label class="stack"><span>{{ t('Cancel the whole check — reason') }}</span><input v-model="cancelReason" class="ord__input" maxlength="140" /></label>
          <NButton block variant="danger" icon="trash" :disabled="!cancelReason.trim() || !editable" @click="cancelOrder">{{ t('Cancel check') }}</NButton>
        </div>
      </NSheet>

      <NSheet :open="!!target" :title="target?.kind === 'transfer' ? t('Move to table') : t('Merge into')" @close="target = null">
        <p v-if="!target?.options.length" class="muted">{{ t('No suitable table right now.') }}</p>
        <div class="ord__targets">
          <NButton v-for="o in target?.options ?? []" :key="o.value" @click="applyTarget(o.value)">{{ o.label }}</NButton>
        </div>
      </NSheet>

      <PaySheet :open="paying" :due="partDue" :currency="currency" :modes="till.register.value?.payment_modes ?? []" :online="till.online.value" :busy="busy === 'pay'" :error="payError" @close="paying = false" @pay="pay">
        <template #part>
          <div class="ord__seg" role="radiogroup" :aria-label="t('What is being paid')">
            <button type="button" role="radio" class="ord__segb" :aria-checked="part.mode === 'all'" @click="part = { mode: 'all', seat: null, selection: {} }">{{ t('Everything left') }}</button>
            <button v-for="s in seats" :key="s" type="button" role="radio" class="ord__segb" :aria-checked="part.mode === 'seat' && part.seat === s" @click="part = { mode: 'seat', seat: s, selection: {} }">{{ t('Seat {0}', s) }}</button>
            <button type="button" role="radio" class="ord__segb" :aria-checked="part.mode === 'items'" @click="part = { mode: 'items', seat: null, selection: {} }">{{ t('Choose items') }}</button>
          </div>
          <ul v-if="part.mode === 'items'" role="list" class="ord__list">
            <li v-for="l in order.lines.filter((x) => x.qty > x.paid_qty)" :key="l.line_id" class="ord__payline">
              <span>{{ l.item_name }} <span class="muted num">{{ money(l.rate_preview, currency) }}</span></span>
              <NQty :model-value="part.selection[l.line_id] ?? 0" :max="l.qty - l.paid_qty" :label="t('Pay for {0}', l.item_name)" @update:model-value="(v: number) => (part.selection[l.line_id] = v)" />
            </li>
          </ul>
        </template>
      </PaySheet>
    </template>
  </div>
</template>

<style>
.ord { flex: 1; min-block-size: 0; display: grid; grid-template-columns: minmax(0, 1fr) var(--tape-width); }
.ord__menu { display: flex; flex-direction: column; min-block-size: 0; padding: var(--space-3) var(--space-4); gap: var(--space-3); }
.ord__sections { display: flex; gap: var(--space-2); overflow-x: auto; }
.ord__sec { min-block-size: 44px; padding-inline: var(--space-4); border-radius: var(--radius-pill); border: 1px solid var(--border-strong); background: var(--surface-card); font-weight: 600; cursor: pointer; white-space: nowrap; color: var(--text-body); }
.ord__sec[aria-selected='true'] { background: var(--action-primary-bg); color: var(--action-primary-fg); border-color: transparent; }
.ord__pickers { display: flex; gap: var(--space-4); flex-wrap: wrap; }
.ord__seg { display: flex; align-items: center; gap: var(--space-1); flex-wrap: wrap; }
.ord__segb { min-inline-size: var(--touch); min-block-size: 40px; padding-inline: var(--space-2); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); cursor: pointer; font-weight: 600; color: var(--text-body); }
.ord__segb[aria-checked='true'], .ord__segb[aria-pressed='true'] { background: var(--brand-fill); color: var(--brand-on-fill); border-color: var(--nest-yellow-500); }
.ord__items { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--space-2); flex: 1; min-block-size: 0; align-content: start; }
.ord__item { inline-size: 100%; min-block-size: 96px; display: grid; gap: var(--space-1); align-content: space-between; text-align: start; padding: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-subtle); background: var(--surface-card); cursor: pointer; color: var(--text-body); }
.ord__item:disabled { opacity: 0.55; cursor: not-allowed; }
.ord__item-name { font-weight: 600; color: var(--text-strong); overflow-wrap: anywhere; }
.ord__allergens { font-size: var(--text-xs); color: var(--warn-fg); }
.ord__item-foot { display: flex; justify-content: space-between; gap: var(--space-2); font-weight: 600; flex-wrap: wrap; }
.ord__soldout { color: var(--danger-fg); }
.ord__check { display: flex; flex-direction: column; min-block-size: 0; background: var(--surface-tape); border-inline-start: 1px solid var(--border-subtle); }
.ord__head { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3); border-block-end: 1px dashed var(--border-strong); }
.ord__head > div { flex: 1; min-inline-size: 0; }
.ord__head h1 { font-size: var(--text-lg); }
.ord__back { inline-size: var(--touch); block-size: var(--touch); border: 0; background: transparent; border-radius: var(--radius-md); display: grid; place-items: center; cursor: pointer; color: var(--text-strong); }
.ord__lines { flex: 1; min-block-size: 0; padding: var(--space-2) var(--space-3); }
.ord__course-h { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); color: var(--text-muted); padding-block: var(--space-2); }
.ord__list { list-style: none; margin: 0; padding: 0; }
.ord__line { inline-size: 100%; display: grid; grid-template-columns: auto 1fr auto; gap: var(--space-2); align-items: start; padding: var(--space-2) 0; border: 0; border-block-end: 1px dashed var(--border-subtle); background: transparent; text-align: start; cursor: pointer; color: var(--text-body); }
.ord__line--draft { background: var(--brand-fill); color: var(--brand-on-fill); border-radius: var(--radius-sm); padding-inline: var(--space-2); margin-block-end: 4px; border: 0; }
.ord__qty { font-weight: 700; color: var(--text-strong); }
.ord__line--draft .ord__qty { color: inherit; }
.ord__lname { display: grid; gap: 2px; font-weight: 600; overflow-wrap: anywhere; }
.ord__mods, .ord__note, .ord__lname .muted { font-weight: 400; font-size: var(--text-sm); }
.ord__x { inline-size: 36px; block-size: 36px; border: 0; background: transparent; cursor: pointer; color: inherit; display: grid; place-items: center; }
.ord__foot { padding: var(--space-3); border-block-start: 1px dashed var(--border-strong); display: grid; gap: var(--space-2); }
.ord__total { display: flex; justify-content: space-between; align-items: baseline; font-size: var(--text-lg); }
.ord__total strong { font-size: var(--text-xl); color: var(--text-strong); }
.ord__actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
.ord__actions .n-btn--lg { grid-column: 1 / -1; }
.ord__group { border: 0; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.ord__group legend { font-weight: 600; margin-block-end: var(--space-2); }
.ord__opt { min-block-size: var(--touch); padding-inline: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); cursor: pointer; color: var(--text-body); }
.ord__opt[aria-pressed='true'] { background: var(--brand-fill); color: var(--brand-on-fill); border-color: var(--nest-yellow-500); font-weight: 600; }
.ord__input { min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); padding-inline: var(--space-3); background: var(--surface-card); color: var(--text-strong); }
.ord__allergy { background: var(--warn-bg); color: var(--warn-fg); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); }
.ord__targets { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: var(--space-2); }
.ord__payline { display: flex; justify-content: space-between; align-items: center; gap: var(--space-2); padding-block: var(--space-2); border-block-end: 1px dashed var(--border-subtle); }
@media (max-width: 900px) {
  .ord { grid-template-columns: 1fr; grid-template-rows: minmax(0, 0.8fr) minmax(0, 1.2fr); }
  .ord__pickers { gap: var(--space-2); }
  .ord__check { border-inline-start: 0; border-block-start: 1px solid var(--border-subtle); }
  .ord__items { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
