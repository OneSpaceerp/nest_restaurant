<script setup lang="ts">
// Search + groups + product grid. A keyboard-wedge scan anywhere on the page lands here without
// stealing the search box from someone who is typing.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import NIcon from '../components/NIcon.vue'
import NState from '../components/NState.vue'
import { WedgeDetector, type CatalogItem } from '../lib/scan'
import { money, t } from '../lib/i18n'

const props = defineProps<{ items: CatalogItem[]; currency: string; state: string; favourites?: string[] }>()
const emit = defineEmits<{ pick: [CatalogItem]; scan: [string]; camera: [] }>()

const query = ref('')
const group = ref<string | null>(null)
const search = ref<HTMLInputElement | null>(null)

const groups = computed(() => [...new Set(props.items.map((i) => i.item_group).filter(Boolean))].sort() as string[])
const shown = computed(() => {
  const q = query.value.trim().toLowerCase()
  let list = props.items
  if (group.value) list = list.filter((i) => i.item_group === group.value)
  if (q) {
    list = list.filter((i) => i.item_name.toLowerCase().includes(q) || i.item_code.toLowerCase().includes(q) || i.barcodes.some((b) => b.barcode === q))
  }
  return list.slice(0, 120)
})

const wedge = new WedgeDetector((code) => {
  query.value = ''
  emit('scan', code)
})
function onKey(e: KeyboardEvent) {
  const target = e.target as HTMLElement
  const typingElsewhere = target && target !== search.value && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
  if (typingElsewhere || e.ctrlKey || e.metaKey || e.altKey) return
  if (wedge.key(e.key, performance.now()) && target !== search.value) e.preventDefault()
  if (e.key === '/' && target !== search.value) {
    e.preventDefault()
    search.value?.focus()
  }
}
onMounted(() => window.addEventListener('keydown', onKey, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true))

function submitSearch() {
  const q = query.value.trim()
  if (!q) return
  if (shown.value.length === 1) {
    emit('pick', shown.value[0])
    query.value = ''
  } else if (!shown.value.length) {
    emit('scan', q)
    query.value = ''
  }
}
</script>

<template>
  <section class="cat" :aria-label="t('Sell')">
    <form class="cat__search" role="search" @submit.prevent="submitSearch">
      <NIcon name="search" class="cat__search-icon" />
      <label class="sr-only" for="cat-q">{{ t('Search products or scan a code') }}</label>
      <input id="cat-q" ref="search" v-model="query" class="cat__input" type="search" :placeholder="t('Search products or scan a code')" autocomplete="off" enterkeyhint="search" />
      <button type="button" class="cat__camera" :aria-label="t('Scan')" @click="emit('camera')"><NIcon name="scan" :size="22" /></button>
    </form>
    <div class="cat__groups" role="tablist" :aria-label="t('Categories')">
      <button type="button" role="tab" :aria-selected="group === null" class="cat__chip" @click="group = null">{{ t('All') }}</button>
      <button v-for="g in groups" :key="g" type="button" role="tab" :aria-selected="group === g" class="cat__chip" @click="group = g">{{ g }}</button>
    </div>
    <div class="cat__grid scroll">
      <NState v-if="state === 'loading'" kind="loading" :title="t('Loading products')" />
      <NState v-else-if="state === 'error'" kind="offline" :title="t('Products could not be loaded')" :detail="t('Check the connection, then try again.')" />
      <NState v-else-if="!shown.length" kind="empty" :title="query ? t('No product matches “{0}”', query) : t('No products in this category')" :detail="query ? t('Press Enter to look the code up on the server.') : ''" />
      <ul v-else class="cat__list" role="list">
        <li v-for="i in shown" :key="i.item_code">
          <button type="button" class="cat__item" @click="emit('pick', i)">
            <span class="cat__thumb" aria-hidden="true">
              <img v-if="i.image" :src="i.image" alt="" loading="lazy" />
              <span v-else>{{ i.item_name.slice(0, 1) }}</span>
            </span>
            <span class="cat__name">{{ i.item_name }}</span>
            <span class="cat__meta">
              <span class="cat__price num">{{ i.rate === null ? t('No price') : money(i.rate, currency) }}</span>
              <span v-if="i.available !== null && i.available !== undefined && i.available <= 0" class="cat__stock">{{ t('Out of stock') }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>

<style>
.cat { display: flex; flex-direction: column; min-block-size: 0; flex: 1; gap: var(--space-3); padding: var(--space-4); }
.cat__search { position: relative; display: flex; align-items: center; }
.cat__search-icon { position: absolute; inset-inline-start: 14px; color: var(--text-muted); pointer-events: none; }
.cat__input { flex: 1; min-block-size: 52px; padding-inline: 44px 60px; border-radius: var(--radius-lg); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-strong); }
.cat__camera { position: absolute; inset-inline-end: 6px; inline-size: var(--touch); block-size: var(--touch); border: 0; border-radius: var(--radius-md); background: var(--brand-fill); color: var(--brand-on-fill); display: grid; place-items: center; cursor: pointer; }
.cat__groups { display: flex; gap: var(--space-2); overflow-x: auto; scrollbar-width: none; padding-block-end: 2px; }
.cat__chip { flex: none; min-block-size: 40px; padding-inline: var(--space-4); border-radius: var(--radius-pill); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-body); font-weight: 500; cursor: pointer; white-space: nowrap; }
.cat__chip[aria-selected='true'] { background: var(--action-primary-bg); color: var(--action-primary-fg); border-color: transparent; }
.cat__grid { flex: 1; min-block-size: 0; }
.cat__list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); gap: var(--space-3); }
.cat__item { inline-size: 100%; block-size: 100%; display: grid; grid-template-rows: auto 1fr auto; gap: var(--space-2); padding: var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-subtle); background: var(--surface-card); text-align: start; cursor: pointer; color: var(--text-body); transition: border-color var(--dur-fast); }
.cat__item:hover { border-color: var(--text-strong); }
.cat__item:active { background: var(--brand-fill); }
.cat__thumb { aspect-ratio: 4 / 3; border-radius: var(--radius-sm); background: var(--surface-sunken); display: grid; place-items: center; overflow: hidden; font-size: var(--text-xl); font-weight: 600; color: var(--text-muted); }
.cat__thumb img { inline-size: 100%; block-size: 100%; object-fit: cover; }
.cat__name { font-weight: 600; color: var(--text-strong); line-height: 1.25; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.cat__meta { display: flex; justify-content: space-between; align-items: baseline; gap: var(--space-2); flex-wrap: wrap; }
.cat__price { font-weight: 600; color: var(--text-strong); }
.cat__stock { font-size: var(--text-xs); color: var(--danger-fg); font-weight: 600; }
@media (max-width: 520px) { .cat { padding: var(--space-3); } .cat__list { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); } }
</style>
