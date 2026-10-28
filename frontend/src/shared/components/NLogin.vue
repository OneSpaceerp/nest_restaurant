<script setup lang="ts">
// Staff sign-in for the PWAs. Brand panel (the app's tile colour) beside the form on wide screens; on
// phones the panel becomes a header band and the form rises over it as a sheet. Authentication is
// Frappe's own (/api/method/login): lockouts, rate limits and two-factor codes are honoured as-is.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import NButton from './NButton.vue'
import NIcon from './NIcon.vue'
import { signIn, SignInError } from '../lib/auth'
import { lang, t } from '../lib/i18n'
import { toggleLanguage } from '../app/surface'

const props = defineProps<{
  app: string
  name: string
  tagline: string
  logo: string
  root: HTMLElement
  /** brand panel colour; text colour follows its lightness */
  brand: string
}>()

const userKey = computed(() => `${props.app}:last-user`)
const usr = ref('')
const pwd = ref('')
const otp = ref('')
const showPwd = ref(false)
const capsLock = ref(false)
const busy = ref(false)
const error = ref('')
const step = ref<'password' | 'otp'>('password')
const otpPrompt = ref('')
const tmpId = ref('')
const online = ref(navigator.onLine)
const site = location.hostname
const usrInput = ref<HTMLInputElement | null>(null)
const pwdInput = ref<HTMLInputElement | null>(null)
const otpInput = ref<HTMLInputElement | null>(null)
const ids = { usr: useId(), pwd: useId(), otp: useId(), caps: useId() }

const darkBrand = computed(() => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(props.brand.slice(i, i + 2), 16))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 140
})

const setOnline = () => (online.value = navigator.onLine)
onMounted(() => {
  try { usr.value = localStorage.getItem(userKey.value) ?? '' } catch { /* private mode */ }
  void nextTick(() => (usr.value ? pwdInput.value : usrInput.value)?.focus())
  window.addEventListener('online', setOnline)
  window.addEventListener('offline', setOnline)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', setOnline)
  window.removeEventListener('offline', setOnline)
})

function onKey(e: KeyboardEvent) {
  capsLock.value = e.getModifierState?.('CapsLock') ?? false
}

async function submit() {
  if (busy.value) return
  error.value = ''
  if (step.value === 'password' && (!usr.value.trim() || !pwd.value)) {
    error.value = t('Enter your email or username and your password.')
    return
  }
  busy.value = true
  try {
    const res = step.value === 'otp'
      ? await signIn({ otp: otp.value.trim(), tmpId: tmpId.value })
      : await signIn({ usr: usr.value.trim(), pwd: pwd.value })
    if (res.status === 'otp') {
      step.value = 'otp'
      tmpId.value = res.tmpId
      otpPrompt.value = res.prompt
      busy.value = false
      await nextTick()
      otpInput.value?.focus()
      return
    }
    try { localStorage.setItem(userKey.value, usr.value.trim()) } catch { /* private mode */ }
    // the shell is rendered per session (CSRF token, user, translations), so load it again
    location.reload()
  } catch (e) {
    busy.value = false
    error.value = e instanceof SignInError ? t(e.message) : t('The server could not sign you in. Try again.')
    if (step.value === 'password') {
      pwd.value = ''
      void nextTick(() => pwdInput.value?.focus())
    } else {
      otp.value = ''
      void nextTick(() => otpInput.value?.focus())
    }
  }
}

function back() {
  step.value = 'password'
  otp.value = ''
  error.value = ''
  void nextTick(() => pwdInput.value?.focus())
}
</script>

