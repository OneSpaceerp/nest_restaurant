<script setup lang="ts">
// Counter / takeaway till for cafés: the same catalog + receipt tape + payment as Nest POS, built from
// the shared till, so quick sales don't need a table or a kitchen round.
import { computed, ref } from 'vue'
import NButton from '@shared/components/NButton.vue'
import NSheet from '@shared/components/NSheet.vue'
import NScanner from '@shared/components/NScanner.vue'
import { toast } from '@shared/components/toast'
import { money, t } from '@shared/lib/i18n'
import CartTape from '@shared/till/CartTape.vue'
import CatalogPanel from '@shared/till/CatalogPanel.vue'
import PaySheet from '@shared/till/PaySheet.vue'
import { useTill } from '../state'

const till = useTill()
const currency = computed(() => till.register.value?.currency ?? 'USD')
const due = computed(() => (till.quote.value && till.quoteState.value === 'fresh' ? till.quote.value.amount_due : Number(till.preview.value.total)))
const paying = ref(false)
const scanning = ref(false)
const busy = ref(false)
const error = ref('')
const done = ref<{ name?: string; change?: string; queued: boolean } | null>(null)

async function pay(tenders: { mode_of_payment: string; amount: string }[]) {
  busy.value = true
  error.value = ''
  try {
    const res = (await till.submit(tenders)) as { mode: string; invoice?: { name: string }; change?: string }
    paying.value = false
    done.value = { name: res.invoice?.name, change: res.change, queued: res.mode === 'queued' }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function onScan(code: string) {
  const r = await till.scan(code).catch((e) => ({ status: 'invalid', message: e.message }))
  if (r.status !== 'ok') toast(t('No product for code {0}', code), 'warn')
}
</script>

<template>
  <div class="counter">
    <CatalogPanel :items="till.catalog.value" :currency="currency" :state="till.catalogState.value" @pick="(i) => till.addItem(i)" @scan="onScan" @camera="scanning = true" />
    <CartTape class="counter__tape" :till="till" :title="t('Counter sale')" @pay="paying = true" @hold="() => undefined" @customer="() => undefined" />
    <PaySheet :open="paying" :due="due" :currency="currency" :modes="till.register.value?.payment_modes ?? []" :online="till.online.value" :busy="busy" :error="error" @close="paying = false" @pay="pay" />
    <NSheet :open="scanning" :title="t('Scan')" @close="scanning = false">
      <NScanner v-if="scanning" continuous @code="onScan" @close="scanning = false" />
    </NSheet>
    <NSheet :open="!!done" :title="done?.queued ? t('Sale saved offline') : t('Sale complete')" @close="done = null">
      <p v-if="done?.change && Number(done.change)" class="counter__change">{{ t('Change') }} <strong class="num">{{ money(done.change, currency) }}</strong></p>
      <p v-if="done?.name" class="muted code">{{ done.name }}</p>
      <template #actions><NButton variant="primary" @click="done = null">{{ t('Next sale') }}</NButton></template>
    </NSheet>
  </div>
</template>

<style>
.counter { flex: 1; min-block-size: 0; display: flex; }
.counter__change { font-size: var(--text-xl); }
@media (max-width: 1023px) { .counter { flex-direction: column; } .counter__tape { max-block-size: 55%; } }
</style>
