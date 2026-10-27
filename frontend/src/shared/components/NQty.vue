<script setup lang="ts">
import NIcon from './NIcon.vue'
import { qty as fmt, t } from '../lib/i18n'

const props = withDefaults(defineProps<{ modelValue: number; min?: number; max?: number; step?: number; label: string; fractional?: boolean }>(), { min: 0, max: 999, step: 1 })
const emit = defineEmits<{ 'update:modelValue': [number] }>()

function set(v: number) {
  const clean = Math.min(props.max, Math.max(props.min, props.fractional ? Math.round(v * 1000) / 1000 : Math.round(v)))
  emit('update:modelValue', clean)
}
</script>

<template>
  <div class="n-qty" role="group" :aria-label="label">
    <button type="button" class="n-qty__b" :aria-label="t('Decrease')" :disabled="modelValue <= min" @click="set(modelValue - step)"><NIcon name="minus" :size="18" /></button>
    <input
      class="n-qty__v num"
      :value="fmt(modelValue)"
      :inputmode="fractional ? 'decimal' : 'numeric'"
      :aria-label="label"
      @change="set(Number(($event.target as HTMLInputElement).value.replace(',', '.')) || 0)"
    />
    <button type="button" class="n-qty__b" :aria-label="t('Increase')" :disabled="modelValue >= max" @click="set(modelValue + step)"><NIcon name="plus" :size="18" /></button>
  </div>
</template>

<style>
.n-qty { flex: none; display: inline-flex; align-items: stretch; border: 1px solid var(--border-strong); border-radius: var(--radius-md); overflow: hidden; background: var(--surface-card); }
.n-qty__b { flex: none; inline-size: var(--touch); min-block-size: var(--touch); display: grid; place-items: center; border: 0; background: transparent; cursor: pointer; color: var(--text-strong); }
.n-qty__b:hover:not(:disabled) { background: var(--surface-sunken); }
.n-qty__b:disabled { opacity: 0.4; }
.n-qty__v { inline-size: 3.5em; text-align: center; border: 0; border-inline: 1px solid var(--border-subtle); background: transparent; font-weight: 600; }
</style>
