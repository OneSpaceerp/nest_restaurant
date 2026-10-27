<script setup lang="ts">
// Always-visible connection + sync state, and the safe update prompt.
import { computed } from 'vue'
import NIcon from './NIcon.vue'
import { applyUpdate, updateReady } from '../lib/pwa'
import { t } from '../lib/i18n'

const props = defineProps<{ online: boolean; pending: number; review: number; syncing: boolean; busy?: boolean }>()
const emit = defineEmits<{ open: [] }>()
const tone = computed(() => (!props.online ? 'warn' : props.review ? 'danger' : props.pending ? 'info' : 'ok'))
const label = computed(() => {
  if (!props.online) return props.pending ? `${t('Offline')} · ${t('{0} waiting to sync', props.pending)}` : t('Offline')
  if (props.review) return t('{0} need review', props.review)
  if (props.syncing || props.pending) return t('Syncing {0}', props.pending)
  return t('Online')
})
</script>

<template>
  <div class="n-conn">
    <button type="button" :class="['n-conn__pill', `n-conn__pill--${tone}`]" :aria-label="label" @click="emit('open')">
      <NIcon :name="online ? (pending ? 'sync' : 'check') : 'offline'" :size="16" />
      <span>{{ label }}</span>
    </button>
    <div v-if="updateReady" class="n-conn__update" role="status">
      <span>{{ t('A new version is ready') }}</span>
      <button type="button" class="n-conn__go" :disabled="busy" :title="busy ? t('Update after this sale') : ''" @click="applyUpdate()">
        {{ busy ? t('Update after this sale') : t('Update now') }}
      </button>
    </div>
  </div>
</template>

<style>
.n-conn { display: flex; align-items: center; gap: var(--space-2); flex: none; }
.n-conn__pill { display: inline-flex; align-items: center; gap: 6px; min-block-size: var(--touch); padding-inline: var(--space-3); border-radius: var(--radius-pill); border: 0; font-size: var(--text-sm); font-weight: 600; cursor: pointer; white-space: nowrap; }
.n-conn__pill--ok { background: var(--ok-bg); color: var(--ok-fg); }
.n-conn__pill--info { background: var(--info-bg); color: var(--info-fg); }
.n-conn__pill--warn { background: var(--warn-bg); color: var(--warn-fg); }
.n-conn__pill--danger { background: var(--danger-bg); color: var(--danger-fg); }
.n-conn__update { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-sm); }
.n-conn__go { border: 0; background: var(--brand-fill); color: var(--brand-on-fill); border-radius: var(--radius-pill); min-block-size: var(--touch); padding-inline: var(--space-3); font-weight: 600; cursor: pointer; }
.n-conn__go:disabled { background: var(--surface-sunken); color: var(--text-muted); cursor: default; }
@media (max-width: 520px) { .n-conn__update span { display: none; } }
</style>
