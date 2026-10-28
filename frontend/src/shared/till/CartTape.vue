<script setup lang="ts">
// The cart as a receipt tape: perforated top edge, lines in print order, the amount due on a yellow
// plate at the foot with the Pay action directly beneath it (Fitts: biggest, closest target).
import { computed } from 'vue'
import NButton from '../components/NButton.vue'
import NIcon from '../components/NIcon.vue'
import NQty from '../components/NQty.vue'
import NState from '../components/NState.vue'
import { money, t } from '../lib/i18n'
import type { Till } from './till'

// `sheet`: shown inside a phone bottom sheet that already carries the title, so no heading or frame
const props = defineProps<{ till: Till; title?: string; sheet?: boolean }>()
const emit = defineEmits<{ pay: []; hold: []; customer: []; held: [] }>()
const tl = props.till
const currency = computed(() => tl.register.value?.currency ?? 'USD')
const due = computed(() => (tl.quote.value && tl.quoteState.value === 'fresh' ? tl.quote.value.amount_due : Number(tl.preview.value.total)))
const authoritative = computed(() => tl.quoteState.value === 'fresh')
</script>

<template>
  <aside :class="['tape', { 'tape--sheet': sheet }]" :aria-label="title ?? t('Current sale')">
    <div class="tape__paper">
      <header class="tape__head">
        <h2 v-if="!sheet">{{ title ?? t('Current sale') }}</h2>
        <span class="tape__head-tools">
          <button type="button" class="tape__customer" @click="emit('customer')">
            <NIcon name="user" :size="16" /><span class="tape__cname">{{ tl.cart.customerName ?? tl.cart.customer ?? t('Walk-in customer') }}</span>
          </button>
          <button type="button" class="tape__held" :aria-label="t('Held sales')" :title="t('Held sales')" @click="emit('held')"><NIcon name="history" :size="18" /></button>
        </span>
      </header>
      <ol v-if="tl.cart.lines.length" class="tape__lines scroll" role="list">
        <li v-for="l in tl.cart.lines" :key="l.line_id" class="tape__line">
          <div class="tape__line-main">
            <span class="tape__name">{{ l.item_name }}</span>
            <span class="tape__amount num">{{ money((l.qty * Number(l.rate_override ?? l.rate ?? 0)), currency) }}</span>
          </div>
          <div class="tape__line-sub">
            <NQty :model-value="l.qty" :label="t('Quantity of {0}', l.item_name)" :fractional="!Number.isInteger(l.qty)" @update:model-value="(v: number) => tl.setQty(l.line_id, v)" />
            <span class="tape__rate muted num">× {{ l.rate === null ? '—' : money(Number(l.rate_override ?? l.rate), currency) }}</span>
            <button type="button" class="tape__remove" :aria-label="t('Remove {0}', l.item_name)" @click="tl.setQty(l.line_id, 0)"><NIcon name="trash" :size="18" /></button>
          </div>
          <div v-if="tl.preview.value.lineDiscounts[l.line_id] || l.serial_nos?.length" class="tape__line-extra">
            <span v-if="tl.preview.value.lineDiscounts[l.line_id]" class="tape__promo num">− {{ money(tl.preview.value.lineDiscounts[l.line_id], currency) }}</span>
            <span v-if="l.serial_nos?.length" class="tape__tag code">{{ l.serial_nos.join(', ') }}</span>
          </div>
        </li>
      </ol>
      <NState v-else kind="empty" icon="scan" :title="t('Nothing in this sale yet')" :detail="t('Scan a product or tap one from the catalog.')" />
      <dl v-if="tl.cart.lines.length" class="tape__sums">
        <div><dt>{{ t('Subtotal') }}</dt><dd class="num">{{ money(authoritative ? tl.quote.value!.net_total : tl.preview.value.gross, currency) }}</dd></div>
        <div v-if="Number(tl.preview.value.discount) || (authoritative && tl.quote.value!.discount_amount)"><dt>{{ t('Discount') }}</dt><dd class="num">− {{ money(authoritative ? tl.quote.value!.discount_amount : tl.preview.value.discount, currency) }}</dd></div>
        <div v-if="authoritative"><dt>{{ t('Tax') }}</dt><dd class="num">{{ money(tl.quote.value!.total_taxes_and_charges, currency) }}</dd></div>
      </dl>
    </div>
    <div class="tape__foot">
      <div class="tape__due" :aria-live="'polite'">
        <span class="tape__due-label">{{ t('Amount due') }}</span>
        <span class="tape__due-value num">{{ money(due, currency) }}</span>
        <span class="tape__due-note">
          <template v-if="tl.quoteState.value === 'loading'">{{ t('Checking prices…') }}</template>
          <template v-else-if="tl.quoteState.value === 'stale'">{{ t('Estimate — taxes are confirmed when online') }}</template>
          <template v-else-if="tl.quoteState.value === 'error'">{{ tl.quoteError.value }}</template>
          <template v-else-if="authoritative">{{ t('Includes tax') }}</template>
        </span>
      </div>
      <div class="tape__actions">
        <NButton variant="ghost" icon="pause" :disabled="!tl.cart.lines.length" @click="emit('hold')">{{ t('Hold') }}</NButton>
        <NButton variant="ghost" icon="trash" :disabled="!tl.cart.lines.length" @click="tl.clearCart()">{{ t('Clear') }}</NButton>
        <NButton variant="primary" size="lg" class="tape__pay" :disabled="!tl.cart.lines.length || tl.quoteState.value === 'error' || tl.quoteState.value === 'loading'" @click="emit('pay')">
          {{ t('Pay {0}', money(due, currency)) }}
        </NButton>
      </div>
    </div>
  </aside>
