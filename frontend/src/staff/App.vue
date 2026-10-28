<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import NConnection from '@shared/components/NConnection.vue'
import NShell from '@shared/components/NShell.vue'
import NState from '@shared/components/NState.vue'
import NInstall from '@shared/components/NInstall.vue'
import NToasts from '@shared/components/NToasts.vue'
import { call } from '@shared/lib/api'
import { t } from '@shared/lib/i18n'
import { purgeLocal } from '@shared/lib/pwa'
import { connect, subscribeDoc } from '@shared/lib/realtime'
import { cycleTheme, toggleLanguage } from '@shared/app/surface'
import RegisterGate from '@shared/till/RegisterGate.vue'
import { useTill } from './state'

const props = defineProps<{ embedded?: boolean; root: HTMLElement }>()
const till = useTill()
const route = useRoute()
const bootError = ref('')
provide('embedded', props.embedded ?? false)

const roles = computed(() => till.boot.value?.roles ?? {})
const nav = computed(() => {
  const r = roles.value
  const items = []
  if (r.waiter || r.cashier || r.supervisor || r.manager) items.push({ to: '/floor', label: t('Floor'), icon: 'table' })
  if (r.kitchen || r.supervisor || r.manager) items.push({ to: '/kitchen', label: t('Kitchen'), icon: 'chef' })
  if (r.cashier || r.supervisor || r.manager) items.push({ to: '/counter', label: t('Counter'), icon: 'register' })
  if (r.waiter || r.cashier || r.supervisor || r.manager) items.push({ to: '/bookings', label: t('Bookings'), icon: 'calendar' })
  if (r.cashier || r.supervisor || r.manager) items.push({ to: '/shift', label: t('Shift'), icon: 'cash' })
  return items
})
const needsShift = computed(() => Boolean(route.meta.shift))

async function start() {
  bootError.value = ''
  try {
    await till.loadBoot()
  } catch (e) {
    bootError.value = (e as Error).message
  }
}

let unsub: (() => void) | null = null
watch(till.registerName, (name) => {
  unsub?.()
  if (name) unsub = subscribeDoc('Nest Restaurant Register', name)
})

onMounted(async () => {
  const boot = window.nest_boot as { site_name?: string; socketio_port?: number } | undefined
  await connect(boot?.site_name ?? location.hostname, boot?.socketio_port)
  await start()
})

async function logout() {
  if (till.pendingCount.value) {
    alert(t('{0} sale(s) have not synced yet. Stay signed in until they do, or export them from Sync.', till.pendingCount.value))
    return
  }
  await call('logout', {}, { method: 'POST' }).catch(() => undefined)
  await purgeLocal('nest_restaurant')
  await purgeLocal('nestrest-staff-')
  location.href = '/nest-restaurant/'
}
</script>

<template>
  <NShell
    title="Nest Restaurant"
    logo="/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e"
    :nav="route.meta.bare ? [] : nav"
    :embedded="embedded"
    desk-url="/desk/nest-restaurant"
    :user="till.boot.value?.user"
    @lang="toggleLanguage('nest_restaurant', root)"
    @theme="cycleTheme('nest_restaurant', root)"
    @logout="logout"
  >
    <template #status>
      <span v-if="till.registerName.value" class="app__reg">{{ till.registerName.value }}</span>
      <NConnection :online="till.online.value" :pending="till.pendingCount.value" :review="till.reviewCount.value" :syncing="till.syncing.value" :busy="till.cart.lines.length > 0" @open="$router.push('/sync')" />
    </template>
    <nav v-if="embedded" class="app__tabs" :aria-label="t('Restaurant sections')">
      <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="app__tab">{{ n.label }}</RouterLink>
    </nav>
    <NState v-if="bootError" kind="error" :title="t('The restaurant app could not start')" :detail="bootError" :retry="start" />
    <RegisterGate v-else-if="!till.registerName.value || (needsShift && !till.sessionOpen.value)" :till="till" />
    <RouterView v-else />
  </NShell>
  <NToasts />
  <NInstall v-if="!embedded" app="nest_restaurant" name="Nest Restaurant" logo="/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e" />
</template>

<style>
#app, .nest-desk-host > div { block-size: 100%; }
.app__reg { font-weight: 600; font-size: var(--text-sm); color: var(--text-muted); white-space: nowrap; }
@media (max-width: 480px) { .app__reg { display: none; } }
.app__tabs { display: flex; gap: var(--space-1); padding: 0 var(--space-4) var(--space-2); border-block-end: 1px solid var(--border-subtle); overflow-x: auto; }
.app__tab { min-block-size: 40px; display: inline-flex; align-items: center; padding-inline: var(--space-3); border-radius: var(--radius-md); color: var(--text-body); text-decoration: none; font-weight: 500; white-space: nowrap; }
.app__tab.router-link-active { background: var(--brand-fill); color: var(--brand-on-fill); }
</style>
