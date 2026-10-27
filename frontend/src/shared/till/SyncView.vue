<script setup lang="ts">
// Everything this device holds that the server has not acknowledged, in plain words, with export.
import NButton from '../components/NButton.vue'
import NState from '../components/NState.vue'
import NStatus from '../components/NStatus.vue'
import { t, time } from '../lib/i18n'
import type { Till } from './till'

const props = defineProps<{ till: Till }>()
const tl = props.till
const TONE: Record<string, 'ok' | 'info' | 'warn' | 'danger' | 'neutral'> = {
  Queued: 'info', Sending: 'info', Ambiguous: 'warn', Acknowledged: 'ok', Rejected: 'danger', 'Needs Review': 'danger', Discarded: 'neutral',
}
const LABEL: Record<string, string> = {
  Queued: 'Waiting to send', Sending: 'Sending', Ambiguous: 'Checking with the server', Acknowledged: 'Posted', Rejected: 'Refused by the server', 'Needs Review': 'Waiting for a manager', Discarded: 'Discarded',
}

async function download() {
  const blob = await tl.exportPending()
  if (!blob) return
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `nest-unsynced-${new Date().toISOString().slice(0, 19)}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <div class="sync scroll">
    <header class="sync__head">
      <h1>{{ t('Sync') }}</h1>
      <div class="row">
        <NButton icon="sync" :busy="tl.syncing.value" :disabled="!tl.online.value" @click="tl.syncNow()">{{ t('Send now') }}</NButton>
        <NButton icon="receipt" :disabled="!tl.pendingCount.value && !tl.reviewCount.value" @click="download">{{ t('Export unsynced') }}</NButton>
      </div>
    </header>
    <NState v-if="!tl.outboxEntries.value.length" kind="empty" icon="check" :title="t('Nothing waiting on this device')" />
    <ul v-else class="sync__list" role="list">
      <li v-for="e in [...tl.outboxEntries.value].reverse()" :key="e.key" class="sync__row">
        <span class="code">{{ e.key.slice(0, 14) }}…</span>
        <span>{{ time(new Date(e.created)) }}</span>
        <NStatus :tone="TONE[e.status]" :label="t(LABEL[e.status])" />
        <span class="muted sync__err">{{ e.lastError }}</span>
      </li>
    </ul>
    <p class="muted">{{ t('Refused and review items stay here and on the server’s “Sales to review” list until a manager resolves them. Nothing is deleted automatically.') }}</p>
  </div>
</template>

<style>
.sync { flex: 1; padding: var(--space-5) var(--space-4); display: grid; gap: var(--space-4); align-content: start; max-inline-size: 960px; margin-inline: auto; inline-size: 100%; }
.sync__head { display: flex; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap; align-items: center; }
.sync__list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.sync__row { display: grid; grid-template-columns: auto auto auto 1fr; gap: var(--space-3); align-items: center; background: var(--surface-card); padding: var(--space-3); border-radius: var(--radius-md); }
.sync__err { overflow-wrap: anywhere; }
@media (max-width: 640px) { .sync__row { grid-template-columns: 1fr auto; } }
</style>