</template>

<style>
.tape { display: flex; flex-direction: column; min-block-size: 0; inline-size: var(--tape-width); flex: none; background: var(--surface-page); padding: var(--space-4); padding-inline-start: 0; gap: var(--space-3); }
.tape__paper {
  flex: 1; min-block-size: 0; display: flex; flex-direction: column; background: var(--surface-tape); box-shadow: var(--shadow-raised);
  border-radius: 0 0 var(--radius-md) var(--radius-md);
  /* perforated top edge: the receipt tearing off the printer */
  -webkit-mask: radial-gradient(circle 6px at 12px 0, #0000 98%, #000) -6px 0 / 24px 100% repeat-x;
  mask: radial-gradient(circle 6px at 12px 0, #0000 98%, #000) -6px 0 / 24px 100% repeat-x;
  padding-block-start: var(--space-3);
}
.tape__head { padding: var(--space-3) var(--space-4); display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); flex-wrap: wrap; border-block-end: 1px dashed var(--border-strong); }
.tape__head-tools { display: flex; gap: var(--space-1); align-items: center; min-inline-size: 0; }
.tape__held { inline-size: 36px; block-size: 36px; border: 0; border-radius: 50%; background: var(--surface-sunken); color: var(--text-body); display: grid; place-items: center; cursor: pointer; flex: none; }
.tape__customer { display: inline-flex; align-items: center; gap: 6px; border: 0; background: var(--surface-sunken); border-radius: var(--radius-pill); min-block-size: 36px; padding-inline: var(--space-3); cursor: pointer; color: var(--text-body); max-inline-size: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tape__lines { list-style: none; margin: 0; padding: 0 var(--space-4); flex: 1; min-block-size: 0; }
.tape__line { padding-block: var(--space-3); border-block-end: 1px dashed var(--border-subtle); }
.tape__line-main { display: flex; justify-content: space-between; gap: var(--space-3); align-items: baseline; }
.tape__name { font-weight: 600; color: var(--text-strong); overflow-wrap: anywhere; }
.tape__amount { font-weight: 600; color: var(--text-strong); white-space: nowrap; }
/* stepper · unit price · remove stay on one row; the price gives way first */
.tape__line-sub { display: flex; align-items: center; gap: var(--space-2); margin-block-start: var(--space-2); }
.tape__rate { flex: 1; min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-sm); }
.tape__line-extra { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-block-start: var(--space-2); }
.tape__promo { color: var(--ok-fg); font-weight: 600; font-size: var(--text-sm); }
.tape__tag { font-size: var(--text-xs); background: var(--surface-sunken); padding: 2px 6px; border-radius: var(--radius-sm); }
.tape__remove { margin-inline-start: auto; inline-size: var(--touch); block-size: var(--touch); border: 0; background: transparent; color: var(--text-muted); border-radius: var(--radius-md); display: grid; place-items: center; cursor: pointer; }
.tape__remove:hover { background: var(--danger-bg); color: var(--danger-fg); }
.tape__sums { margin: 0; padding: var(--space-3) var(--space-4); border-block-start: 1px dashed var(--border-strong); display: grid; gap: var(--space-1); }
.tape__sums div { display: flex; justify-content: space-between; }
.tape__sums dt { color: var(--text-muted); }
.tape__sums dd { margin: 0; font-weight: 600; color: var(--text-strong); }
.tape__foot { display: grid; gap: var(--space-3); }
.tape__due { background: var(--brand-fill); color: var(--brand-on-fill); border-radius: var(--radius-lg); padding: var(--space-3) var(--space-4); display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 0 var(--space-3); }
.tape__due-label { font-weight: 600; }
.tape__due-value { font-size: var(--text-due); font-weight: 700; line-height: 1.1; letter-spacing: -0.01em; }
.tape__due-note { grid-column: 1 / -1; font-size: var(--text-sm); opacity: 0.85; min-block-size: 1.3em; }
.tape__actions { display: grid; grid-template-columns: auto auto 1fr; gap: var(--space-2); }
.tape__pay { inline-size: 100%; }
@media (max-width: 1023px) { .tape { inline-size: 100%; padding: var(--space-3); } }
/* inside the phone sheet: no outer frame, the sheet's title replaces the heading */
.tape--sheet { padding: 0; background: transparent; inline-size: 100%; }
.tape--sheet .tape__paper { padding-block-start: 0; box-shadow: none; background: transparent; -webkit-mask: none; mask: none; }
.tape--sheet .tape__head, .tape--sheet .tape__lines, .tape--sheet .tape__sums { padding-inline: 0; }
.tape--sheet .tape__head { justify-content: flex-start; padding-block-start: var(--space-2); }
.tape--sheet .tape__head-tools { flex: 1; }
.tape--sheet .tape__customer { flex: 1; justify-content: flex-start; }
/* phones: the amount scales to fit, Pay takes the full row above Hold / Clear */
@media (max-width: 640px) {
  .tape__due { grid-template-columns: 1fr; }
  .tape__due-value { font-size: clamp(1.75rem, 9vw, var(--text-due)); overflow-wrap: anywhere; }
  .tape__actions { grid-template-columns: 1fr 1fr; }
  .tape__pay { grid-column: 1 / -1; order: -1; }
}
</style>
