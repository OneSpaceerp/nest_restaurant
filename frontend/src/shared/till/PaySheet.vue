<script setup lang="ts">
// Tendering: cash with quick amounts and live change, card/bank, split across tenders.
// The server re-validates every tender and computes the posted change; this view previews it.
import { computed, ref, watch } from 'vue'
import NButton from '../components/NButton.vue'
import NIcon from '../components/NIcon.vue'
import NSheet from '../components/NSheet.vue'
import { Dec } from '../lib/decimal'
import { money, t } from '../lib/i18n'
import type { PaymentMode } from './till'

const props = defineProps<{ open: boolean; due: number; currency: string; modes: PaymentMode[]; online: boolean; busy: boolean; error: string }>()
const emit = defineEmits<{ close: []; pay: [{ mode_of_payment: string; amount: string }[]] }>()

const rows = ref<{ mode: string; amount: string }[]>([])
const cashMode = computed(() => props.modes.find((m) => m.type === 'Cash')?.mode_of_payment)
watch(
  () => props.open,
  (o) => {
    if (o) rows.value = [{ mode: props.modes.find((m) => m.default)?.mode_of_payment ?? props.modes[0]?.mode_of_payment ?? '', amount: Dec.of(props.due).toFixed(2) }]
  },
)

const paid = computed(() => rows.value.reduce((a, r) => a.plus(r.amount || 0), Dec.zero))
const remaining = computed(() => Dec.of(props.due).minus(paid.value))
const nonCashOver = computed(() => rows.value.filter((r) => r.mode !== cashMode.value).reduce((a, r) => a.plus(r.amount || 0), Dec.zero).gt(props.due))
const change = computed(() => (remaining.value.lt(0) ? remaining.value.neg() : Dec.zero))
const canPay = computed(() => !props.busy && remaining.value.lte(0) && !nonCashOver.value && rows.value.every((r) => r.mode))

function quick(): number[] {
  const due = props.due
  const steps = [5, 10, 20, 50, 100, 200, 500]
  const out = new Set<number>([Math.ceil(due)])
  for (const s of steps) out.add(Math.ceil(due / s) * s)
  return [...out].filter((v) => v >= due).sort((a, b) => a - b).slice(0, 4)
}

function setCash(v: number) {
  rows.value = [{ mode: cashMode.value!, amount: Dec.of(v).toFixed(2) }]
}
function addSplit() {
  const other = props.modes.find((m) => !rows.value.some((r) => r.mode === m.mode_of_payment))
  rows.value.push({ mode: other?.mode_of_payment ?? props.modes[0].mode_of_payment, amount: remaining.value.gt(0) ? remaining.value.toFixed(2) : '0.00' })
}
function submit() {
  emit('pay', rows.value.filter((r) => Dec.of(r.amount || 0).gt(0)).map((r) => ({ mode_of_payment: r.mode, amount: Dec.of(r.amount).toFixed(2) })))
}
</script>

<template>
  <NSheet :open="open" :title="t('Take payment')" :dismissible="!busy" @close="emit('close')">
    <div class="pay">
      <slot name="part" />
      <div class="pay__due">
        <span>{{ t('Amount due') }}</span>
        <strong class="num">{{ money(due, currency) }}</strong>
      </div>
      <p v-if="!online" class="pay__offline" role="status"><NIcon name="offline" :size="18" />{{ t('Offline: cash only. The sale is kept on this device and posted when the connection returns.') }}</p>

      <div v-if="cashMode" class="pay__quick" role="group" :aria-label="t('Quick cash amounts')">
        <button v-for="v in quick()" :key="v" type="button" class="pay__chip num" @click="setCash(v)">{{ money(v, currency) }}</button>
      </div>

      <div v-for="(r, i) in rows" :key="i" class="pay__row">
        <label class="sr-only" :for="`mode-${i}`">{{ t('Payment method') }}</label>
        <select :id="`mode-${i}`" v-model="r.mode" class="pay__select">
          <option v-for="m in modes" :key="m.mode_of_payment" :value="m.mode_of_payment" :disabled="!online && m.type !== 'Cash'">{{ m.mode_of_payment }}</option>
        </select>
        <label class="sr-only" :for="`amt-${i}`">{{ t('Amount') }}</label>
        <input :id="`amt-${i}`" v-model="r.amount" class="pay__amount num" inputmode="decimal" autocomplete="off" />
        <button v-if="rows.length > 1" type="button" class="pay__x" :aria-label="t('Remove payment')" @click="rows.splice(i, 1)"><NIcon name="close" :size="18" /></button>
      </div>
      <NButton variant="ghost" icon="plus" :disabled="!online || rows.length >= modes.length" @click="addSplit">{{ t('Split payment') }}</NButton>

      <dl class="pay__sum">
        <div><dt>{{ t('Paid') }}</dt><dd class="num">{{ money(paid.toNumber(), currency) }}</dd></div>
        <div v-if="remaining.gt(0)" class="pay__left"><dt>{{ t('Still to pay') }}</dt><dd class="num">{{ money(remaining.toNumber(), currency) }}</dd></div>
        <div v-else class="pay__change"><dt>{{ t('Change') }}</dt><dd class="num">{{ money(change.toNumber(), currency) }}</dd></div>
      </dl>
      <p v-if="nonCashOver" class="pay__err" role="alert">{{ t('Card or account payments cannot exceed the amount due.') }}</p>
      <p v-if="error" class="pay__err" role="alert">{{ error }}</p>
    </div>
    <template #actions>
      <NButton :disabled="busy" @click="emit('close')">{{ t('Back') }}</NButton>
      <NButton variant="primary" size="lg" icon="check" :busy="busy" :disabled="!canPay" @click="submit">{{ t('Complete sale') }}</NButton>
    </template>
  </NSheet>
</template>

<style>
.pay { display: grid; gap: var(--space-4); }
.pay__due { display: flex; justify-content: space-between; align-items: baseline; background: var(--brand-fill); color: var(--brand-on-fill); padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); }
.pay__due strong { font-size: var(--text-2xl); }
.pay__offline { display: flex; gap: var(--space-2); align-items: flex-start; background: var(--warn-bg); color: var(--warn-fg); padding: var(--space-3); border-radius: var(--radius-md); }
.pay__quick { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.pay__chip { min-block-size: var(--touch-lg); min-inline-size: 88px; padding-inline: var(--space-4); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); font-weight: 600; font-size: var(--text-lg); cursor: pointer; color: var(--text-strong); }
.pay__chip:active { background: var(--brand-fill); }
.pay__row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 9rem) auto; gap: var(--space-2); }
.pay__select, .pay__amount { min-block-size: var(--touch-lg); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); padding-inline: var(--space-3); min-inline-size: 0; }
.pay__amount { text-align: end; font-size: var(--text-lg); font-weight: 600; }
.pay__x { inline-size: var(--touch-lg); border: 0; background: transparent; border-radius: var(--radius-md); cursor: pointer; color: var(--text-muted); display: grid; place-items: center; }
.pay__sum { margin: 0; display: grid; gap: var(--space-2); }
.pay__sum div { display: flex; justify-content: space-between; font-size: var(--text-lg); }
.pay__sum dd { margin: 0; font-weight: 700; }
.pay__change { color: var(--ok-fg); }
.pay__left { color: var(--danger-fg); }
.pay__err { color: var(--danger-fg); font-weight: 600; }
</style>
