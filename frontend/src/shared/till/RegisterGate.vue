<script setup lang="ts">
// Before selling: choose an assigned register, then open (or resume) its shift with a float per tender.
import { ref } from 'vue'
import NButton from '../components/NButton.vue'
import NIcon from '../components/NIcon.vue'
import NState from '../components/NState.vue'
import { toast } from '../components/toast'
import { call } from '../lib/api'
import { money, t } from '../lib/i18n'
import type { Till } from './till'

const props = defineProps<{ till: Till }>()
const tl = props.till
const floats = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')

async function open() {
  busy.value = true
  error.value = ''
  try {
    const res = await call<{ session: string }>(tl.api('open_register'), {
      register_name: tl.registerName.value,
      floats: Object.entries(floats.value).map(([mode_of_payment, amount]) => ({ mode_of_payment, amount: Number(amount) || 0 })),
    })
    tl.register.value!.session = res.session
    toast(t('Register open'))
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="gate scroll">
    <NState v-if="!tl.boot.value" kind="loading" :title="t('Getting your registers')" />
    <NState v-else-if="!tl.boot.value.registers.length" kind="denied" :title="t('No register is assigned to you')" :detail="t('Ask a manager to add you to a register.')" />
    <section v-else-if="!tl.registerName.value" class="gate__card">
      <h1>{{ t('Choose a register') }}</h1>
      <ul class="gate__list" role="list">
        <li v-for="r in tl.boot.value.registers" :key="r.register">
          <button type="button" class="gate__reg" @click="tl.useRegister(r.register)">
            <NIcon name="register" :size="28" />
            <span><strong>{{ r.register }}</strong><span class="muted">{{ r.outlet_label || r.company }}</span></span>
            <span :class="['gate__open', { 'gate__open--yes': r.session }]">{{ r.session ? t('Shift open') : t('Closed') }}</span>
          </button>
        </li>
      </ul>
    </section>
    <form v-else-if="!tl.sessionOpen.value" class="gate__card" @submit.prevent="open">
      <h1>{{ t('Open {0}', tl.registerName.value) }}</h1>
      <p class="muted">{{ t('Count the money in the drawer and enter the opening float.') }}</p>
      <label v-for="m in tl.register.value!.payment_modes" :key="m.mode_of_payment" class="gate__float">
        <span>{{ m.mode_of_payment }}</span>
        <input v-model="floats[m.mode_of_payment]" class="gate__input num" inputmode="decimal" :placeholder="money(0, tl.register.value!.currency)" />
      </label>
      <p v-if="tl.register.value!.invoice_mode === 'Consolidated'" class="gate__note">{{ t('This register posts POS Invoices that ERPNext consolidates at closing. The shift must close before midnight.') }}</p>
      <p v-if="error" class="gate__err" role="alert">{{ error }}</p>
      <div class="row">
        <NButton v-if="tl.boot.value.registers.length > 1" @click="tl.registerName.value = null">{{ t('Other register') }}</NButton>
        <div class="spacer" />
        <NButton type="submit" variant="primary" size="lg" :busy="busy" :disabled="!tl.online.value">{{ t('Open register') }}</NButton>
      </div>
      <p v-if="!tl.online.value" class="muted">{{ t('Opening a shift needs a connection.') }}</p>
    </form>
  </div>
</template>

<style>
.gate { flex: 1; display: grid; place-items: start center; padding: var(--space-6) var(--space-4); }
.gate__card { inline-size: min(560px, 100%); background: var(--surface-card); border-radius: var(--radius-lg); padding: var(--space-6); box-shadow: var(--shadow-raised); display: grid; gap: var(--space-4); }
.gate__list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.gate__reg { inline-size: 100%; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: var(--space-3); padding: var(--space-4); border-radius: var(--radius-md); border: 1px solid var(--border-subtle); background: var(--surface-card); cursor: pointer; text-align: start; color: var(--text-body); }
.gate__reg:hover { border-color: var(--text-strong); }
.gate__reg strong { display: block; color: var(--text-strong); }
.gate__open { font-size: var(--text-sm); font-weight: 600; color: var(--text-muted); }
.gate__open--yes { color: var(--ok-fg); }
.gate__float { display: grid; grid-template-columns: 1fr minmax(0, 10rem); align-items: center; gap: var(--space-3); }
.gate__input { min-block-size: var(--touch-lg); border-radius: var(--radius-md); border: 1px solid var(--border-strong); padding-inline: var(--space-3); text-align: end; background: var(--surface-card); color: var(--text-strong); font-size: var(--text-lg); }
.gate__note { background: var(--info-bg); color: var(--info-fg); padding: var(--space-3); border-radius: var(--radius-md); }
.gate__err { color: var(--danger-fg); font-weight: 600; }
@media (max-width: 520px) { .gate { padding: var(--space-3); } .gate__card { padding: var(--space-4); } }
</style>
