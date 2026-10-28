<script setup lang="ts">
// Menu builder (managers): sections in order, dishes as photo cards, and option groups such as a
// required size or an optional combo with its own pictures and add-on prices. Saving a dish creates
// or updates the ERPNext Item and its price on this register's price list, so the till, the guest
// menu, invoices and reports all read the same thing.
import { computed, onMounted, ref } from 'vue'
import NButton from '@shared/components/NButton.vue'
import NIcon from '@shared/components/NIcon.vue'
import NQty from '@shared/components/NQty.vue'
import NSheet from '@shared/components/NSheet.vue'
import NState from '@shared/components/NState.vue'
import { toast } from '@shared/components/toast'
import { call } from '@shared/lib/api'
import { lang, money, t } from '@shared/lib/i18n'
import { uploadImage } from '@shared/lib/upload'
import { MENU_API, useTill } from '../state'

interface Option { option_code?: string; option_name: string; description: string; image: string; price: number; sold_out: number }
interface Group { name?: string; group_name: string; min_select: number; max_select: number; options: Option[] }
interface Dish {
  name?: string; item_code?: string; display_name: string; display_name_ar: string; section: string; price: number | null; image: string
  item_group: string; description: string; allergens: string; dietary: string; sold_out: number; guest_visible: number; default_course: number; groups: string[]
}
interface Section { name: string | null; section_name: string; section_name_ar: string }
interface Data { register: string; currency: string; price_list: string; item_groups: string[]; sections: Section[]; items: Dish[]; groups: Group[] }

const till = useTill()
const data = ref<Data | null>(null)
const error = ref('')
const section = ref<string>('')
const query = ref('')
const reg = computed(() => till.registerName.value)
const currency = computed(() => data.value?.currency ?? 'USD')
const groupsByName = computed(() => Object.fromEntries((data.value?.groups ?? []).map((g) => [g.name!, g])))

async function load() {
  try {
    data.value = await call<Data>(MENU_API('load'), { register_name: reg.value }, { method: 'GET' })
    if (!section.value || !data.value.sections.some((s) => s.section_name === section.value)) section.value = data.value.sections[0]?.section_name ?? ''
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
  }
}
onMounted(load)

const label = (en: string, ar?: string | null) => (lang() === 'ar' && ar) || en
const countIn = (s: string) => (data.value?.items ?? []).filter((i) => i.section === s).length
const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  const items = data.value?.items ?? []
  if (q) return items.filter((i) => `${i.display_name} ${i.display_name_ar} ${i.description}`.toLowerCase().includes(q))
  return items.filter((i) => i.section === section.value)
})

// ------------------------------------------------------------------ quick actions on cards
async function flag(d: Dish, field: 'sold_out' | 'guest_visible') {
  const value = d[field] ? 0 : 1
  d[field] = value
  try {
    await call(MENU_API('set_flag'), { register_name: reg.value, name: d.name, field, value })
  } catch (e) {
    d[field] = value ? 0 : 1
    toast((e as Error).message, 'danger')
  }
}
async function shift(d: Dish, by: -1 | 1) {
  const list = (data.value?.items ?? []).filter((i) => i.section === d.section)
  const i = list.indexOf(d)
  const j = i + by
  if (j < 0 || j >= list.length) return
  ;[list[i], list[j]] = [list[j], list[i]]
  const all = data.value!.items.filter((x) => x.section !== d.section)
  data.value!.items = [...all, ...list]
  try {
    await call(MENU_API('reorder_items'), { register_name: reg.value, section: d.section, names: list.map((x) => x.name) })
  } catch (e) {
    toast((e as Error).message, 'danger')
    await load()
  }
}

// ------------------------------------------------------------------ dish editor
const dish = ref<Dish | null>(null)
const dishBusy = ref(false)
const dishError = ref('')
const newSection = ref('')
const uploading = ref<string | null>(null)
const attachPick = ref('')

