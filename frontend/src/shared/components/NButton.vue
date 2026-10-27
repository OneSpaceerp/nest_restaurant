<script setup lang="ts">
import NIcon from './NIcon.vue'

withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'brand' | 'danger' | 'ghost'
    size?: 'sm' | 'md' | 'lg'
    icon?: string
    busy?: boolean
    disabled?: boolean
    block?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'secondary', size: 'md', type: 'button' },
)
</script>

<template>
  <button
    :type="type"
    :class="['n-btn', `n-btn--${variant}`, `n-btn--${size}`, { 'n-btn--block': block }]"
    :disabled="disabled || busy"
    :aria-busy="busy || undefined"
  >
    <span v-if="busy" class="n-btn__spin" aria-hidden="true" />
    <NIcon v-else-if="icon" :name="icon" :size="size === 'lg' ? 22 : 18" />
    <span class="n-btn__label"><slot /></span>
  </button>
</template>

<style>
.n-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-block-size: var(--touch);
  padding-inline: var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  font-weight: 600;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-standard), transform var(--dur-fast) var(--ease-standard);
  user-select: none;
  touch-action: manipulation;
}
.n-btn:active:not(:disabled) { transform: translateY(1px); }
.n-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.n-btn--sm { min-block-size: 36px; padding-inline: var(--space-3); font-size: var(--text-sm); }
.n-btn--lg { min-block-size: var(--touch-lg); padding-inline: var(--space-5); font-size: var(--text-lg); border-radius: var(--radius-lg); }
.n-btn--block { inline-size: 100%; }
.n-btn--primary { background: var(--action-primary-bg); color: var(--action-primary-fg); }
.n-btn--primary:hover:not(:disabled) { background: var(--action-primary-hover); }
.n-btn--brand { background: var(--brand-fill); color: var(--brand-on-fill); }
.n-btn--brand:hover:not(:disabled) { background: var(--brand-fill-strong); }
.n-btn--secondary { background: var(--surface-card); color: var(--text-strong); border-color: var(--border-strong); }
.n-btn--secondary:hover:not(:disabled) { background: var(--surface-sunken); }
.n-btn--danger { background: var(--danger-bg); color: var(--danger-fg); border-color: color-mix(in srgb, var(--danger-fg) 30%, transparent); }
.n-btn--ghost { background: transparent; color: var(--text-strong); }
.n-btn--ghost:hover:not(:disabled) { background: var(--surface-sunken); }
.n-btn__label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.n-btn__spin {
  inline-size: 18px; block-size: 18px; border-radius: 50%;
  border: 2px solid currentColor; border-inline-end-color: transparent;
  animation: n-spin 700ms linear infinite;
}
@keyframes n-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .n-btn__spin { animation-duration: 2s; } }
</style>
