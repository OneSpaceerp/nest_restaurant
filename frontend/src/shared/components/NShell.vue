<script setup lang="ts">
// App frame: brand, primary navigation (top on wide screens, bottom bar on phones), utilities.
// Inside Desk the native Dock + Sidebar already exist, so `embedded` hides our navigation chrome.
import { RouterLink } from 'vue-router'
import NIcon from './NIcon.vue'
import { dir, t } from '../lib/i18n'

export interface NavItem { to: string; label: string; icon: string; badge?: number }
defineProps<{ title: string; logo: string; nav: NavItem[]; embedded?: boolean; deskUrl?: string; user?: string }>()
const emit = defineEmits<{ lang: []; theme: []; logout: [] }>()
</script>

<template>
  <div class="n-shell" :dir="dir()">
    <header v-if="!embedded" class="n-shell__top">
      <img :src="logo" alt="" class="n-shell__logo" width="32" height="32" />
      <span class="n-shell__title">{{ title }}</span>
      <nav class="n-shell__nav n-shell__nav--top" :aria-label="title">
        <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="n-shell__link">
          <NIcon :name="n.icon" :size="18" />{{ n.label }}<span v-if="n.badge" class="n-shell__badge num">{{ n.badge }}</span>
        </RouterLink>
      </nav>
      <div class="spacer" />
      <slot name="status" />
      <button type="button" class="n-shell__util" :aria-label="t('Language')" @click="emit('lang')"><NIcon name="globe" /></button>
      <button type="button" class="n-shell__util" :aria-label="t('Theme')" @click="emit('theme')"><NIcon name="moon" /></button>
      <a v-if="deskUrl" :href="deskUrl" class="n-shell__util n-shell__desk">{{ t('Back to Desk') }}</a>
      <button v-if="user" type="button" class="n-shell__util" :aria-label="t('Sign out')" @click="emit('logout')"><NIcon name="logout" /></button>
    </header>
    <div v-else class="n-shell__embedded-status"><slot name="status" /></div>
    <main class="n-shell__main"><slot /></main>
    <nav v-if="!embedded && nav.length > 1" class="n-shell__nav n-shell__nav--bottom" :aria-label="title">
      <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="n-shell__tab">
        <NIcon :name="n.icon" :size="22" />
        <span>{{ n.label }}</span>
        <span v-if="n.badge" class="n-shell__badge num">{{ n.badge }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style>
.n-shell { display: flex; flex-direction: column; block-size: 100%; min-block-size: 0; }
.n-shell__top { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-4); background: var(--surface-card); border-block-end: 1px solid var(--border-subtle); min-block-size: 56px; }
.n-shell__logo { border-radius: 8px; }
.n-shell__title { font-weight: 600; color: var(--text-strong); white-space: nowrap; }
.n-shell__nav--top { display: flex; gap: var(--space-1); margin-inline-start: var(--space-4); }
.n-shell__link { display: inline-flex; align-items: center; gap: 6px; min-block-size: 40px; padding-inline: var(--space-3); border-radius: var(--radius-md); color: var(--text-body); text-decoration: none; font-weight: 500; position: relative; }
.n-shell__link:hover { background: var(--surface-sunken); }
.n-shell__link.router-link-active { background: var(--brand-fill); color: var(--brand-on-fill); }
.n-shell__util { display: grid; place-items: center; min-inline-size: var(--touch); min-block-size: var(--touch); border: 0; background: transparent; border-radius: var(--radius-md); color: var(--text-body); cursor: pointer; text-decoration: none; }
.n-shell__util:hover { background: var(--surface-sunken); }
.n-shell__desk { padding-inline: var(--space-3); font-weight: 600; font-size: var(--text-sm); }
.n-shell__main { flex: 1; min-block-size: 0; display: flex; flex-direction: column; }
.n-shell__embedded-status { display: flex; justify-content: flex-end; padding: var(--space-2) var(--space-3); }
.n-shell__badge { min-inline-size: 20px; block-size: 20px; padding-inline: 6px; border-radius: var(--radius-pill); background: var(--danger-fg); color: #fff; font-size: var(--text-xs); display: inline-grid; place-items: center; }
.n-shell__nav--bottom { display: none; }
@media (max-width: 760px) {
  .n-shell__nav--top, .n-shell__desk, .n-shell__title { display: none; }
  .n-shell__nav--bottom { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; background: var(--surface-card); border-block-start: 1px solid var(--border-subtle); padding-block-end: var(--safe-bottom); }
  .n-shell__tab { display: grid; justify-items: center; gap: 2px; padding-block: var(--space-2); min-block-size: 56px; color: var(--text-muted); text-decoration: none; font-size: var(--text-xs); font-weight: 600; position: relative; }
  .n-shell__tab.router-link-active { color: var(--text-strong); }
  .n-shell__tab.router-link-active .n-icon { background: var(--brand-fill); color: var(--brand-on-fill); border-radius: var(--radius-pill); padding: 2px 14px; box-sizing: content-box; }
  .n-shell__tab .n-shell__badge { position: absolute; inset-block-start: 4px; inset-inline-start: calc(50% + 12px); }
}
</style>