function editDish(d?: Dish) {
  dishError.value = ''
  newSection.value = ''
  attachPick.value = ''
  dish.value = d
    ? JSON.parse(JSON.stringify(d))
    : { display_name: '', display_name_ar: '', section: section.value || data.value?.sections[0]?.section_name || '', price: null, image: '', item_group: '', description: '', allergens: '', dietary: '', sold_out: 0, guest_visible: 1, default_course: 1, groups: [] }
}
async function pickImage(e: Event, set: (url: string) => void, key: string) {
  const file = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!file) return
  uploading.value = key
  try {
    set(await uploadImage(file))
  } catch (err) {
    toast((err as Error).message, 'danger')
  } finally {
    uploading.value = null
  }
}
function dropImage(e: DragEvent, set: (url: string) => void, key: string) {
  const file = e.dataTransfer?.files?.[0]
  if (file) void pickImage({ target: { files: [file], value: '' } } as unknown as Event, set, key)
}
async function saveDish() {
  const d = dish.value
  if (!d) return
  if (newSection.value.trim()) d.section = newSection.value.trim()
  dishBusy.value = true
  dishError.value = ''
  try {
    data.value = await call<Data>(MENU_API('save_item'), { register_name: reg.value, item: d })
    section.value = d.section
    toast(d.name ? t('Dish saved') : t('Dish added to the menu'))
    dish.value = null
  } catch (e) {
    dishError.value = (e as Error).message
  } finally {
    dishBusy.value = false
  }
}
async function removeDish() {
  const d = dish.value
  if (!d?.name || !confirm(t('Take {0} off this menu? Past sales are kept.', d.display_name))) return
  dishBusy.value = true
  try {
    data.value = await call<Data>(MENU_API('remove_item'), { register_name: reg.value, name: d.name })
    dish.value = null
  } catch (e) {
    dishError.value = (e as Error).message
  } finally {
    dishBusy.value = false
  }
}
function attachGroup() {
  if (dish.value && attachPick.value && !dish.value.groups.includes(attachPick.value)) dish.value.groups.push(attachPick.value)
  attachPick.value = ''
}
function moveGroup(i: number, by: -1 | 1) {
  const g = dish.value!.groups
  const j = i + by
  if (j < 0 || j >= g.length) return
  ;[g[i], g[j]] = [g[j], g[i]]
}

// ------------------------------------------------------------------ option group editor
const group = ref<Group | null>(null)
const groupBusy = ref(false)
const groupError = ref('')
const attachAfterSave = ref(false)

function editGroup(name?: string) {
  groupError.value = ''
  const g = name ? groupsByName.value[name] : null
  attachAfterSave.value = !name && !!dish.value
  group.value = g
    ? JSON.parse(JSON.stringify(g))
    : { group_name: '', min_select: 0, max_select: 1, options: [{ option_name: '', description: '', image: '', price: 0, sold_out: 0 }] }
}
const required = computed({
  get: () => (group.value?.min_select ?? 0) > 0,
  set: (v: boolean) => { if (group.value) group.value.min_select = v ? 1 : 0 },
})
function addOption() {
  group.value?.options.push({ option_name: '', description: '', image: '', price: 0, sold_out: 0 })
}
async function saveGroup() {
  const g = group.value
  if (!g) return
  g.max_select = Math.max(g.max_select, g.min_select, 1)
  groupBusy.value = true
  groupError.value = ''
  try {
    data.value = await call<Data>(MENU_API('save_group'), { register_name: reg.value, group: g })
    const saved = data.value.groups.find((x) => x.group_name === g.group_name)
    if (attachAfterSave.value && saved?.name && dish.value && !dish.value.groups.includes(saved.name)) dish.value.groups.push(saved.name)
    toast(t('Option group saved'))
    group.value = null
  } catch (e) {
    groupError.value = (e as Error).message
  } finally {
    groupBusy.value = false
  }
}

// ------------------------------------------------------------------ sections editor
const sections = ref<(Section & { old_name: string })[] | null>(null)
const sectionsBusy = ref(false)
const sectionsError = ref('')
function editSections() {
  sectionsError.value = ''
  sections.value = (data.value?.sections ?? []).map((s) => ({ ...s, old_name: s.section_name }))
  if (!sections.value.length) sections.value.push({ name: null, section_name: '', section_name_ar: '', old_name: '' })
}
function moveSection(i: number, by: -1 | 1) {
  const s = sections.value!
  const j = i + by
  if (j < 0 || j >= s.length) return
  ;[s[i], s[j]] = [s[j], s[i]]
}
async function saveSections() {
  sectionsBusy.value = true
  sectionsError.value = ''
  try {
    const rows = sections.value!.filter((s) => s.section_name.trim())
    data.value = await call<Data>(MENU_API('save_sections'), { register_name: reg.value, sections: rows })
    const renamed = rows.find((s) => s.old_name === section.value)
    section.value = renamed?.section_name ?? data.value.sections[0]?.section_name ?? ''
    sections.value = null
    toast(t('Sections saved'))
  } catch (e) {
    sectionsError.value = (e as Error).message
  } finally {
    sectionsBusy.value = false
  }
}

