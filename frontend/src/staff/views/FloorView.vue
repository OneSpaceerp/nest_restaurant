<script setup lang="ts">
// Live floor: tables in their real arrangement on wide screens, a sorted grid on phones. Every table
// shows its state in words (not colour alone), covers, how long it has been seated, and flags for a
// bill request or food waiting at the pass.
// Managers can switch to "Edit layout": drag tables on a snap grid, resize them from the corner
// handle, change shape and seats, add tables and floors, then save the whole plan in one step.
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import NButton from '@shared/components/NButton.vue'
import NQty from '@shared/components/NQty.vue'
import NSheet from '@shared/components/NSheet.vue'
import NState from '@shared/components/NState.vue'
import { toast } from '@shared/components/toast'
import { call, newKey } from '@shared/lib/api'
import { dir, minutesAgo, money, t } from '@shared/lib/i18n'
import { on, onReconnect, poll } from '@shared/lib/realtime'
import { SVC, useTill } from '../state'

interface TableOrder { name: string; status: string; covers: number; waiter: string | null; subtotal_preview: number; paid_amount: number; order_number: number; age_minutes: number; requests: string[]; ready_tickets: number }
interface Table { name: string; floor: string; table_label: string; seats: number; status: string; shape: string; x: number; y: number; w: number; h: number; current_order: string | null; order?: TableOrder }
interface Floor { name: string; floor_name: string; width: number; height: number }
interface Box { x: number; y: number; w: number; h: number; seats: number; shape: string }

const GRID = 20 // plan units; tables snap to it and the dotted background matches it
const MIN = 60

const till = useTill()
const router = useRouter()
const state = ref<{ floors: Floor[]; tables: Table[] } | null>(null)
const error = ref('')
const floor = ref<string | null>(null)
const opening = ref<Table | null>(null)
const covers = ref(2)
const busy = ref(false)
const currency = computed(() => till.register.value?.currency ?? 'USD')
const canEdit = computed(() => Boolean(till.boot.value?.roles.manager))

async function load() {
  try {
    state.value = await call(SVC('floor_state'), { register_name: till.registerName.value }, { method: 'GET' })
    floor.value ??= state.value!.floors[0]?.name ?? null
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
  }
}

const tables = computed(() => (state.value?.tables ?? []).filter((t) => t.floor === floor.value))
const current = computed(() => state.value?.floors.find((f) => f.name === floor.value))
const planW = computed(() => current.value?.width || 1200)
const planH = computed(() => current.value?.height || 800)
const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const tb of tables.value) c[tb.status] = (c[tb.status] ?? 0) + 1
  return c
})

const TONE: Record<string, string> = { Free: 'free', Reserved: 'reserved', Occupied: 'busy', 'Needs Cleaning': 'clean', 'Out of Service': 'off' }

function tap(tb: Table) {
  if (editing.value) return void (selected.value = tb.name)
  if (tb.current_order) return router.push(`/order/${tb.current_order}`)
  if (tb.status === 'Needs Cleaning') return markClean(tb)
  if (tb.status === 'Out of Service') return
  covers.value = Math.min(tb.seats || 2, 2)
  opening.value = tb
}

async function open() {
  busy.value = true
  try {
    const res = await call<{ order: string }>(SVC('open_order'), { register_name: till.registerName.value, table: opening.value!.name, covers: covers.value, service_type: 'Dine-in', request_key: newKey('open-') })
    opening.value = null
    await router.push(`/order/${res.order}`)
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    busy.value = false
  }
}

async function markClean(tb: Table) {
  try {
    await call(SVC('mark_table_clean'), { table: tb.name })
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
  }
}

async function takeaway() {
  const res = await call<{ order: string }>(SVC('open_order'), { register_name: till.registerName.value, service_type: 'Takeaway', request_key: newKey('open-') })
  await router.push(`/order/${res.order}`)
}

