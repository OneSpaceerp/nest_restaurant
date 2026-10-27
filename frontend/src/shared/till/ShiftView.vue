<script setup lang="ts">
// X report, cash in/out and closing with counted amounts (optionally by denomination).
// Blind close hides the expected figures from cashiers; the server enforces it too.
import { computed, onMounted, ref } from 'vue'
import NButton from '../components/NButton.vue'
import NSheet from '../components/NSheet.vue'
import NState from '../components/NState.vue'
import { toast } from '../components/toast'
import { call, newKey } from '../lib/api'
import { money, t } from '../lib/i18n'
import type { Till } from './till'

const props = defineProps<{ till: Till; denominations?: number[] }>()
const tl = props.till
type Summary = { status: string; sales_count: number; returns_count: number; net_sales: number; by_mode: Record<string, string>; expected?: Record<string, string> }
const summary = ref<Summary | null>(null)
const loadError = ref('')
const counts = ref<Record<string, string>>({})
const denomCounts = ref<Record<string, number>>({})
const reason = ref('')
const busy = ref(false)
const closeError = ref('')
const moveOpen = ref(false)
const move = ref({ direction: 'Out' as 'In' | 'Out', amount: '', reason: '' })
const currency = computed(() => tl.register.value?.currency ?? 'USD')
const cashMode = computed(() => tl.register.value?.payment_modes.find((m) => m.type === 'Cash')?.mode_of_payment)
const denoms = computed(() => props.denominations ?? [200, 100, 50, 20, 10, 5, 1, 0.5, 0.25])

async function load() {
  loadError.value = ''
  try {
    summary.value = await call<Summary>(tl.api('shift_summary'), { register_name: tl.registerName.value }, { method: 'GET' })
  } catch (e) {
    loadError.value = (e as Error).message
  }
}
onMounted(load)

function denomTotal() {
  return Object.entries(denomCounts.value).reduce((a, [v, n]) => a + Number(v) * (n || 0), 0)
}
function applyDenoms() {
  if (cashMode.value) counts.value[cashMode.value] = denomTotal().toFixed(2)
}
function variance(mode: string) {
  if (!summary.value?.expected) return null
  return Number(counts.value[mode] || 0) - Number(summary.value.expected[mode] || 0)
}

