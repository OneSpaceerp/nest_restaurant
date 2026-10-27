<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import NButton from '@shared/components/NButton.vue'
import NIcon from '@shared/components/NIcon.vue'
import NState from '@shared/components/NState.vue'
import { toast } from '@shared/components/toast'
import { call } from '@shared/lib/api'
import { minutesAgo, t } from '@shared/lib/i18n'
import { connected, on, onReconnect, poll, subscribeDoc } from '@shared/lib/realtime'
import { SVC, useTill } from '../state'

interface TicketLine { item_name: string; qty: number; course: number; seat: number | null; note: string | null; modifiers: string | null }
interface Ticket { name: string; order: string; status: 'New' | 'Preparing' | 'Ready'; kind: string; table_label: string | null; order_number: number; service_type: string; age_minutes: number; timing: 'on_time' | 'warning' | 'late'; lines: TicketLine[] }

const props = defineProps<{ station?: string }>()
const till = useTill()
const router = useRouter()
const stations = ref<{ name: string; station_name: string }[] | null>(null)
const board = ref<{ station_name: string; tickets: Ticket[] } | null>(null)
const error = ref('')
const busy = ref<string | null>(null)
const sound = ref(localStorage.getItem('nest_rest:kds_sound') !== 'off')
let known = new Set<string>()

async function loadStations() {
  stations.value = await call(SVC('stations'), { register_name: till.registerName.value }, { method: 'GET' })
  if (!props.station && stations.value?.length === 1) await router.replace(`/kitchen/${encodeURIComponent(stations.value[0].name)}`)
}
async function load() {
  if (!props.station) return
  try {
    const b = await call<{ station_name: string; tickets: Ticket[] }>(SVC('kitchen_board'), { station: props.station }, { method: 'GET' })
    const fresh = b.tickets.filter((x) => x.status === 'New' && !known.has(x.name))
    if (known.size && fresh.length) chime()
    known = new Set(b.tickets.map((x) => x.name))
    board.value = b
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
  }
}

function chime() {
  if (!sound.value) return
  try {
    const ctx = new AudioContext()
    for (const [i, f] of [880, 1320].entries()) {
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.frequency.value = f
      g.gain.setValueAtTime(0.15, ctx.currentTime + i * 0.18)
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.18 + 0.16)
      o.connect(g).connect(ctx.destination)
      o.start(ctx.currentTime + i * 0.18)
      o.stop(ctx.currentTime + i * 0.18 + 0.17)
    }
  } catch {
    /* audio blocked until the first tap: the visual "New" column still shows it */
  }
}
watch(sound, (v) => localStorage.setItem('nest_rest:kds_sound', v ? 'on' : 'off'))

async function move(tk: Ticket, status: string) {
  busy.value = tk.name
  try {
    await call(SVC('ticket_status'), { ticket: tk.name, status })
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    busy.value = null
  }
}

const columns = computed(() => {
  const all = board.value?.tickets ?? []
  return [
    { key: 'New', label: t('New'), tickets: all.filter((x) => x.status === 'New') },
    { key: 'Preparing', label: t('Preparing'), tickets: all.filter((x) => x.status === 'Preparing') },
    { key: 'Ready', label: t('Ready'), tickets: all.filter((x) => x.status === 'Ready') },
  ]
})
const NEXT: Record<string, [string, string]> = { New: ['Preparing', 'Start preparing'], Preparing: ['Ready', 'Mark ready'], Ready: ['Served', 'Mark served'] }
const BACK: Record<string, string> = { Preparing: 'New', Ready: 'Preparing' }

const offs: (() => void)[] = []
let unsub: (() => void) | null = null
watch(() => props.station, (s) => {
  unsub?.()
  known = new Set()
  board.value = null
  if (s) {
    unsub = subscribeDoc('Nest Restaurant Station', s)
    void load()
  }
}, { immediate: true })
onMounted(() => {
  void loadStations().catch((e) => (error.value = e.message))
  offs.push(on('nest_rest:ticket', () => void load()), onReconnect(() => void load()), poll(load, 20000, 4000))
})
onBeforeUnmount(() => { offs.forEach((f) => f()); unsub?.() })
</script>

