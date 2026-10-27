<script setup lang="ts">
import NIcon from './NIcon.vue'
import { dismiss, toasts } from './toast'
const ICON = { ok: 'check', danger: 'warning', warn: 'warning', info: 'bell' } as const
</script>

<template>
  <div class="n-toasts" role="region" aria-live="polite" aria-label="Notifications">
    <div v-for="tt in toasts" :key="tt.id" :class="['n-toast', `n-toast--${tt.tone}`]" :role="tt.tone === 'danger' ? 'alert' : 'status'">
      <NIcon :name="ICON[tt.tone]" />
      <span class="n-toast__text">{{ tt.text }}</span>
      <button v-if="tt.action" type="button" class="n-toast__btn" @click="tt.action.run(); dismiss(tt.id)">{{ tt.action.label }}</button>
      <button type="button" class="n-toast__btn n-toast__close" aria-label="Dismiss" @click="dismiss(tt.id)"><NIcon name="close" :size="16" /></button>
    </div>
  </div>
</template>

<style>
.n-toasts { position: fixed; inset-inline: 0; inset-block-end: calc(var(--space-5) + var(--safe-bottom)); display: grid; justify-items: center; gap: var(--space-2); pointer-events: none; z-index: 50; padding-inline: var(--space-4); }
.n-toast { pointer-events: auto; display: flex; align-items: center; gap: var(--space-3); max-inline-size: 560px; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--surface-inverse); color: var(--text-inverse); box-shadow: var(--shadow-overlay); animation: n-toast-in var(--dur-normal) var(--ease-enter); }
.n-toast--danger { background: var(--danger-bg); color: var(--danger-fg); border: 1px solid currentColor; }
.n-toast--warn { background: var(--warn-bg); color: var(--warn-fg); border: 1px solid currentColor; }
.n-toast__text { flex: 1; }
.n-toast__btn { background: transparent; border: 0; color: inherit; font-weight: 600; min-block-size: 36px; padding-inline: var(--space-2); cursor: pointer; border-radius: var(--radius-sm); }
.n-toast__close { opacity: 0.7; }
@keyframes n-toast-in { from { opacity: 0; transform: translateY(8px); } }
</style>