const editorGroups = computed(() => (dish.value?.groups ?? []).map((n) => groupsByName.value[n]).filter(Boolean))
const attachable = computed(() => (data.value?.groups ?? []).filter((g) => !dish.value?.groups.includes(g.name!)))
const summary = (g: Group) => `${g.min_select ? t('Required') : t('Optional')} · ${g.max_select === 1 ? t('Choose 1') : t('Choose up to {0}', g.max_select)}`
const optionList = (g: Group) => g.options.map((o) => o.option_name).join(', ')
</script>

<template>
  <div class="mb">
    <NState v-if="error" kind="error" :title="t('The menu could not be loaded')" :detail="error" :retry="load" />
    <NState v-else-if="!data" kind="loading" :title="t('Loading the menu')" />
    <template v-else>
      <aside class="mb__side" :aria-label="t('Menu sections')">
        <div class="mb__side-head">
          <h2>{{ t('Sections') }}</h2>
          <button type="button" class="mb__icon" :aria-label="t('Edit sections')" :title="t('Edit sections')" @click="editSections"><NIcon name="edit" :size="18" /></button>
        </div>
        <ul class="mb__secs" role="tablist">
          <li v-for="s in data.sections" :key="s.section_name">
            <button type="button" role="tab" :aria-selected="!query && section === s.section_name" class="mb__sec" @click="section = s.section_name; query = ''">
              <span class="mb__sec-name">{{ label(s.section_name, s.section_name_ar) }}</span>
              <span class="mb__sec-count num">{{ countIn(s.section_name) }}</span>
            </button>
          </li>
        </ul>
        <NButton variant="ghost" icon="plus" block @click="editSections">{{ t('Add section') }}</NButton>
      </aside>

      <section class="mb__main">
        <header class="mb__head">
          <div>
            <h1>{{ query ? t('Search results') : label(section, data.sections.find((s) => s.section_name === section)?.section_name_ar) || t('Menu') }}</h1>
            <p class="muted">{{ t('{0} dishes · prices from {1}', visible.length, data.price_list) }}</p>
          </div>
          <label class="mb__search">
            <NIcon name="search" :size="18" />
            <input v-model="query" type="search" :placeholder="t('Search dishes')" :aria-label="t('Search dishes')" />
          </label>
          <NButton variant="primary" icon="plus" @click="editDish()">{{ t('Add dish') }}</NButton>
        </header>

        <NState v-if="!data.sections.length && !data.items.length" kind="empty" icon="menu" :title="t('Start your menu')" :detail="t('Add sections like Burgers, Sides and Drinks, then add dishes with photos, prices and options.')" />
        <NState v-else-if="!visible.length" kind="empty" icon="menu" :title="query ? t('No dish matches') : t('No dishes in this section yet')" />
        <ul v-else class="mb__grid" role="list">
          <li v-for="(d, i) in visible" :key="d.name" :class="['mb__card', { 'mb__card--out': d.sold_out }]">
            <button type="button" class="mb__card-open" :aria-label="t('Edit {0}', d.display_name)" @click="editDish(d)">
              <span class="mb__card-img">
                <img v-if="d.image" :src="d.image" alt="" loading="lazy" decoding="async" />
                <NIcon v-else name="image" :size="34" />
                <span v-if="d.sold_out" class="mb__chip mb__chip--out">{{ t('Sold out') }}</span>
                <span v-else-if="!d.guest_visible" class="mb__chip">{{ t('Staff only') }}</span>
              </span>
              <span class="mb__card-body">
                <span class="mb__card-name">{{ label(d.display_name, d.display_name_ar) }}</span>
                <span v-if="d.description" class="mb__card-desc">{{ d.description }}</span>
                <span v-if="d.groups.length" class="mb__card-opts">{{ d.groups.map((g) => groupsByName[g]?.group_name ?? g).join(' · ') }}</span>
              </span>
            </button>
            <div class="mb__card-foot">
              <span class="mb__price num">{{ d.price ? money(d.price, currency) : t('No price') }}</span>
              <span class="mb__card-tools">
                <button v-if="!query" type="button" class="mb__icon" :disabled="i === 0" :aria-label="t('Move up')" @click="shift(d, -1)"><NIcon name="up" :size="16" /></button>
                <button v-if="!query" type="button" class="mb__icon" :disabled="i === visible.length - 1" :aria-label="t('Move down')" @click="shift(d, 1)"><NIcon name="down" :size="16" /></button>
                <button type="button" :class="['mb__toggle', { 'mb__toggle--on': d.sold_out }]" :aria-pressed="!!d.sold_out" @click="flag(d, 'sold_out')">{{ t('Sold out') }}</button>
              </span>
            </div>
          </li>
        </ul>
      </section>
    </template>

    <!-- dish editor -->
    <NSheet :open="!!dish" wide :title="dish?.name ? t('Edit dish') : t('New dish')" @close="dish = null">
      <form v-if="dish && data" class="mb__form" novalidate @submit.prevent="saveDish">
        <div class="mb__form-media">
          <label :class="['mb__drop', { 'mb__drop--has': dish.image }]" @dragover.prevent @drop.prevent="dropImage($event, (u) => (dish!.image = u), 'dish')">
            <img v-if="dish.image" :src="dish.image" alt="" />
            <span v-else class="mb__drop-empty"><NIcon name="image" :size="36" />{{ t('Add a photo') }}<small>{{ t('Drop an image here or tap to choose') }}</small></span>
            <span v-if="uploading === 'dish'" class="mb__drop-busy">{{ t('Uploading') }}…</span>
            <input type="file" accept="image/*" class="sr-only" @change="pickImage($event, (u) => (dish!.image = u), 'dish')" />
          </label>
          <button v-if="dish.image" type="button" class="mb__link" @click="dish.image = ''">{{ t('Remove photo') }}</button>
          <p class="muted mb__hint">{{ t('Square or 4:3 photos on a plain background look best. Large photos are reduced automatically.') }}</p>
        </div>

        <div class="mb__form-fields">
          <div class="mb__row">
            <label class="mb__field">{{ t('Name') }}<input v-model="dish.display_name" class="mb__input" maxlength="140" /></label>
            <label class="mb__field">{{ t('Arabic name') }}<input v-model="dish.display_name_ar" class="mb__input" dir="rtl" maxlength="140" /></label>
          </div>
          <div class="mb__row">
            <label class="mb__field">{{ t('Section') }}
              <select v-model="dish.section" class="mb__input" :disabled="!!newSection.trim()">
                <option v-for="s in data.sections" :key="s.section_name" :value="s.section_name">{{ label(s.section_name, s.section_name_ar) }}</option>
              </select>
            </label>
            <label class="mb__field">{{ t('…or a new section') }}<input v-model="newSection" class="mb__input" maxlength="140" :placeholder="t('e.g. Burgers')" /></label>
          </div>
          <div class="mb__row">
            <label class="mb__field"><span>{{ t('Price') }} <small class="muted">({{ currency }})</small></span><input v-model.number="dish.price" class="mb__input num" type="number" min="0" step="0.01" inputmode="decimal" dir="ltr" /></label>
            <label class="mb__field">{{ t('Item group') }}
              <select v-model="dish.item_group" class="mb__input">
                <option value="">{{ t('Automatic') }}</option>
                <option v-for="g in data.item_groups" :key="g" :value="g">{{ g }}</option>
              </select>
            </label>
          </div>
          <label class="mb__field">{{ t('Description') }}<textarea v-model="dish.description" class="mb__input mb__textarea" rows="2" maxlength="1000" /></label>
          <div class="mb__row">
            <label class="mb__field">{{ t('Allergens') }}<input v-model="dish.allergens" class="mb__input" :placeholder="t('e.g. gluten, milk')" maxlength="140" /></label>
            <label class="mb__field">{{ t('Dietary tags') }}<input v-model="dish.dietary" class="mb__input" :placeholder="t('e.g. vegetarian, spicy')" maxlength="140" /></label>
          </div>
          <div class="mb__checks">
            <label class="mb__check"><input v-model="dish.guest_visible" type="checkbox" :true-value="1" :false-value="0" />{{ t('Show on the guest QR menu') }}</label>
            <label class="mb__check"><input v-model="dish.sold_out" type="checkbox" :true-value="1" :false-value="0" />{{ t('Sold out') }}</label>
            <span class="mb__check">{{ t('Course') }}
              <span class="mb__seg" role="radiogroup" :aria-label="t('Course')">
                <button v-for="c in [1, 2, 3]" :key="c" type="button" role="radio" :aria-checked="dish.default_course === c" class="mb__segb mb__segb--sm num" @click="dish!.default_course = c">{{ c }}</button>
              </span>
            </span>
          </div>

          <fieldset class="mb__groups">
            <legend>{{ t('Options and sizes') }}</legend>
            <p class="muted mb__hint">{{ t('Sizes, combos, extras and removals. Required groups must be chosen before the dish can be added.') }}</p>
            <ul class="mb__glist" role="list">
              <li v-for="(g, i) in editorGroups" :key="g!.name" class="mb__gitem">
                <span class="mb__gtext"><strong>{{ g!.group_name }}</strong><small class="muted">{{ summary(g!) }} — {{ optionList(g!) }}</small></span>
                <button type="button" class="mb__icon" :disabled="i === 0" :aria-label="t('Move up')" @click="moveGroup(i, -1)"><NIcon name="up" :size="16" /></button>
                <button type="button" class="mb__icon" :aria-label="t('Edit {0}', g!.group_name)" @click="editGroup(g!.name)"><NIcon name="edit" :size="16" /></button>
                <button type="button" class="mb__icon" :aria-label="t('Remove {0}', g!.group_name)" @click="dish.groups.splice(i, 1)"><NIcon name="close" :size="16" /></button>
              </li>
            </ul>
            <div class="mb__gadd">
              <select v-model="attachPick" class="mb__input" :aria-label="t('Use an existing option group')" @change="attachGroup">
                <option value="">{{ t('Use an existing group…') }}</option>
                <option v-for="g in attachable" :key="g.name" :value="g.name">{{ g.group_name }} ({{ g.options.length }})</option>
              </select>
              <NButton variant="ghost" icon="plus" @click="editGroup()">{{ t('New option group') }}</NButton>
            </div>
          </fieldset>
          <p v-if="dishError" class="mb__error" role="alert">{{ dishError }}</p>
        </div>
      </form>
      <template #actions>
        <NButton v-if="dish?.name" variant="danger" icon="trash" :disabled="dishBusy" @click="removeDish">{{ t('Remove') }}</NButton>
        <span class="mb__spacer" />
        <NButton @click="dish = null">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" icon="check" :busy="dishBusy" :disabled="!!uploading" @click="saveDish">{{ t('Save dish') }}</NButton>
      </template>
    </NSheet>

    <!-- option group editor -->
    <NSheet :open="!!group" wide :title="group?.name ? t('Edit option group') : t('New option group')" @close="group = null">
      <form v-if="group" class="mb__gform" novalidate @submit.prevent="saveGroup">
        <div class="mb__row">
          <label class="mb__field">{{ t('Group name') }}<input v-model="group.group_name" class="mb__input" maxlength="140" :readonly="!!group.name" :placeholder="t('e.g. Size, Make it a combo, Extras')" /></label>
          <div class="mb__field">{{ t('Choice') }}
            <div class="mb__seg" role="radiogroup">
              <button type="button" role="radio" :aria-checked="required" class="mb__segb" @click="required = true">{{ t('Required') }}</button>
              <button type="button" role="radio" :aria-checked="!required" class="mb__segb" @click="required = false">{{ t('Optional') }}</button>
            </div>
          </div>
          <label class="mb__field">{{ t('Guests can choose up to') }}<NQty v-model="group.max_select" :min="1" :max="20" :label="t('Guests can choose up to')" /></label>
        </div>
        <ul class="mb__olist" role="list">
          <li v-for="(o, i) in group.options" :key="o.option_code ?? i" class="mb__orow">
            <label class="mb__othumb" :aria-label="t('Option photo')" @dragover.prevent @drop.prevent="dropImage($event, (u) => (o.image = u), `o${i}`)">
              <img v-if="o.image" :src="o.image" alt="" />
              <NIcon v-else name="image" :size="22" />
              <span v-if="uploading === `o${i}`" class="mb__drop-busy">…</span>
              <input type="file" accept="image/*" class="sr-only" @change="pickImage($event, (u) => (o.image = u), `o${i}`)" />
            </label>
            <input v-model="o.option_name" class="mb__input" :placeholder="t('Option, e.g. Coleslaw combo')" :aria-label="t('Option name')" maxlength="140" />
            <input v-model="o.description" class="mb__input" :placeholder="t('Details, e.g. coleslaw and a drink')" :aria-label="t('Description')" maxlength="140" />
            <label class="mb__oprice"><span aria-hidden="true">+</span><input v-model.number="o.price" class="mb__input num" type="number" min="0" step="0.01" inputmode="decimal" dir="ltr" :aria-label="t('Extra price')" /></label>
            <label class="mb__check mb__check--sm"><input v-model="o.sold_out" type="checkbox" :true-value="1" :false-value="0" />{{ t('Sold out') }}</label>
            <button type="button" class="mb__icon" :disabled="group.options.length === 1" :aria-label="t('Remove option')" @click="group.options.splice(i, 1)"><NIcon name="trash" :size="16" /></button>
          </li>
        </ul>
        <NButton variant="ghost" icon="plus" @click="addOption">{{ t('Add option') }}</NButton>
        <p class="muted mb__hint">{{ t('An extra price is billed as its own line on the invoice. Leave 0 for free choices such as "no onions".') }}</p>
        <p v-if="groupError" class="mb__error" role="alert">{{ groupError }}</p>
      </form>
      <template #actions>
        <NButton @click="group = null">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" icon="check" :busy="groupBusy" :disabled="!!uploading" @click="saveGroup">{{ t('Save group') }}</NButton>
      </template>
    </NSheet>

    <!-- sections editor -->
    <NSheet :open="!!sections" :title="t('Menu sections')" @close="sections = null">
      <ul v-if="sections" class="mb__slist" role="list">
        <li v-for="(s, i) in sections" :key="i" class="mb__srow">
          <input v-model="s.section_name" class="mb__input" :placeholder="t('Section, e.g. Burgers')" :aria-label="t('Section')" maxlength="140" />
          <input v-model="s.section_name_ar" class="mb__input" dir="rtl" :placeholder="t('Arabic name')" :aria-label="t('Arabic name')" maxlength="140" />
          <button type="button" class="mb__icon" :disabled="i === 0" :aria-label="t('Move up')" @click="moveSection(i, -1)"><NIcon name="up" :size="16" /></button>
          <button type="button" class="mb__icon" :disabled="i === sections.length - 1" :aria-label="t('Move down')" @click="moveSection(i, 1)"><NIcon name="down" :size="16" /></button>
          <button type="button" class="mb__icon" :aria-label="t('Remove section')" @click="sections.splice(i, 1)"><NIcon name="trash" :size="16" /></button>
        </li>
      </ul>
      <NButton variant="ghost" icon="plus" @click="sections?.push({ name: null, section_name: '', section_name_ar: '', old_name: '' })">{{ t('Add section') }}</NButton>
      <p v-if="sectionsError" class="mb__error" role="alert">{{ sectionsError }}</p>
      <template #actions>
        <NButton @click="sections = null">{{ t('Cancel') }}</NButton>
        <NButton variant="primary" icon="check" :busy="sectionsBusy" @click="saveSections">{{ t('Save sections') }}</NButton>
      </template>
    </NSheet>
  </div>
