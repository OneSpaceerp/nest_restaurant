<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import NButton from '@shared/components/NButton.vue'
import NState from '@shared/components/NState.vue'
import NStatus from '@shared/components/NStatus.vue'
import { toast } from '@shared/components/toast'
import { call } from '@shared/lib/api'
import { t, time } from '@shared/lib/i18n'
import { SVC, useTill } from '../state'
import { useRouter } from 'vue-router'

interface Res { name: string; guest_name: string; phone: string; party_size: number; start: string; table: string | null; status: string; source: string; notes: string | null; order: string | null }
const till = useTill()
const router = useRouter()
const day = ref(new Date().toISOString().slice(0, 10))
const rows = ref<Res[] | null>(null)
const error = ref('')
const tables = ref<{ name: string; table_label: string; status: string; seats: number }[]>([])
const seatPick = ref<Record<string, string>>({})

async function load() {
  try {
    rows.value = await call<Res[]>(SVC('reservations'), { register_name: till.registerName.value, day: day.value }, { method: 'GET' })
    const floor = await call<{ tables: typeof tables.value }>(SVC('floor_state'), { register_name: till.registerName.value }, { method: 'GET' })
    tables.value = floor.tables
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
  }
}
onMounted(load)

async function setStatus(r: Res, status: string) {
  try {
    const res = await call<{ order: string | null }>(SVC('reservation_status'), { name: r.name, status, table: seatPick.value[r.name] || r.table })
    if (status === 'Seated' && res.order) return router.push(`/order/${res.order}`)
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
  }
}
const TONE: Record<string, 'brand' | 'info' | 'ok' | 'neutral' | 'danger' | 'warn'> = { Requested: 'brand', Confirmed: 'info', Seated: 'ok', Completed: 'neutral', Cancelled: 'danger', 'No Show': 'warn' }
const free = computed(() => tables.value.filter((x) => ['Free', 'Reserved'].includes(x.status)))
</script>

<template>
  <div class="bk scroll">
    <header class="bk__head">
      <h1>{{ t('Bookings') }}</h1>
      <input v-model="day" type="date" class="bk__date" :aria-label="t('Day')" @change="load" />
    </header>
    <NState v-if="error" kind="error" :title="t('Bookings could not be loaded')" :detail="error" :retry="load" />
    <NState v-else-if="!rows" kind="loading" :title="t('Loading bookings')" />
    <NState v-else-if="!rows.length" kind="empty" icon="calendar" :title="t('No bookings for this day')" />
    <ul v-else class="bk__list" role="list">
      <li v-for="r in rows" :key="r.name" class="bk__row">
        <span class="bk__time num">{{ time(r.start) }}</span>
        <span class="bk__who"><strong>{{ r.guest_name }}</strong> <span class="muted">{{ t('{0} guests', r.party_size) }} · <bdi>{{ r.phone }}</bdi></span><span v-if="r.notes" class="muted">“{{ r.notes }}”</span></span>
        <NStatus :tone="TONE[r.status] ?? 'neutral'" :label="t(r.status)" />
        <span class="bk__act">
          <NButton v-if="r.status === 'Requested'" size="sm" @click="setStatus(r, 'Confirmed')">{{ t('Confirm') }}</NButton>
          <template v-if="r.status === 'Confirmed'">
            <select v-model="seatPick[r.name]" class="bk__date" :aria-label="t('Table for {0}', r.guest_name)">
              <option value="">{{ r.table ?? t('Choose table') }}</option>
              <option v-for="tb in free" :key="tb.name" :value="tb.name">{{ t('Table {0}', tb.table_label) }} ({{ tb.seats }})</option>
            </select>
            <NButton size="sm" variant="primary" @click="setStatus(r, 'Seated')">{{ t('Seat') }}</NButton>
            <NButton size="sm" variant="ghost" @click="setStatus(r, 'No Show')">{{ t('No show') }}</NButton>
          </template>
          <NButton v-if="['Requested', 'Confirmed'].includes(r.status)" size="sm" variant="ghost" @click="setStatus(r, 'Cancelled')">{{ t('Cancel') }}</NButton>
        </span>
      </li>
    </ul>
  </div>
</template>

<style>
.bk { flex: 1; padding: var(--space-5) var(--space-4); display: grid; gap: var(--space-4); align-content: start; max-inline-size: 1100px; margin-inline: auto; inline-size: 100%; }
.bk__head { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); }
.bk__date { min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); padding-inline: var(--space-3); }
.bk__list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.bk__row { display: grid; grid-template-columns: 5rem 1fr auto auto; gap: var(--space-3); align-items: center; background: var(--surface-card); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); box-shadow: var(--shadow-raised); }
.bk__time { font-size: var(--text-lg); font-weight: 700; color: var(--text-strong); }
.bk__who { display: grid; }
.bk__act { display: flex; gap: var(--space-2); flex-wrap: wrap; justify-content: flex-end; }
@media (max-width: 760px) { .bk__row { grid-template-columns: auto 1fr; } .bk__act { grid-column: 1 / -1; justify-content: flex-start; } }
</style>
