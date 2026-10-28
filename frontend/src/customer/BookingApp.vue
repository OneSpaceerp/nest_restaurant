<script setup lang="ts">
// Public booking page: /nest-restaurant/customer/book?r=<register>. Capacity is checked on the server
// under a lock; this page only shows what is free and sends one idempotent request.
import { onMounted, reactive, ref, watch } from 'vue'
import NButton from '@shared/components/NButton.vue'
import NQty from '@shared/components/NQty.vue'
import NState from '@shared/components/NState.vue'
import NInstall from '@shared/components/NInstall.vue'
import NToasts from '@shared/components/NToasts.vue'
import { call, newKey } from '@shared/lib/api'
import { t } from '@shared/lib/i18n'

const API = (m: string) => `nest_restaurant.api.guest.${m}`
const register = new URLSearchParams(location.search).get('r') ?? ''
const day = ref(new Date(Date.now() + 86400000).toISOString().slice(0, 10))
const slots = ref<{ time: string; available: boolean; seats_left: number | null }[] | null>(null)
const maxParty = ref(8)
const form = reactive({ party: 2, time: '', name: '', phone: '', email: '', notes: '', website: '' })
const key = ref(newKey('book-'))
const busy = ref(false)
const error = ref('')
const done = ref<{ reservation: string; status: string } | null>(null)

async function load() {
  slots.value = null
  error.value = ''
  try {
    const res = await call<{ slots: typeof slots.value; max_party: number }>(API('availability'), { register_name: register, day: day.value }, { method: 'GET' })
    slots.value = res.slots
    maxParty.value = res.max_party
  } catch (e) {
    error.value = (e as Error).message
  }
}
onMounted(load)
watch(day, () => { form.time = ''; void load() })

async function book() {
  busy.value = true
  error.value = ''
  try {
    done.value = await call(API('book'), {
      register_name: register, guest_name: form.name, phone: form.phone, party: form.party, start: `${day.value} ${form.time}:00`,
      request_key: key.value, notes: form.notes, email: form.email, website: form.website,
    })
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="book scroll">
    <section class="book__card">
      <img src="/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e" alt="" width="48" height="48" />
      <template v-if="done">
        <h1>{{ t('Request received') }}</h1>
        <p>{{ t('We’ll confirm your table by phone. Your reference is {0}.', done.reservation) }}</p>
      </template>
      <form v-else class="stack" @submit.prevent="book">
        <h1>{{ t('Book a table') }}</h1>
        <label class="stack"><span>{{ t('Date') }}</span><input v-model="day" type="date" class="book__in" required /></label>
        <label class="stack"><span>{{ t('Guests') }}</span><NQty v-model="form.party" :min="1" :max="maxParty" :label="t('Guests')" /></label>
        <fieldset class="book__slots">
          <legend>{{ t('Time') }}</legend>
          <NState v-if="error && !slots" kind="error" :title="error" :retry="load" />
          <NState v-else-if="!slots" kind="loading" :title="t('Checking tables')" />
          <p v-else-if="!slots.length" class="muted">{{ t('No online tables that day. Call us and we’ll try to fit you in.') }}</p>
          <button v-for="s in slots ?? []" :key="s.time" type="button" class="book__slot num" :aria-pressed="form.time === s.time" :disabled="!s.available" @click="form.time = s.time">
            {{ s.time }}<span v-if="s.seats_left" class="book__left">{{ t('{0} left', s.seats_left) }}</span>
          </button>
        </fieldset>
        <label class="stack"><span>{{ t('Name') }}</span><input v-model="form.name" class="book__in" required maxlength="80" autocomplete="name" /></label>
        <label class="stack"><span>{{ t('Phone') }}</span><input v-model="form.phone" class="book__in" required inputmode="tel" autocomplete="tel" maxlength="20" /></label>
        <label class="stack"><span>{{ t('Email (optional)') }}</span><input v-model="form.email" class="book__in" type="email" autocomplete="email" /></label>
        <label class="stack"><span>{{ t('Anything we should know?') }}</span><input v-model="form.notes" class="book__in" maxlength="140" /></label>
        <input v-model="form.website" class="book__hp" tabindex="-1" autocomplete="off" aria-hidden="true" />
        <p v-if="error && slots" class="book__err" role="alert">{{ error }}</p>
        <NButton type="submit" variant="primary" size="lg" :busy="busy" :disabled="!form.time || !form.name || form.phone.length < 7">{{ t('Request this table') }}</NButton>
      </form>
    </section>
    <NToasts />
    <NInstall app="nest_rest_guest" name="Nest Restaurant" logo="/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e" />
  </div>
</template>

<style>
.book { block-size: 100%; padding: var(--space-5) var(--space-4); display: grid; place-items: start center; }
.book__card { inline-size: min(560px, 100%); background: var(--surface-card); border-radius: var(--radius-lg); padding: var(--space-6); box-shadow: var(--shadow-raised); display: grid; gap: var(--space-4); }
.book__in { min-block-size: var(--touch); border-radius: var(--radius-md); border: 1px solid var(--border-strong); padding-inline: var(--space-3); background: var(--surface-card); color: var(--text-strong); }
.book__slots { border: 0; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.book__slots legend { font-weight: 600; margin-block-end: var(--space-2); }
.book__slot { min-block-size: var(--touch); min-inline-size: 5.5rem; border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); font-weight: 600; cursor: pointer; display: grid; place-items: center; }
.book__slot[aria-pressed='true'] { background: var(--nest-ink-900); color: var(--nest-yellow-400); }
.book__slot:disabled { opacity: 0.4; text-decoration: line-through; }
.book__left { font-size: var(--text-xs); font-weight: 500; }
.book__hp { position: absolute; inset-inline-start: -10000px; }
.book__err { color: var(--danger-fg); font-weight: 600; }
@media (max-width: 520px) { .book__card { padding: var(--space-4); } }
</style>
