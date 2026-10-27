<script setup lang="ts">
// Live floor: tables in their real arrangement on wide screens, a sorted grid on phones. Every table
// shows its state in words (not colour alone), covers, how long it has been seated, and flags for a
// bill request or food waiting at the pass.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import NButton from '@shared/components/NButton.vue'
import NQty from '@shared/components/NQty.vue'
import NSheet from '@shared/components/NSheet.vue'
import NState from '@shared/components/NState.vue'
import { toast } from '@shared/components/toast'
import { call, newKey } from '@shared/lib/api'
import { minutesAgo, money, t } from '@shared/lib/i18n'
import { on, onReconnect, poll } from '@shared/lib/realtime'
import { SVC, useTill } from '../state'

interface TableOrder { name: string; status: string; covers: number; waiter: string | null; subtotal_preview: number; paid_amount: number; order_number: number; age_minutes: number; requests: string[]; ready_tickets: number }
interface Table { name: string; floor: string; table_label: string; seats: number; status: string; shape: string; x: number; y: number; w: number; h: number; current_order: string | null; order?: TableOrder }
interface Floor { name: string; floor_name: string; width: number; height: number }

const till = useTill()
const router = useRouter()
const state = ref<{ floors: Floor[]; tables: Table[] } | null>(null)
const error = ref('')
const floor = ref<string | null>(null)
const opening = ref<Table | null>(null)
const covers = ref(2)
const busy = ref(false)
const currency = computed(() => till.register.value?.currency ?? 'USD')

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
const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const tb of tables.value) c[tb.status] = (c[tb.status] ?? 0) + 1
  return c
})

const TONE: Record<string, string> = { Free: 'free', Reserved: 'reserved', Occupied: 'busy', 'Needs Cleaning': 'clean', 'Out of Service': 'off' }

function tap(tb: Table) {
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

const offs: (() => void)[] = []
onMounted(() => {
  void load()
  offs.push(on('nest_rest:table', () => void load()), on('nest_rest:order', () => void load()), on('nest_rest:ticket', () => void load()), on('nest_rest:service_request', () => void load()), onReconnect(() => void load()), poll(load, 30000, 6000))
})
onBeforeUnmount(() => offs.forEach((f) => f()))

const style = (tb: Table) => {
  const f = current.value
  if (!f) return {}
  return { insetInlineStart: `${(tb.x / f.width) * 100}%`, insetBlockStart: `${(tb.y / f.height) * 100}%`, inlineSize: `${(tb.w / f.width) * 100}%`, blockSize: `${(tb.h / f.height) * 100}%` }
}
</script>

<template>
  <div class="floor">
    <header class="floor__head">
      <div class="floor__tabs" role="tablist" :aria-label="t('Floors')">
        <button v-for="f in state?.floors ?? []" :key="f.name" type="button" role="tab" :aria-selected="floor === f.name" class="floor__tab" @click="floor = f.name">{{ f.floor_name }}</button>
      </div>
      <p class="floor__counts muted">
        <span v-for="(n, s) in counts" :key="s">{{ t(String(s)) }} <strong class="num">{{ n }}</strong></span>
      </p>
      <NButton icon="basket" @click="takeaway">{{ t('Takeaway') }}</NButton>
    </header>
    <NState v-if="error" kind="error" :title="t('The floor could not be loaded')" :detail="error" :retry="load" />
    <NState v-else-if="!state" kind="loading" :title="t('Loading the floor')" />
    <NState v-else-if="!tables.length" kind="empty" icon="table" :title="t('No tables on this floor')" :detail="t('A manager can add tables in Desk → Nest Restaurant → Floor.')" />
    <div v-else class="floor__plan scroll">
      <div class="floor__canvas" :style="{ aspectRatio: `${current?.width ?? 4} / ${current?.height ?? 3}` }">
        <button
          v-for="tb in tables"
          :key="tb.name"
          type="button"
          :class="['tbl', `tbl--${TONE[tb.status] ?? 'free'}`, `tbl--${tb.shape.toLowerCase()}`]"
          :style="style(tb)"
          :aria-label="`${t('Table {0}', tb.table_label)}, ${t(tb.status)}${tb.order ? ', ' + t('{0} guests', tb.order.covers) : ''}`"
          @click="tap(tb)"
        >
          <span class="tbl__label">{{ tb.table_label }}</span>
          <span class="tbl__state">{{ t(tb.status) }}</span>
          <template v-if="tb.order">
            <span class="tbl__meta num">{{ minutesAgo(tb.order.age_minutes) }} · {{ tb.order.covers }}</span>
            <span v-if="tb.order.requests.includes('Bill')" class="tbl__flag">{{ t('Bill') }}</span>
            <span v-else-if="tb.order.ready_tickets" class="tbl__flag tbl__flag--ready">{{ t('Food ready') }}</span>
            <span class="tbl__amount num">{{ money(tb.order.subtotal_preview, currency) }}</span>
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
  </div>
</template>

<style>
.floor { flex: 1; min-block-size: 0; display: flex; flex-direction: column; }
.floor__head { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); flex-wrap: wrap; }
.floor__tabs { display: flex; gap: var(--space-2); overflow-x: auto; }
.floor__tab { min-block-size: 40px; padding-inline: var(--space-4); border-radius: var(--radius-pill); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-body); font-weight: 600; cursor: pointer; white-space: nowrap; }
.floor__tab[aria-selected='true'] { background: var(--action-primary-bg); color: var(--action-primary-fg); border-color: transparent; }
.floor__counts { flex: 1; display: flex; gap: var(--space-4); flex-wrap: wrap; font-size: var(--text-sm); }
.floor__plan { flex: 1; min-block-size: 0; padding: var(--space-3) var(--space-4) var(--space-5); }
.floor__canvas { position: relative; inline-size: 100%; max-inline-size: 1400px; margin-inline: auto; background:
  radial-gradient(circle at 1px 1px, var(--border-subtle) 1px, transparent 0) 0 0 / 24px 24px, var(--surface-card); border-radius: var(--radius-lg); box-shadow: var(--shadow-raised); }
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
@media (max-width: 760px) {
  .floor__canvas { aspect-ratio: auto !important; display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: var(--space-2); background: none; box-shadow: none; }
  .tbl { position: static; inline-size: auto !important; block-size: auto !important; min-block-size: 104px; border-radius: var(--radius-md) !important; }
}
</style>
