<script setup lang="ts">
// "Install the app" popup for the standalone PWAs (never mounted in Desk).
// Android/Chromium: offered once the browser fires beforeinstallprompt, then the native prompt runs.
// iOS Safari has no install API, so it shows the Share → Add to Home Screen steps instead.
// "Not now" is remembered per app for a week; nothing shows once the app runs installed.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import NButton from './NButton.vue'
import NSheet from './NSheet.vue'
import { t } from '../lib/i18n'
import { installAvailable, isStandalone, promptInstall } from '../lib/pwa'

const props = defineProps<{ app: string; name: string; logo: string }>()

const SNOOZE_MS = 7 * 24 * 3600 * 1000
const DELAY_MS = 2500
const key = computed(() => `${props.app}:install-snoozed`)
const open = ref(false)
const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
let timer = 0

function snoozed() {
  try {
    return Date.now() - Number(localStorage.getItem(key.value) ?? 0) < SNOOZE_MS
  } catch {
    return false
  }
}
function offer() {
  clearTimeout(timer)
  if (isStandalone() || snoozed()) return
  timer = window.setTimeout(() => (open.value = true), DELAY_MS)
}
function later() {
  open.value = false
  try { localStorage.setItem(key.value, String(Date.now())) } catch { /* private mode */ }
}
async function install() {
  open.value = false
  await promptInstall()
}

onMounted(() => {
  if (installAvailable.value || ios) offer()
})
watch(installAvailable, (v) => {
  if (v) offer()
  else if (!ios) open.value = false
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <NSheet :open="open" :title="t('Install {0}', name)" @close="later">
    <div class="n-install">
      <img :src="logo" alt="" width="64" height="64" class="n-install__logo" />
      <div>
        <p class="n-install__lead">{{ t('Add {0} to your home screen for full-screen use, a faster start and work offline.', name) }}</p>
        <ol v-if="ios && !installAvailable" class="n-install__steps">
          <li>{{ t('Tap the Share button in the browser bar.') }}</li>
          <li>{{ t('Choose “Add to Home Screen”, then tap Add.') }}</li>
        </ol>
      </div>
    </div>
    <template #actions>
      <NButton variant="ghost" @click="later">{{ t('Not now') }}</NButton>
      <NButton v-if="installAvailable" variant="primary" icon="plus" @click="install">{{ t('Install') }}</NButton>
      <NButton v-else variant="primary" icon="check" @click="later">{{ t('Got it') }}</NButton>
    </template>
  </NSheet>
</template>

<style>
.n-install { display: flex; gap: var(--space-4); align-items: flex-start; }
.n-install__logo { border-radius: 14px; flex: none; }
.n-install__lead { color: var(--text-body); }
.n-install__steps { margin-block-start: var(--space-3); padding-inline-start: 1.2em; display: grid; gap: var(--space-2); color: var(--text-strong); font-weight: 600; }
</style>