</template>

<style>
.mb { flex: 1; min-block-size: 0; display: grid; grid-template-columns: 260px minmax(0, 1fr); }
.mb__side { border-inline-end: 1px solid var(--border-subtle); padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-3); overflow-y: auto; background: var(--surface-card); }
.mb__side-head { display: flex; align-items: center; justify-content: space-between; }
.mb__side-head h2 { font-size: var(--text-md); }
.mb__secs { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.mb__sec { inline-size: 100%; min-block-size: var(--touch); display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding-inline: var(--space-3); border: 0; border-radius: var(--radius-md); background: transparent; color: var(--text-body); cursor: pointer; text-align: start; font: inherit; }
.mb__sec:hover { background: var(--surface-sunken); }
.mb__sec[aria-selected='true'] { background: var(--brand-fill); color: var(--brand-on-fill); font-weight: 600; }
.mb__sec-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mb__sec-count { font-size: var(--text-sm); opacity: 0.75; }
.mb__main { min-block-size: 0; overflow-y: auto; padding: var(--space-4) var(--space-5) var(--space-7); }
.mb__head { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; margin-block-end: var(--space-4); }
.mb__head > div:first-child { flex: 1; min-inline-size: 200px; }
.mb__head h1 { font-size: var(--text-2xl); color: var(--text-strong); }
.mb__search { display: inline-flex; align-items: center; gap: var(--space-2); min-block-size: var(--touch); padding-inline: var(--space-3); border: 1px solid var(--border-strong); border-radius: var(--radius-pill); background: var(--surface-card); color: var(--text-muted); }
.mb__search input { border: 0; background: transparent; font: inherit; color: var(--text-strong); inline-size: 180px; outline: none; }
.mb__grid { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-4); }
.mb__card { display: flex; flex-direction: column; background: var(--surface-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-raised); }
.mb__card--out .mb__card-img img { filter: grayscale(0.8); opacity: 0.6; }
.mb__card-open { display: flex; flex-direction: column; border: 0; padding: 0; background: none; text-align: start; cursor: pointer; color: inherit; font: inherit; flex: 1; }
.mb__card-img { position: relative; aspect-ratio: 4 / 3; display: grid; place-items: center; background: var(--surface-sunken); color: var(--text-muted); }
.mb__card-img img { position: absolute; inset: 0; inline-size: 100%; block-size: 100%; object-fit: cover; }
.mb__chip { position: absolute; inset-block-start: var(--space-2); inset-inline-start: var(--space-2); padding: 2px 10px; border-radius: var(--radius-pill); background: var(--surface-card); color: var(--text-strong); font-size: var(--text-xs); font-weight: 700; }
.mb__chip--out { background: var(--danger-fg); color: #fff; }
.mb__card-body { display: grid; gap: 4px; padding: var(--space-3) var(--space-3) var(--space-2); }
.mb__card-name { font-weight: 700; color: var(--text-strong); }
.mb__card-desc { font-size: var(--text-sm); color: var(--text-muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.mb__card-opts { font-size: var(--text-xs); color: var(--text-body); background: var(--surface-sunken); padding: 2px 8px; border-radius: var(--radius-sm); justify-self: start; }
.mb__card-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--space-1) var(--space-2); padding: var(--space-2) var(--space-3) var(--space-3); flex-wrap: wrap; }
.mb__price { font-weight: 700; color: var(--text-strong); }
.mb__card-tools { display: inline-flex; align-items: center; gap: 2px; margin-inline-start: auto; }
.mb__icon { inline-size: 36px; block-size: 36px; display: grid; place-items: center; border: 0; border-radius: var(--radius-md); background: transparent; color: var(--text-body); cursor: pointer; flex: none; }
.mb__icon:hover:not(:disabled) { background: var(--surface-sunken); }
.mb__icon:disabled { opacity: 0.3; cursor: default; }
.mb__toggle { white-space: nowrap; min-block-size: 36px; padding-inline: var(--space-3); border-radius: var(--radius-pill); border: 1px solid var(--border-strong); background: var(--surface-card); color: var(--text-body); font: inherit; font-size: var(--text-sm); font-weight: 600; cursor: pointer; }
.mb__toggle--on { background: var(--danger-fg); border-color: var(--danger-fg); color: #fff; }

.mb__form { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: var(--space-5); align-items: start; }
.mb__form-media { display: grid; gap: var(--space-2); position: sticky; inset-block-start: 0; }
.mb__drop { position: relative; aspect-ratio: 4 / 3; display: grid; place-items: center; border: 2px dashed var(--border-strong); border-radius: var(--radius-lg); background: var(--surface-sunken); cursor: pointer; overflow: hidden; color: var(--text-muted); }
.mb__drop:focus-within { outline: 3px solid var(--focus-ring); }
.mb__drop--has { border-style: solid; }
.mb__drop img { position: absolute; inset: 0; inline-size: 100%; block-size: 100%; object-fit: cover; }
.mb__drop-empty { display: grid; justify-items: center; gap: 4px; font-weight: 600; text-align: center; padding: var(--space-3); }
.mb__drop-empty small { font-weight: 400; font-size: var(--text-xs); }
.mb__drop-busy { position: absolute; inset: 0; display: grid; place-items: center; background: rgb(255 255 255 / 0.75); color: var(--text-strong); font-weight: 700; }
.mb__form-fields { display: grid; gap: var(--space-3); }
.mb__row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-3); }
.mb__field { display: grid; gap: 6px; font-size: var(--text-sm); font-weight: 600; color: var(--text-strong); align-content: start; }
.mb__input { inline-size: 100%; min-block-size: var(--touch); padding-inline: var(--space-3); border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-card); color: var(--text-strong); font: inherit; font-weight: 400; }
.mb__input[readonly] { background: var(--surface-sunken); }
.mb__textarea { padding-block: var(--space-2); resize: vertical; }
.mb__checks { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: center; }
.mb__check { display: inline-flex; align-items: center; gap: var(--space-2); font-weight: 600; font-size: var(--text-sm); }
.mb__check input { inline-size: 20px; block-size: 20px; accent-color: var(--action-primary-bg); }
.mb__check--sm { font-weight: 400; white-space: nowrap; }
.mb__groups { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: var(--space-3) var(--space-4); margin: 0; display: grid; gap: var(--space-2); }
.mb__groups legend { font-weight: 700; padding-inline: var(--space-1); color: var(--text-strong); }
.mb__glist { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.mb__gitem { display: flex; align-items: center; gap: var(--space-1); padding: var(--space-2) var(--space-3); background: var(--surface-sunken); border-radius: var(--radius-md); }
.mb__gtext { flex: 1; min-inline-size: 0; display: grid; }
.mb__gtext small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mb__gadd { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.mb__gadd select { flex: 1; min-inline-size: 200px; }
.mb__hint { font-size: var(--text-sm); }
.mb__error { color: var(--danger-fg); background: var(--danger-bg); padding: var(--space-3); border-radius: var(--radius-md); font-weight: 600; font-size: var(--text-sm); }
.mb__link { justify-self: start; border: 0; background: none; padding: 0; color: var(--text-body); text-decoration: underline; cursor: pointer; font: inherit; font-size: var(--text-sm); }
.mb__spacer { flex: 1; }

.mb__gform { display: grid; gap: var(--space-4); }
.mb__seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius-md); overflow: hidden; justify-self: start; }
.mb__segb { min-block-size: var(--touch); padding-inline: var(--space-4); border: 0; background: var(--surface-card); color: var(--text-body); font: inherit; font-weight: 600; cursor: pointer; }
.mb__segb + .mb__segb { border-inline-start: 1px solid var(--border-strong); }
.mb__segb[aria-checked='true'] { background: var(--brand-fill); color: var(--brand-on-fill); }
.mb__segb--sm { min-inline-size: 44px; padding-inline: var(--space-3); }
.mb__olist { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.mb__orow { display: grid; grid-template-columns: 56px minmax(140px, 1.2fr) minmax(140px, 1.5fr) 120px auto auto; gap: var(--space-2); align-items: center; padding: var(--space-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); background: var(--surface-card); }
.mb__othumb { position: relative; inline-size: 56px; block-size: 56px; display: grid; place-items: center; border: 1px dashed var(--border-strong); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--text-muted); cursor: pointer; overflow: hidden; }
.mb__othumb img { position: absolute; inset: 0; inline-size: 100%; block-size: 100%; object-fit: cover; }
.mb__othumb:focus-within { outline: 3px solid var(--focus-ring); }
.mb__oprice { display: flex; align-items: center; gap: 4px; font-weight: 700; }
.mb__slist { list-style: none; margin: 0 0 var(--space-3); padding: 0; display: grid; gap: var(--space-2); }
.mb__srow { display: grid; grid-template-columns: 1fr 1fr auto auto auto; gap: var(--space-2); align-items: center; }