// ---------------------------------------------------------------- layout editing (managers)
const editing = ref(false)
const draft = reactive<Record<string, Box>>({})
const selected = ref<string | null>(null)
const canvas = ref<HTMLElement | null>(null)
const saving = ref(false)

const snap = (v: number) => Math.round(v / GRID) * GRID
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi))
const boxOf = (tb: Table): Box => draft[tb.name] ?? { x: tb.x || 0, y: tb.y || 0, w: tb.w || 90, h: tb.h || 90, seats: tb.seats, shape: tb.shape }
const changed = computed(() =>
  Object.entries(draft).filter(([name, b]) => {
    const tb = state.value?.tables.find((x) => x.name === name)
    return tb && (b.x !== (tb.x || 0) || b.y !== (tb.y || 0) || b.w !== (tb.w || 90) || b.h !== (tb.h || 90) || b.seats !== tb.seats || b.shape !== tb.shape)
  }),
)
const sel = computed(() => (selected.value ? tables.value.find((x) => x.name === selected.value) ?? null : null))

function startEditing() {
  editing.value = true
  for (const tb of state.value?.tables ?? []) draft[tb.name] = boxOf(tb)
}
function stopEditing() {
  editing.value = false
  selected.value = null
  for (const k of Object.keys(draft)) delete draft[k]
}
function cancelEditing() {
  if (changed.value.length && !confirm(t('Discard the layout changes?'))) return
  stopEditing()
}

async function saveLayout() {
  saving.value = true
  try {
    const rows = changed.value.map(([name, b]) => ({ name, x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.w), h: Math.round(b.h), seats: b.seats, shape: b.shape }))
    state.value = await call(SVC('save_plan'), { register_name: till.registerName.value, tables: rows })
    toast(t('Floor layout saved'))
    stopEditing()
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    saving.value = false
  }
}

// drag to move, drag the corner handle to resize; the canvas scales plan units to pixels
let drag: { name: string; mode: 'move' | 'size'; px: number; py: number; start: Box; scale: number } | null = null
function down(e: PointerEvent, tb: Table, mode: 'move' | 'size') {
  if (!editing.value || !canvas.value || e.button > 0) return
  e.preventDefault()
  e.stopPropagation()
  selected.value = tb.name
  const rect = canvas.value.getBoundingClientRect()
  drag = { name: tb.name, mode, px: e.clientX, py: e.clientY, start: { ...boxOf(tb) }, scale: planW.value / rect.width }
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}
function move(e: PointerEvent) {
  if (!drag) return
  const flip = dir() === 'rtl' ? -1 : 1
  const dx = (e.clientX - drag.px) * drag.scale * flip
  const dy = (e.clientY - drag.py) * drag.scale
  const b = draft[drag.name]
  if (drag.mode === 'move') {
    b.x = clamp(snap(drag.start.x + dx), 0, planW.value - b.w)
    b.y = clamp(snap(drag.start.y + dy), 0, planH.value - b.h)
  } else {
    b.w = clamp(snap(drag.start.w + dx), MIN, planW.value - b.x)
    b.h = clamp(snap(drag.start.h + dy), MIN, planH.value - b.y)
    if (b.shape === 'Round') b.h = b.w = Math.min(b.w, planH.value - b.y)
  }
}
function up() {
  drag = null
}
function key(e: KeyboardEvent, tb: Table) {
  if (!editing.value) return
  const steps: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
  const s = steps[e.key]
  if (!s) return
  e.preventDefault()
  const b = draft[tb.name]
  const flip = dir() === 'rtl' ? -1 : 1
  if (e.shiftKey) {
    b.w = clamp(b.w + s[0] * flip * GRID, MIN, planW.value - b.x)
    b.h = clamp(b.h + s[1] * GRID, MIN, planH.value - b.y)
  } else {
    b.x = clamp(b.x + s[0] * flip * GRID, 0, planW.value - b.w)
    b.y = clamp(b.y + s[1] * GRID, 0, planH.value - b.h)
  }
}
function setShape(shape: string) {
  const b = sel.value && draft[sel.value.name]
  if (!b) return
  b.shape = shape
  if (shape === 'Round') b.h = b.w = Math.max(b.w, b.h)
  if (shape === 'Rectangle' && b.w === b.h) b.w = clamp(b.w + 2 * GRID, MIN, planW.value - b.x)
}