<template>
  <main :class="['n-login', { 'n-login--dark': darkBrand }]" :style="{ '--login-brand': brand }">
    <section class="n-login__brand" aria-hidden="true">
      <div class="n-login__pattern" />
      <div class="n-login__brand-inner">
        <img :src="logo" alt="" class="n-login__logo" width="96" height="96" />
        <p class="n-login__app">{{ name }}</p>
        <p class="n-login__tagline">{{ t(tagline) }}</p>
      </div>
      <p class="n-login__site"><NIcon name="globe" :size="14" /> {{ site }}</p>
    </section>

    <section class="n-login__panel">
      <div class="n-login__tools">
        <button type="button" class="n-login__lang" :aria-label="t('Language')" @click="toggleLanguage(app, root)">
          <NIcon name="globe" :size="18" /><span>{{ lang() === 'ar' ? 'English' : 'العربية' }}</span>
        </button>
      </div>

      <form class="n-login__form" novalidate @submit.prevent="submit">
        <header class="n-login__head">
          <h1>{{ step === 'otp' ? t('Verification code') : t('Sign in') }}</h1>
          <p class="n-login__sub">
            {{ step === 'otp' ? (otpPrompt || t('Enter the code from your authenticator app.')) : t('Use your ERPNext account to open {0}.', name) }}
          </p>
        </header>

        <p v-if="!online" class="n-login__note n-login__note--warn" role="status"><NIcon name="offline" :size="18" />{{ t('You are offline. Connect to sign in.') }}</p>
        <p v-if="error" class="n-login__note n-login__note--danger" role="alert"><NIcon name="warning" :size="18" />{{ error }}</p>

        <template v-if="step === 'password'">
          <div class="n-login__field">
            <label :for="ids.usr">{{ t('Email or username') }}</label>
            <input :id="ids.usr" ref="usrInput" v-model="usr" class="n-login__input" type="text" name="username" autocomplete="username" inputmode="email" autocapitalize="none" spellcheck="false" dir="ltr" required />
          </div>
          <div class="n-login__field">
            <label :for="ids.pwd">{{ t('Password') }}</label>
            <span class="n-login__pwd" dir="ltr">
              <input :id="ids.pwd" ref="pwdInput" v-model="pwd" class="n-login__input" :aria-describedby="capsLock ? ids.caps : undefined" :type="showPwd ? 'text' : 'password'" name="password" autocomplete="current-password" dir="ltr" required @keydown="onKey" @keyup="onKey" />
              <button type="button" class="n-login__reveal" :aria-pressed="showPwd" :aria-label="showPwd ? t('Hide password') : t('Show password')" @click="showPwd = !showPwd">{{ showPwd ? t('Hide') : t('Show') }}</button>
            </span>
            <span v-if="capsLock" :id="ids.caps" class="n-login__caps" role="status">{{ t('Caps Lock is on') }}</span>
          </div>
        </template>
        <div v-else class="n-login__field">
          <label :for="ids.otp">{{ t('Verification code') }}</label>
          <input :id="ids.otp" ref="otpInput" v-model="otp" class="n-login__input n-login__otp" type="text" name="otp" autocomplete="one-time-code" inputmode="numeric" maxlength="10" dir="ltr" required />
        </div>

        <NButton type="submit" variant="primary" size="lg" block :busy="busy" :disabled="!online" :icon="step === 'otp' ? 'check' : 'lock'">
          {{ busy ? t('Signing in') + '…' : step === 'otp' ? t('Verify') : t('Sign in') }}
        </NButton>

        <p class="n-login__links">
          <button v-if="step === 'otp'" type="button" class="n-login__link" @click="back">{{ t('Back') }}</button>
          <a v-else class="n-login__link" href="/login#forgot">{{ t('Forgot password?') }}</a>
        </p>
      </form>

      <p class="n-login__by">nsdLabs</p>
    </section>
  </main>
</template>