@media (max-width: 900px) {
  .mb { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
  .mb__side { border-inline-end: 0; border-block-end: 1px solid var(--border-subtle); flex-direction: row; align-items: center; overflow-x: auto; padding: var(--space-2) var(--space-3); }
  .mb__side-head h2, .mb__side > .n-btn { display: none; }
  .mb__secs { display: flex; gap: var(--space-2); }
  .mb__sec { white-space: nowrap; border: 1px solid var(--border-strong); border-radius: var(--radius-pill); }
  .mb__main { padding: var(--space-3); }
  .mb__grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: var(--space-3); }
  .mb__search input { inline-size: 120px; }
  .mb__card-tools .mb__icon { inline-size: 30px; block-size: 32px; }
  .mb__toggle { padding-inline: var(--space-2); font-size: var(--text-xs); min-block-size: 32px; }
  .mb__form { grid-template-columns: 1fr; }
  .mb__form-media { position: static; }
  .mb__orow { grid-template-columns: 56px 1fr auto; }
  .mb__orow > .mb__input:nth-of-type(2), .mb__oprice { grid-column: 2 / -1; }
  .mb__srow { grid-template-columns: 1fr auto auto auto; }
  .mb__srow > .mb__input:nth-of-type(2) { grid-column: 1 / -1; grid-row: 2; }
}
</style>