/** Lay the floor's tables out in tidy rows, keeping their sizes (handy after tables pile up at 0,0). */
function tidy() {
  const gap = 2 * GRID
  let x = gap
  let y = gap
  let row = 0
  for (const tb of [...tables.value].sort((a, b) => a.table_label.localeCompare(b.table_label, undefined, { numeric: true }))) {
    const b = draft[tb.name]
    if (x + b.w + gap > planW.value) {
      x = gap
      y += row + gap
      row = 0
    }
    b.x = snap(x)
    b.y = snap(Math.min(y, planH.value - b.h))
    x += b.w + gap
    row = Math.max(row, b.h)
  }
}

// add table / floor
const adding = ref<null | { kind: 'table'; label: string; seats: number; shape: string } | { kind: 'floor'; label: string }>(null)
function nextLabel() {
  const nums = tables.value.map((x) => parseInt(x.table_label.replace(/\D+/g, ''), 10)).filter((n) => !Number.isNaN(n))
  return String((nums.length ? Math.max(...nums) : 0) + 1).padStart(2, '0')
}
async function confirmAdd() {
  const a = adding.value
  if (!a) return
  busy.value = true
  try {
    const before = new Set(state.value?.tables.map((x) => x.name))
    state.value = a.kind === 'table'
      ? await call(SVC('add_table'), { register_name: till.registerName.value, floor: floor.value, table_label: a.label, seats: a.seats, shape: a.shape })
      : await call(SVC('add_floor'), { register_name: till.registerName.value, floor_name: a.label })
    for (const tb of state.value!.tables) if (!before.has(tb.name)) { draft[tb.name] = boxOf(tb); selected.value = tb.name }
    if (a.kind === 'floor') floor.value = state.value!.floors.at(-1)?.name ?? floor.value
    adding.value = null
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    busy.value = false
  }
}

onBeforeRouteLeave(() => (editing.value && changed.value.length ? confirm(t('Discard the layout changes?')) : true))

const offs: (() => void)[] = []
onMounted(() => {
  void load()
  const refresh = () => void (!editing.value && load())
  offs.push(on('nest_rest:table', refresh), on('nest_rest:order', refresh), on('nest_rest:ticket', refresh), on('nest_rest:service_request', refresh), onReconnect(refresh), poll(refresh, 30000, 6000))
})
onBeforeUnmount(() => offs.forEach((f) => f()))

const style = (tb: Table) => {
  const b = boxOf(tb)
  return { insetInlineStart: `${(b.x / planW.value) * 100}%`, insetBlockStart: `${(b.y / planH.value) * 100}%`, inlineSize: `${(b.w / planW.value) * 100}%`, blockSize: `${(b.h / planH.value) * 100}%` }
}
const gridStyle = computed(() => ({
  aspectRatio: `${planW.value} / ${planH.value}`,
  '--grid-x': `${(GRID / planW.value) * 100}%`,
  '--grid-y': `${(GRID / planH.value) * 100}%`,
}))
const shapeOf = (tb: Table) => (draft[tb.name]?.shape ?? tb.shape).toLowerCase()
</script>