<style>
.n-login { min-block-size: 100dvh; display: grid; grid-template-columns: minmax(320px, 44%) 1fr; background: var(--surface-page); color: var(--text-body); }
.n-login__brand { position: relative; overflow: hidden; background: var(--login-brand); color: var(--nest-ink-900); display: grid; place-items: center; padding: var(--space-7); }
.n-login--dark .n-login__brand { color: #fff; }
/* receipt-tape dots: the till's own motif, quiet enough to sit behind the mark */
.n-login__pattern { position: absolute; inset: 0; opacity: 0.12; background-image: radial-gradient(currentColor 1.2px, transparent 1.4px); background-size: 18px 18px; mask-image: radial-gradient(circle at 50% 45%, transparent 0 26%, #000 70%); }
.n-login__brand-inner { position: relative; display: grid; justify-items: center; text-align: center; gap: var(--space-3); animation: n-login-rise 0.6s cubic-bezier(0.2, 0.9, 0.25, 1.2) both; }
.n-login__logo { inline-size: 96px; block-size: 96px; border-radius: 24px; box-shadow: 0 0 0 1px rgb(0 0 0 / 0.08), 0 18px 40px -14px rgb(0 0 0 / 0.4), 0 2px 6px rgb(0 0 0 / 0.12); }
.n-login__app { margin-block-start: var(--space-2); font-size: var(--text-2xl); font-weight: 700; letter-spacing: -0.01em; }
.n-login__tagline { font-size: var(--text-md); opacity: 0.8; max-inline-size: 28ch; }
.n-login__site { position: absolute; inset-block-end: var(--space-5); display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-sm); opacity: 0.75; }

.n-login__panel { position: relative; display: grid; place-items: center; padding: var(--space-7) var(--space-5); }
.n-login__tools { position: absolute; inset-block-start: var(--space-4); inset-inline-end: var(--space-4); }
.n-login__lang { display: inline-flex; align-items: center; gap: 6px; min-block-size: var(--touch); padding-inline: var(--space-3); border: 1px solid var(--border-subtle); border-radius: var(--radius-pill); background: var(--surface-card); color: var(--text-body); cursor: pointer; font: inherit; font-size: var(--text-sm); }
.n-login__form { inline-size: min(400px, 100%); display: grid; gap: var(--space-4); animation: n-login-up 0.5s 0.1s ease-out both; }
.n-login__head h1 { font-size: var(--text-2xl); color: var(--text-strong); line-height: var(--leading-tight); }
.n-login__sub { margin-block-start: var(--space-2); color: var(--text-muted); }
.n-login__field { display: grid; gap: 6px; font-size: var(--text-sm); font-weight: 600; color: var(--text-strong); }
.n-login__input { inline-size: 100%; min-block-size: var(--touch-lg); padding-inline: var(--space-4); border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-card); color: var(--text-strong); font: inherit; font-size: var(--text-md); font-weight: 400; }
.n-login__input:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 1px; border-color: var(--text-strong); }
.n-login__pwd { position: relative; display: block; }
.n-login__pwd .n-login__input { padding-inline-end: 84px; }
.n-login__reveal { position: absolute; inset-block: 6px; inset-inline-end: 6px; min-inline-size: 64px; border: 0; border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--text-strong); font: inherit; font-size: var(--text-sm); font-weight: 600; cursor: pointer; }
.n-login__caps { color: var(--warn-fg); font-weight: 600; }
.n-login__otp { letter-spacing: 0.3em; font-size: var(--text-xl); text-align: center; }
.n-login__note { display: flex; gap: var(--space-2); align-items: flex-start; padding: var(--space-3); border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: 600; }
.n-login__note--warn { background: var(--warn-bg); color: var(--warn-fg); }
.n-login__note--danger { background: var(--danger-bg); color: var(--danger-fg); }
.n-login__links { text-align: center; }
.n-login__link { background: none; border: 0; padding: var(--space-2); font: inherit; font-size: var(--text-sm); color: var(--text-body); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; min-block-size: var(--touch); }
.n-login__by { position: absolute; inset-block-end: var(--space-4); font-size: var(--text-xs); letter-spacing: 0.06em; color: var(--text-muted); }

@keyframes n-login-rise { from { opacity: 0; transform: translateY(14px) scale(0.92); } }
@keyframes n-login-up { from { opacity: 0; transform: translateY(10px); } }
@media (prefers-reduced-motion: reduce) { .n-login__brand-inner, .n-login__form { animation: none; } }

/* Phones and portrait tablets: brand band on top, form as a sheet rising over it */
@media (max-width: 860px) {
  .n-login { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
  .n-login__brand { padding: calc(var(--safe-top) + var(--space-7)) var(--space-5) calc(var(--space-7) + 24px); }
  .n-login__logo { inline-size: 72px; block-size: 72px; border-radius: 18px; }
  .n-login__app { font-size: var(--text-xl); margin-block-start: 0; }
  .n-login__site { display: none; }
  .n-login__panel { place-items: start center; margin-block-start: -24px; border-start-start-radius: 24px; border-start-end-radius: 24px; background: var(--surface-page); padding: var(--space-6) var(--space-5) calc(var(--safe-bottom) + var(--space-7)); }
  .n-login__tools { position: fixed; inset-block-start: calc(var(--safe-top) + var(--space-3)); inset-inline-end: var(--space-3); z-index: 1; }
  .n-login__lang { background: rgb(255 255 255 / 0.85); border-color: transparent; color: var(--nest-ink-900); }
}
</style>
