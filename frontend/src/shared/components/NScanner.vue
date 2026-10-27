<script setup lang="ts">
// Camera scanning with honest fallbacks: insecure origin, unsupported browser and denied permission
// each explain themselves and leave the manual code field working.
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import NButton from './NButton.vue'
import NIcon from './NIcon.vue'
import { CameraScanner, type CameraState } from '../lib/camera'
import { normaliseScan } from '../lib/scan'
import { t } from '../lib/i18n'

const props = defineProps<{ continuous?: boolean; feedback?: { tone: 'ok' | 'danger'; text: string } | null }>()
const emit = defineEmits<{ code: [string]; close: [] }>()

const video = ref<HTMLVideoElement | null>(null)
const state = ref<CameraState>('idle')
const message = ref('')
const torchOn = ref(false)
const manual = ref('')
const scanner = shallowRef<CameraScanner | null>(null)
const torchAvailable = ref(false)

const MESSAGES: Partial<Record<CameraState, string>> = {
  insecure: 'The camera needs a secure (https) connection. Use the code field below.',
  unsupported: 'This browser cannot read barcodes with the camera. Use the code field or a scanner.',
  denied: 'Camera access was blocked. Allow it in the browser settings, or type the code.',
  error: 'The camera could not start. Type the code instead.',
}

onMounted(() => {
  scanner.value = new CameraScanner(
    video.value!,
    (c) => {
      emit('code', c)
      if (!props.continuous) scanner.value?.stop()
    },
    (s, m) => {
      state.value = s
      message.value = m ?? ''
      torchAvailable.value = Boolean(scanner.value?.torchAvailable)
    },
  )
  void scanner.value.start()
})
onBeforeUnmount(() => scanner.value?.stop())

function submitManual() {
  const c = normaliseScan(manual.value)
  if (c) emit('code', c)
  manual.value = ''
}
async function toggleTorch() {
  torchOn.value = !torchOn.value
  await scanner.value?.torch(torchOn.value)
}
</script>

<template>
  <section class="n-scan" :aria-label="t('Scan')">
    <div class="n-scan__view">
      <video ref="video" class="n-scan__video" muted playsinline aria-hidden="true" />
      <div v-if="state === 'running'" class="n-scan__frame" aria-hidden="true" />
      <p v-if="state === 'running'" class="n-scan__hint">{{ t('Point the camera at a barcode') }}</p>
      <p v-else-if="state === 'starting'" class="n-scan__hint">{{ t('Loading') }}…</p>
      <div v-else-if="MESSAGES[state]" class="n-scan__msg" role="alert">
        <NIcon name="camera" :size="28" />
        <p>{{ t(MESSAGES[state]!) }}</p>
      </div>
      <div v-if="feedback" :class="['n-scan__feedback', `n-scan__feedback--${feedback.tone}`]" role="status">{{ feedback.text }}</div>
      <div class="n-scan__tools">
        <button v-if="torchAvailable" type="button" class="n-scan__tool" :aria-pressed="torchOn" :aria-label="t('Torch')" @click="toggleTorch"><NIcon name="torch" /></button>
        <button v-if="state === 'running'" type="button" class="n-scan__tool" :aria-label="t('Switch camera')" @click="scanner?.switchCamera()"><NIcon name="sync" /></button>
        <button type="button" class="n-scan__tool" :aria-label="t('Done')" @click="emit('close')"><NIcon name="close" /></button>
      </div>
    </div>
    <form class="n-scan__manual" @submit.prevent="submitManual">
      <label class="sr-only" for="n-scan-manual">{{ t('Type the code instead') }}</label>
      <input id="n-scan-manual" v-model="manual" class="n-input code" :placeholder="t('Type the code instead')" autocomplete="off" inputmode="text" maxlength="128" />
      <NButton type="submit" variant="primary" icon="check">{{ t('Add to order') }}</NButton>
    </form>
  </section>
</template>

<style>
.n-scan { display: flex; flex-direction: column; gap: var(--space-3); }
.n-scan__view { position: relative; aspect-ratio: 3 / 4; max-block-size: 60vh; background: #000; border-radius: var(--radius-lg); overflow: hidden; display: grid; place-items: center; }
@media (min-width: 700px) { .n-scan__view { aspect-ratio: 16 / 10; } }
.n-scan__video { position: absolute; inset: 0; inline-size: 100%; block-size: 100%; object-fit: cover; }
.n-scan__frame { position: absolute; inset: 28% 14%; border: 3px solid var(--nest-yellow-400); border-radius: var(--radius-md); box-shadow: 0 0 0 999px rgb(0 0 0 / 0.35); }
.n-scan__hint { position: absolute; inset-block-start: var(--space-4); color: #fff; font-weight: 600; text-shadow: 0 1px 2px #000; }
.n-scan__msg { display: grid; justify-items: center; gap: var(--space-2); color: #fff; padding: var(--space-5); text-align: center; max-inline-size: 36ch; }
.n-scan__feedback { position: absolute; inset-block-end: 72px; padding: var(--space-2) var(--space-4); border-radius: var(--radius-pill); font-weight: 600; }
.n-scan__feedback--ok { background: var(--nest-yellow-400); color: var(--nest-ink-900); }
.n-scan__feedback--danger { background: var(--nest-red-700); color: #fff; }
.n-scan__tools { position: absolute; inset-block-end: var(--space-3); inset-inline: var(--space-3); display: flex; justify-content: flex-end; gap: var(--space-2); }
.n-scan__tool { inline-size: var(--touch-lg); block-size: var(--touch-lg); border-radius: 50%; border: 0; display: grid; place-items: center; background: rgb(255 255 255 / 0.9); color: var(--nest-ink-900); cursor: pointer; }
.n-scan__tool[aria-pressed='true'] { background: var(--nest-yellow-400); }
.n-scan__manual { display: flex; gap: var(--space-2); }
.n-scan__manual .n-input { flex: 1; min-inline-size: 0; }
.n-input { min-block-size: var(--touch); padding-inline: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); }
</style>