async function close() {
  busy.value = true
  closeError.value = ''
  try {
    const res = await call<{ status: string }>(tl.api('close_register'), {
      register_name: tl.registerName.value,
      counts: Object.fromEntries(Object.entries(counts.value).map(([k, v]) => [k, Number(v) || 0])),
      reason: reason.value,
      denominations: cashMode.value ? { [cashMode.value]: Object.entries(denomCounts.value).map(([value, count]) => ({ value, count })) } : null,
    }, { timeoutMs: 60000 })
    tl.register.value!.session = null
    toast(res.status === 'Closed' ? t('Register closed') : t('Closing — ERPNext is consolidating the shift'))
  } catch (e) {
    closeError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function saveMove() {
  busy.value = true
  try {
    await call(tl.api('cash_movement'), { register_name: tl.registerName.value, direction: move.value.direction, amount: Number(move.value.amount), reason: move.value.reason, request_key: newKey('cash-') })
    moveOpen.value = false
    move.value = { direction: 'Out', amount: '', reason: '' }
    toast(t('Cash movement recorded'))
    await load()
  } catch (e) {
    toast((e as Error).message, 'danger')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="shift scroll">
    <NState v-if="loadError" kind="error" :title="t('Shift details could not be loaded')" :detail="loadError" :retry="load" />
    <NState v-else-if="!summary" kind="loading" :title="t('Loading the shift')" />
    <template v-else>
      <section class="shift__card">
        <h1>{{ t('Shift on {0}', tl.registerName.value ?? '') }}</h1>
        <dl class="shift__kpis">
          <div><dt>{{ t('Sales') }}</dt><dd class="num">{{ summary.sales_count }}</dd></div>
          <div><dt>{{ t('Returns') }}</dt><dd class="num">{{ summary.returns_count }}</dd></div>
          <div><dt>{{ t('Net sales') }}</dt><dd class="num">{{ money(summary.net_sales, currency) }}</dd></div>
        </dl>
        <p v-if="tl.pendingCount.value" class="shift__warn" role="status">{{ t('{0} offline sale(s) still need to sync before you can close.', tl.pendingCount.value) }}</p>
        <div class="row">
          <NButton icon="cash" :disabled="!tl.online.value" @click="moveOpen = true">{{ t('Cash in / out') }}</NButton>
        </div>
      </section>

      <form class="shift__card" @submit.prevent="close">
        <h2>{{ t('Close register') }}</h2>
        <p class="muted">{{ summary.expected ? t('Count each tender. Differences need a reason.') : t('Count each tender. The expected amounts are hidden on this register.') }}</p>
        <details v-if="cashMode" class="shift__denoms">
          <summary>{{ t('Count cash by note and coin') }}</summary>
          <div class="shift__denom-grid">
            <label v-for="d in denoms" :key="d" class="shift__denom">
              <span class="num">{{ money(d, currency) }}</span>
              <input v-model.number="denomCounts[d]" type="number" min="0" step="1" inputmode="numeric" class="shift__n num" :aria-label="t('Number of {0}', money(d, currency))" @change="applyDenoms" />
            </label>
          </div>
          <p class="num"><strong>{{ money(denomTotal(), currency) }}</strong></p>
        </details>
        <table class="shift__table">
          <thead><tr><th scope="col">{{ t('Tender') }}</th><th v-if="summary.expected" scope="col">{{ t('Expected') }}</th><th scope="col">{{ t('Counted') }}</th><th v-if="summary.expected" scope="col">{{ t('Difference') }}</th></tr></thead>
          <tbody>
            <tr v-for="m in tl.register.value!.payment_modes" :key="m.mode_of_payment">
              <th scope="row">{{ m.mode_of_payment }}</th>
              <td v-if="summary.expected" class="num">{{ money(summary.expected[m.mode_of_payment] ?? 0, currency) }}</td>
              <td><input v-model="counts[m.mode_of_payment]" class="shift__count num" inputmode="decimal" :aria-label="t('Counted {0}', m.mode_of_payment)" /></td>
              <td v-if="summary.expected" :class="['num', { 'shift__off': variance(m.mode_of_payment) }]">
                {{ variance(m.mode_of_payment) === null ? '' : money(variance(m.mode_of_payment)!, currency) }}
              </td>
            </tr>
          </tbody>
        </table>
        <label class="stack"><span>{{ t('Reason for the difference') }}</span><textarea v-model="reason" class="shift__reason" rows="2" maxlength="500" /></label>
        <p v-if="closeError" class="shift__err" role="alert">{{ closeError }}</p>
        <NButton type="submit" variant="primary" size="lg" :busy="busy" :disabled="!tl.online.value || tl.pendingCount.value > 0">{{ t('Close register') }}</NButton>
      </form>
    </template>

    <NSheet :open="moveOpen" :title="t('Cash in / out')" @close="moveOpen = false">
      <div class="stack">
        <div class="row" role="radiogroup" :aria-label="t('Direction')">
          <NButton :variant="move.direction === 'In' ? 'primary' : 'secondary'" role="radio" :aria-checked="move.direction === 'In'" @click="move.direction = 'In'">{{ t('Cash in') }}</NButton>
          <NButton :variant="move.direction === 'Out' ? 'primary' : 'secondary'" role="radio" :aria-checked="move.direction === 'Out'" @click="move.direction = 'Out'">{{ t('Cash out') }}</NButton>
        </div>
        <label class="stack"><span>{{ t('Amount') }}</span><input v-model="move.amount" class="shift__count num" inputmode="decimal" /></label>
        <label class="stack"><span>{{ t('Reason') }}</span><input v-model="move.reason" class="shift__count" maxlength="140" /></label>
        <p v-if="move.direction === 'Out' && !tl.boot.value?.roles.supervisor" class="muted">{{ t('Cash out needs a supervisor approval.') }}</p>
      </div>
      <template #actions>
        <NButton @click="moveOpen = false">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" :busy="busy" :disabled="!Number(move.amount) || !move.reason.trim()" @click="saveMove">{{ t('Save') }}</NButton>
      </template>
    </NSheet>
  </div>
</template>

<style>
.shift { flex: 1; padding: var(--space-5) var(--space-4); display: grid; gap: var(--space-4); align-content: start; justify-items: center; }
.shift__card { inline-size: min(720px, 100%); background: var(--surface-card); border-radius: var(--radius-lg); padding: var(--space-5); box-shadow: var(--shadow-raised); display: grid; gap: var(--space-4); }
.shift__kpis { margin: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.shift__kpis div { background: var(--surface-sunken); border-radius: var(--radius-md); padding: var(--space-3); }
.shift__kpis dt { color: var(--text-muted); font-size: var(--text-sm); }
.shift__kpis dd { margin: 0; font-size: var(--text-xl); font-weight: 700; color: var(--text-strong); }
.shift__warn { background: var(--warn-bg); color: var(--warn-fg); padding: var(--space-3); border-radius: var(--radius-md); font-weight: 600; }
.shift__table { inline-size: 100%; border-collapse: collapse; }
.shift__table th, .shift__table td { padding: var(--space-2); text-align: start; border-block-end: 1px solid var(--border-subtle); }
.shift__table td.num { text-align: end; }
.shift__count, .shift__reason { inline-size: 100%; min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); padding-inline: var(--space-3); background: var(--surface-card); color: var(--text-strong); }
.shift__count { text-align: end; }
.shift__off { color: var(--danger-fg); font-weight: 700; }
.shift__err { color: var(--danger-fg); font-weight: 600; }
.shift__denoms summary { cursor: pointer; font-weight: 600; min-block-size: var(--touch); display: flex; align-items: center; }
.shift__denom-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--space-2); margin-block: var(--space-3); }
.shift__denom { display: grid; grid-template-columns: 1fr 5rem; align-items: center; gap: var(--space-2); }
.shift__n { min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); text-align: end; padding-inline: var(--space-2); background: var(--surface-card); color: var(--text-strong); }
@media (max-width: 520px) { .shift__kpis { grid-template-columns: 1fr; } .shift__card { padding: var(--space-4); } }
</style>
