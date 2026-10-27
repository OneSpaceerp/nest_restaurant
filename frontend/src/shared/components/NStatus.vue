<script setup lang="ts">
// Status is always a word plus a shape — never colour alone.
defineProps<{ tone: 'ok' | 'danger' | 'warn' | 'info' | 'neutral' | 'brand'; label: string }>()
</script>

<template>
  <span :class="['n-status', `n-status--${tone}`]"><span class="n-status__dot" aria-hidden="true" />{{ label }}</span>
</template>

<style>
.n-status { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: var(--radius-pill); font-size: var(--text-sm); font-weight: 600; white-space: nowrap; background: var(--surface-sunken); color: var(--text-body); }
.n-status__dot { inline-size: 8px; block-size: 8px; border-radius: 50%; background: currentColor; }
.n-status--ok { background: var(--ok-bg); color: var(--ok-fg); }
.n-status--danger { background: var(--danger-bg); color: var(--danger-fg); }
.n-status--danger .n-status__dot { border-radius: 1px; transform: rotate(45deg); }
.n-status--warn { background: var(--warn-bg); color: var(--warn-fg); }
.n-status--warn .n-status__dot { border-radius: 0; clip-path: polygon(50% 0, 100% 100%, 0 100%); }
.n-status--info { background: var(--info-bg); color: var(--info-fg); }
.n-status--brand { background: var(--brand-fill); color: var(--brand-on-fill); }
</style>