<template>
  <div :class="['floor', { 'floor--editing': editing }]">
    <header class="floor__head">
      <div class="floor__tabs" role="tablist" :aria-label="t('Floors')">
        <button v-for="f in state?.floors ?? []" :key="f.name" type="button" role="tab" :aria-selected="floor === f.name" class="floor__tab" @click="floor = f.name; selected = null">{{ f.floor_name }}</button>
        <button v-if="editing" type="button" class="floor__tab floor__tab--add" @click="adding = { kind: 'floor', label: '' }">+ {{ t('Floor') }}</button>
      </div>
      <template v-if="!editing">
        <p class="floor__counts muted">
          <span v-for="(n, s) in counts" :key="s">{{ t(String(s)) }} <strong class="num">{{ n }}</strong></span>
        </p>
        <NButton v-if="canEdit && state" class="floor__edit-btn" variant="ghost" icon="layout" @click="startEditing">{{ t('Edit layout') }}</NButton>
        <NButton icon="basket" @click="takeaway">{{ t('Takeaway') }}</NButton>
      </template>
      <template v-else>
        <p class="floor__counts muted">{{ changed.length ? t('{0} unsaved changes', changed.length) : t('Drag tables to arrange them. Drag the corner to resize.') }}</p>
        <NButton variant="ghost" icon="plus" :disabled="!floor" @click="adding = { kind: 'table', label: nextLabel(), seats: 4, shape: 'Square' }">{{ t('Add table') }}</NButton>
        <NButton variant="ghost" icon="layout" :disabled="!tables.length" @click="tidy">{{ t('Tidy up') }}</NButton>
        <NButton @click="cancelEditing">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" icon="check" :busy="saving" :disabled="!changed.length" @click="saveLayout">{{ t('Save layout') }}</NButton>
      </template>
    </header>

    <div v-if="editing && sel" class="floor__inspector" role="group" :aria-label="t('Table {0}', sel.table_label)">
      <strong>{{ t('Table {0}', sel.table_label) }}</strong>
      <div class="floor__seg" role="radiogroup" :aria-label="t('Shape')">
        <button v-for="sh in ['Square', 'Round', 'Rectangle']" :key="sh" type="button" role="radio" :aria-checked="draft[sel.name]?.shape === sh" class="floor__segb" @click="setShape(sh)">{{ t(sh) }}</button>
      </div>
      <label class="floor__seats">{{ t('Seats') }} <NQty v-model="draft[sel.name].seats" :min="1" :max="40" :label="t('Seats')" /></label>
    </div>

    <NState v-if="error" kind="error" :title="t('The floor could not be loaded')" :detail="error" :retry="load" />
    <NState v-else-if="!state" kind="loading" :title="t('Loading the floor')" />
    <NState v-else-if="!state.floors.length && !editing" kind="empty" icon="table" :title="t('No floors yet')" :detail="canEdit ? t('Tap Edit layout to add a floor and its tables.') : t('Ask a manager to set up the floor.')" />
    <NState v-else-if="!tables.length && !editing" kind="empty" icon="table" :title="t('No tables on this floor')" :detail="canEdit ? t('Tap Edit layout, then Add table.') : t('Ask a manager to set up the floor.')" />
    <div v-else class="floor__plan scroll" @pointerdown.self="selected = null">
      <p v-if="editing" class="floor__phone-note">{{ t('Arrange tables on a tablet or computer; the phone shows them as a list.') }}</p>
      <div ref="canvas" class="floor__canvas" :style="gridStyle" @pointermove="move" @pointerup="up" @pointercancel="up" @pointerdown.self="selected = null">
        <button
          v-for="tb in tables"
          :key="tb.name"
          type="button"
          :class="['tbl', `tbl--${TONE[tb.status] ?? 'free'}`, `tbl--${shapeOf(tb)}`, { 'tbl--sel': editing && selected === tb.name }]"
          :style="style(tb)"
          :aria-label="editing ? t('Table {0}: use arrow keys to move, Shift + arrows to resize', tb.table_label) : `${t('Table {0}', tb.table_label)}, ${t(tb.status)}${tb.order ? ', ' + t('{0} guests', tb.order.covers) : ''}`"
          @click="tap(tb)"
          @pointerdown="down($event, tb, 'move')"
          @keydown="key($event, tb)"
        >
          <span class="tbl__label">{{ tb.table_label }}</span>
          <template v-if="editing">
            <span class="tbl__state num">{{ t('{0} seats', draft[tb.name]?.seats ?? tb.seats) }}</span>
            <span class="tbl__handle" aria-hidden="true" @pointerdown="down($event, tb, 'size')" />
          </template>
          <template v-else>
            <span class="tbl__state">{{ t(tb.status) }}</span>
            <template v-if="tb.order">
              <span class="tbl__meta num">{{ minutesAgo(tb.order.age_minutes) }} · {{ tb.order.covers }}</span>
              <span v-if="tb.order.requests.includes('Bill')" class="tbl__flag">{{ t('Bill') }}</span>
              <span v-else-if="tb.order.ready_tickets" class="tbl__flag tbl__flag--ready">{{ t('Food ready') }}</span>
              <span class="tbl__amount num">{{ money(tb.order.subtotal_preview, currency) }}</span>
            </template>
          </template>
        </button>
      </div>
    </div>

    <NSheet :open="!!opening" :title="t('Seat table {0}', opening?.table_label ?? '')" @close="opening = null">
      <label class="stack"><span>{{ t('Guests') }}</span><NQty v-model="covers" :min="1" :max="40" :label="t('Guests')" /></label>
      <template #actions>
        <NButton @click="opening = null">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" :busy="busy" @click="open">{{ t('Open table') }}</NButton>
      </template>
    </NSheet>

    <NSheet :open="!!adding" :title="adding?.kind === 'floor' ? t('Add floor') : t('Add table')" @close="adding = null">
      <form v-if="adding" class="stack" @submit.prevent="confirmAdd">
        <label class="stack"><span>{{ adding.kind === 'floor' ? t('Floor name') : t('Table name or number') }}</span><input v-model="adding.label" class="floor__input" maxlength="60" required /></label>
        <template v-if="adding.kind === 'table'">
          <label class="stack"><span>{{ t('Seats') }}</span><NQty v-model="adding.seats" :min="1" :max="40" :label="t('Seats')" /></label>
          <div class="floor__seg" role="radiogroup" :aria-label="t('Shape')">
            <button v-for="sh in ['Square', 'Round', 'Rectangle']" :key="sh" type="button" role="radio" :aria-checked="adding.shape === sh" class="floor__segb" @click="adding.shape = sh">{{ t(sh) }}</button>
          </div>
        </template>
      </form>
      <template #actions>
        <NButton @click="adding = null">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" :busy="busy" :disabled="!adding?.label.trim()" @click="confirmAdd">{{ t('Add') }}</NButton>
      </template>
    </NSheet>
  </div>
