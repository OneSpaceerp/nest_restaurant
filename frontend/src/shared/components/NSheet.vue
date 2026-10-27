<script setup lang="ts">
// Modal built on <dialog>: native focus containment, Esc to close, inert background.
// Centred card on wide screens, bottom sheet on phones (thumb reach).
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import NIcon from './NIcon.vue'
import { t } from '../lib/i18n'

const props = defineProps<{ open: boolean; title: string; wide?: boolean; dismissible?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const el = ref<HTMLDialogElement | null>(null)

watch(
  () => props.open,
  async (open) => {
    await nextTick()
    if (!el.value) return
    if (open && !el.value.open) el.value.showModal()
    if (!open && el.value.open) el.value.close()
  },
  { immediate: true },
)

function onCancel(e: Event) {
  e.preventDefault()
  if (props.dismissible !== false) emit('close')
}
onBeforeUnmount(() => el.value?.open && el.value.close())
</script>

<template>
  <dialog ref="el" :class="['n-sheet', { 'n-sheet--wide': wide }]" :aria-label="title" @cancel="onCancel">
    <div v-if="open" class="n-sheet__inner">
      <header class="n-sheet__head">
        <h2>{{ title }}</h2>
        <button v-if="dismissible !== false" class="n-sheet__x" type="button" :aria-label="t('Cancel')" @click="emit('close')">
          <NIcon name="close" />
        </button>
      </header>
      <div class="n-sheet__body scroll"><slot /></div>
      <footer v-if="$slots.actions" class="n-sheet__actions"><slot name="actions" /></footer>
    </div>
  </dialog>
</template>

<style>
.n-sheet {
  border: 0;
  padding: 0;
  inline-size: min(520px, calc(100vw - 32px));
  max-block-size: min(86vh, 860px);
  border-radius: var(--radius-lg);
  background: var(--surface-card);
  color: var(--text-body);
  box-shadow: var(--shadow-overlay);
}
.n-sheet--wide { inline-size: min(880px, calc(100vw - 32px)); }
.n-sheet::backdrop { background: rgb(20 19 19 / 0.45); }
.n-sheet[open] { animation: n-sheet-in var(--dur-moderate) var(--ease-enter); }
.n-sheet__inner { display: flex; flex-direction: column; max-block-size: inherit; }
.n-sheet__head { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-4) var(--space-5); border-block-end: 1px solid var(--border-subtle); }
.n-sheet__head h2 { flex: 1; font-size: var(--text-lg); }
.n-sheet__x { display: grid; place-items: center; inline-size: var(--touch); block-size: var(--touch); border: 0; background: transparent; border-radius: var(--radius-md); cursor: pointer; color: var(--text-muted); }
.n-sheet__x:hover { background: var(--surface-sunken); }
.n-sheet__body { padding: var(--space-5); flex: 1; min-block-size: 0; }
.n-sheet__actions { display: flex; gap: var(--space-3); justify-content: flex-end; padding: var(--space-4) var(--space-5); border-block-start: 1px solid var(--border-subtle); flex-wrap: wrap; }
@keyframes n-sheet-in { from { opacity: 0; transform: translateY(12px); } }
@media (max-width: 640px) {
  .n-sheet { inline-size: 100vw; max-inline-size: 100vw; margin: auto 0 0; border-end-start-radius: 0; border-end-end-radius: 0; padding-block-end: var(--safe-bottom); }
  .n-sheet__actions > * { flex: 1; }
}
</style>