<template>
  <div class="kds" data-theme="dark">
    <header class="kds__head">
      <h1>{{ board?.station_name ?? t('Kitchen') }}</h1>
      <select v-if="stations && stations.length > 1" class="kds__select" :value="station ?? ''" :aria-label="t('Station')" @change="router.replace(`/kitchen/${encodeURIComponent(($event.target as HTMLSelectElement).value)}`)">
        <option value="" disabled>{{ t('Choose a station') }}</option>
        <option v-for="s in stations" :key="s.name" :value="s.name">{{ s.station_name }}</option>
      </select>
      <span class="spacer" />
      <span :class="['kds__conn', { 'kds__conn--off': !connected }]" role="status">
        <NIcon :name="connected ? 'check' : 'offline'" :size="16" />{{ connected ? t('Live') : t('Reconnecting — checking every few seconds') }}
      </span>
      <button type="button" class="kds__sound" :aria-pressed="sound" :aria-label="sound ? t('Mute new-ticket sound') : t('Turn new-ticket sound on')" @click="sound = !sound">
        <NIcon :name="sound ? 'bell' : 'close'" />{{ sound ? t('Sound on') : t('Muted') }}
      </button>
    </header>
    <NState v-if="error" kind="error" :title="t('The kitchen board could not be loaded')" :detail="error" :retry="load" />
    <NState v-else-if="!station" kind="empty" icon="chef" :title="t('Choose a station')" />
    <NState v-else-if="!board" kind="loading" :title="t('Loading tickets')" />
    <div v-else class="kds__cols">
      <section v-for="c in columns" :key="c.key" class="kds__col" :aria-label="c.label">
        <h2 class="kds__col-h">{{ c.label }} <span class="num">{{ c.tickets.length }}</span></h2>
        <ol class="kds__list" role="list">
          <li v-for="tk in c.tickets" :key="tk.name" :class="['tk', `tk--${tk.timing}`, { 'tk--void': tk.kind === 'Void' }]">
            <header class="tk__head">
              <strong class="tk__where">{{ tk.table_label ? t('Table {0}', tk.table_label) : t(tk.service_type) }}</strong>
              <span class="num">#{{ tk.order_number }}</span>
              <span class="tk__age num" :aria-label="t('Waiting {0}', minutesAgo(tk.age_minutes))">
                <NIcon name="clock" :size="16" />{{ minutesAgo(tk.age_minutes) }}<template v-if="tk.timing === 'late'"> · {{ t('Late') }}</template>
              </span>
            </header>
            <p v-if="tk.kind !== 'Order'" class="tk__kind">{{ tk.kind === 'Void' ? t('VOID — stop these') : tk.kind === 'Recovery' ? t('Recovered ticket') : t('Addition') }}</p>
            <ul class="tk__lines" role="list">
              <li v-for="(l, i) in tk.lines" :key="i">
                <span class="tk__qty num">{{ Math.abs(l.qty) }}</span>
                <span>
                  {{ l.item_name }}
                  <span v-if="l.modifiers" class="tk__mod">{{ l.modifiers }}</span>
                  <span v-if="l.note" class="tk__note">“{{ l.note }}”</span>
                  <span v-if="l.seat" class="tk__mod">{{ t('Seat {0}', l.seat) }}</span>
                </span>
              </li>
            </ul>
            <footer class="tk__foot">
              <NButton v-if="BACK[tk.status] && tk.kind !== 'Void'" size="sm" variant="ghost" icon="undo" :disabled="busy === tk.name" @click="move(tk, BACK[tk.status])">{{ t('Recall') }}</NButton>
              <NButton v-if="tk.kind === 'Void'" variant="danger" size="lg" icon="check" :busy="busy === tk.name" @click="move(tk, 'Cancelled')">{{ t('Stopped — clear ticket') }}</NButton>
              <NButton v-else variant="brand" size="lg" :busy="busy === tk.name" @click="move(tk, NEXT[tk.status][0])">{{ t(NEXT[tk.status][1]) }}</NButton>
            </footer>
          </li>
        </ol>
      </section>
    </div>
  </div>
</template>

<style>
.kds { flex: 1; min-block-size: 0; display: flex; flex-direction: column; background: var(--surface-page); color: var(--text-body); }
.kds__head { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); flex-wrap: wrap; }
.kds__head h1 { font-size: var(--text-xl); }
.kds__select { min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); padding-inline: var(--space-3); }
.kds__conn { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; color: var(--ok-fg); }
.kds__conn--off { color: var(--warn-fg); }
.kds__sound { display: inline-flex; align-items: center; gap: 6px; min-block-size: var(--touch); padding-inline: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); cursor: pointer; font-weight: 600; }
.kds__cols { flex: 1; min-block-size: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); padding: 0 var(--space-4) var(--space-4); }
.kds__col { display: flex; flex-direction: column; min-block-size: 0; background: var(--surface-sunken); border-radius: var(--radius-lg); }
.kds__col-h { display: flex; justify-content: space-between; padding: var(--space-3) var(--space-4); font-size: var(--text-lg); }
.kds__list { list-style: none; margin: 0; padding: 0 var(--space-3) var(--space-3); display: grid; gap: var(--space-3); overflow-y: auto; align-content: start; }
.tk { background: var(--surface-card); border-radius: var(--radius-md); padding: var(--space-3); display: grid; gap: var(--space-2); border-inline-start: 6px solid var(--border-strong); }
.tk--warning { border-inline-start-color: var(--warn-fg); }
.tk--late { border-inline-start-color: var(--danger-fg); box-shadow: 0 0 0 1px var(--danger-fg); }
.tk--void { background: var(--danger-bg); }
.tk__head { display: flex; align-items: baseline; gap: var(--space-2); flex-wrap: wrap; }
.tk__where { font-size: var(--text-lg); color: var(--text-strong); }
.tk__age { margin-inline-start: auto; display: inline-flex; align-items: center; gap: 4px; font-weight: 600; }
.tk--late .tk__age { color: var(--danger-fg); }
.tk__kind { font-weight: 700; color: var(--danger-fg); }
.tk__lines { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); font-size: var(--text-lg); }
.tk__lines li { display: grid; grid-template-columns: 2.2em 1fr; gap: var(--space-2); }
.tk__qty { font-weight: 700; color: var(--brand-text); }
.tk__mod, .tk__note { display: block; font-size: var(--text-md); color: var(--text-muted); }
.tk__note { color: var(--warn-fg); font-weight: 600; }
.tk__foot { display: flex; gap: var(--space-2); justify-content: flex-end; }
.tk__foot .n-btn--lg { flex: 1; }
@media (max-width: 900px) { .kds__cols { grid-template-columns: 1fr; overflow-y: auto; } .kds__col { min-block-size: auto; } }
</style>
