<script setup lang="ts">
// One component for the non-happy states every screen needs: loading, empty, denied, offline, error.
import NButton from './NButton.vue'
import NIcon from './NIcon.vue'
import { t } from '../lib/i18n'

defineProps<{ kind: 'loading' | 'empty' | 'denied' | 'offline' | 'error' | 'stale'; title: string; detail?: string; icon?: string; retry?: () => void }>()
const ICON = { loading: 'sync', empty: 'inbox', denied: 'lock', offline: 'offline', error: 'warning', stale: 'history' }
</script>

<template>
  <div :class="['n-state', `n-state--${kind}`]" :role="kind === 'error' || kind === 'denied' ? 'alert' : 'status'" :aria-busy="kind === 'loading' || undefined">
    <span v-if="kind === 'loading'" class="n-state__pulse" aria-hidden="true" />
    <NIcon v-else :name="icon ?? ICON[kind]" :size="32" />
    <p class="n-state__title">{{ title }}</p>
    <p v-if="detail" class="n-state__detail">{{ detail }}</p>
    <div class="n-state__actions"><slot /><NButton v-if="retry" icon="sync" @click="retry">{{ t('Try again') }}</NButton></div>
  </div>
</template>

<style>
.n-state { display: grid; justify-items: center; text-align: center; gap: var(--space-2); padding: var(--space-7) var(--space-5); color: var(--text-muted); }
.n-state__title { color: var(--text-strong); font-weight: 600; font-size: var(--text-lg); }
.n-state__detail { max-inline-size: 42ch; }
.n-state__actions { display: flex; gap: var(--space-2); margin-block-start: var(--space-3); flex-wrap: wrap; justify-content: center; }
.n-state--error .n-icon, .n-state--denied .n-icon { color: var(--danger-fg); }
.n-state--offline .n-icon, .n-state--stale .n-icon { color: var(--warn-fg); }
.n-state__pulse { inline-size: 40px; block-size: 40px; border-radius: 50%; background: var(--brand-fill); animation: n-pulse 1.1s var(--ease-standard) infinite; }
@keyframes n-pulse { 50% { transform: scale(0.7); opacity: 0.5; } }
@media (prefers-reduced-motion: reduce) { .n-state__pulse { animation: none; } }
</style>