</template>

<style>
.floor { flex: 1; min-block-size: 0; display: flex; flex-direction: column; }
.floor__head { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); flex-wrap: wrap; }
.floor__tabs { display: flex; gap: var(--space-2); overflow-x: auto; }
.floor__tab { min-block-size: 40px; padding-inline: var(--space-4); border-radius: var(--radius-pill); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-body); font-weight: 600; cursor: pointer; white-space: nowrap; }
.floor__tab[aria-selected='true'] { background: var(--action-primary-bg); color: var(--action-primary-fg); border-color: transparent; }
.floor__tab--add { border-style: dashed; }
.floor__counts { flex: 1; display: flex; gap: var(--space-4); flex-wrap: wrap; font-size: var(--text-sm); }
.floor__inspector { display: flex; align-items: center; gap: var(--space-4); flex-wrap: wrap; margin-inline: var(--space-4); padding: var(--space-2) var(--space-4); background: var(--surface-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); }
.floor__seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius-md); overflow: hidden; }
.floor__segb { min-block-size: 40px; padding-inline: var(--space-3); border: 0; background: var(--surface-card); color: var(--text-body); cursor: pointer; font-weight: 600; }
.floor__segb + .floor__segb { border-inline-start: 1px solid var(--border-strong); }
.floor__segb[aria-checked='true'] { background: var(--brand-fill); color: var(--brand-on-fill); }
.floor__seats { display: inline-flex; align-items: center; gap: var(--space-2); font-weight: 600; }
.floor__input { min-block-size: var(--touch); padding-inline: var(--space-3); border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-card); color: var(--text-strong); font: inherit; }
.floor__plan { flex: 1; min-block-size: 0; padding: var(--space-3) var(--space-4) var(--space-5); }
.floor__phone-note { display: none; }
.floor__canvas { position: relative; inline-size: 100%; max-inline-size: 1400px; margin-inline: auto; background:
  radial-gradient(circle at 1px 1px, var(--border-subtle) 1px, transparent 0) 0 0 / 24px 24px, var(--surface-card); border-radius: var(--radius-lg); box-shadow: var(--shadow-raised); }
/* edit mode: the dots become the snap grid, so a table always lands on one */
.floor--editing .floor__canvas { background: radial-gradient(circle at 1px 1px, var(--border-strong) 1.2px, transparent 0) 0 0 / var(--grid-x) var(--grid-y), var(--surface-card); outline: 2px dashed var(--border-strong); outline-offset: 4px; touch-action: none; }
.tbl { position: absolute; display: grid; align-content: center; justify-items: center; gap: 2px; padding: 4px; border-radius: var(--radius-md); border: 2px solid transparent; cursor: pointer; text-align: center; overflow: hidden; min-inline-size: 64px; min-block-size: 64px; font-size: var(--text-sm); }
.tbl--round { border-radius: 50%; }
.tbl__label { font-size: var(--text-lg); font-weight: 700; }
.tbl__state { font-weight: 600; font-size: var(--text-xs); }
.tbl__meta, .tbl__amount { font-size: var(--text-xs); }
.tbl__flag { font-size: var(--text-xs); font-weight: 700; background: var(--nest-ink-900); color: var(--nest-yellow-400); padding: 1px 8px; border-radius: var(--radius-pill); }
.tbl__flag--ready { background: var(--nest-green-700); color: #fff; }
.tbl--free { background: var(--surface-card); border-color: var(--border-strong); color: var(--text-body); border-style: dashed; }
.tbl--reserved { background: var(--info-bg); border-color: var(--info-fg); color: var(--info-fg); }
.tbl--busy { background: var(--brand-fill); border-color: var(--nest-yellow-500); color: var(--brand-on-fill); }
.tbl--clean { background: var(--warn-bg); border-color: var(--warn-fg); color: var(--warn-fg); }
.tbl--off { background: var(--surface-sunken); color: var(--text-muted); cursor: not-allowed; }
.floor--editing .tbl { cursor: grab; border-style: solid; overflow: visible; user-select: none; touch-action: none; transition: box-shadow var(--dur-fast); }
.floor--editing .tbl:active { cursor: grabbing; }
.floor--editing .tbl--sel { box-shadow: 0 0 0 3px var(--focus-ring), var(--shadow-overlay); z-index: 2; }
.tbl__handle { position: absolute; inset-block-end: -8px; inset-inline-end: -8px; inline-size: 22px; block-size: 22px; border-radius: 50%; background: var(--action-primary-bg); border: 3px solid var(--surface-card); cursor: nwse-resize; touch-action: none; }
[dir='rtl'] .tbl__handle { cursor: nesw-resize; }
@media (max-width: 760px) {
  .floor__canvas { aspect-ratio: auto !important; display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: var(--space-2); background: none !important; box-shadow: none; outline: 0 !important; }
  .tbl { position: static; inline-size: auto !important; block-size: auto !important; min-block-size: 104px; border-radius: var(--radius-md) !important; }
  .tbl__handle { display: none; }
  .floor__phone-note { display: block; color: var(--text-muted); font-size: var(--text-sm); margin-block-end: var(--space-2); }
  .floor__edit-btn { display: none; }
}
</style>
