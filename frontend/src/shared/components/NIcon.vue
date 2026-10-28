<script setup lang="ts">
// Original 24px stroke icons drawn for Nest (1.75 stroke, round caps). Directional icons flip in RTL.
const props = defineProps<{ name: string; size?: number; label?: string }>()
const DIRECTIONAL = new Set(['back', 'chevron', 'send'])
const P: Record<string, string> = {
  scan: 'M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M7 9v6M10 9v6M13 9v6M17 9v6',
  basket: 'M3.5 9h17l-1.6 9.2a2 2 0 0 1-2 1.8H7.1a2 2 0 0 1-2-1.8L3.5 9ZM8 9l3-5M16 9l-3-5M9.5 13v3M14.5 13v3',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  close: 'M6 6l12 12M18 6 6 18',
  search: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM20 20l-4.8-4.8',
  check: 'M5 12.5 10 17l9-10',
  offline: 'M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 4-2.5M12 20h.01M15.5 10.9A10 10 0 0 1 19 13M2 8.8a15 15 0 0 1 4.2-2.7M10.7 5.1A15 15 0 0 1 22 8.8',
  sync: 'M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4',
  back: 'M15 5l-7 7 7 7',
  chevron: 'M9 5l7 7-7 7',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4.5 20a7.5 7.5 0 0 1 15 0',
  camera: 'M4 8.5A2.5 2.5 0 0 1 6.5 6h1.8l1.5-2h4.4l1.5 2h1.8A2.5 2.5 0 0 1 20 8.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5v-8ZM12 16a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z',
  torch: 'M8 3h8l-1 5H9L8 3ZM9 8h6v3l-1 10h-4L9 11V8ZM12 13v2',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3',
  pause: 'M8 5v14M16 5v14',
  receipt: 'M6 3h12v18l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5L6 21V3ZM9 8h6M9 12h6M9 16h3',
  table: 'M4 9h16M6 9v10M18 9v10M8 5h8',
  bell: 'M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16ZM10 20.5a2.2 2.2 0 0 0 4 0',
  chef: 'M7 14a4 4 0 0 1-.6-7.9A5 5 0 0 1 12 3a5 5 0 0 1 5.6 3.1A4 4 0 0 1 17 14v6H7v-6ZM7 17h10',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2',
  cash: 'M3 7h18v10H3V7ZM12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM6 10v4M18 10v4',
  card: 'M3 6.5A1.5 1.5 0 0 1 4.5 5h15A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-11ZM3 10h18M7 15h4',
  lock: 'M6 11h12v9H6v-9ZM8.5 11V8a3.5 3.5 0 0 1 7 0v3',
  send: 'M4 12l16-8-6 16-2.5-6.5L4 12Z',
  register: 'M5 3h14v6H5V3ZM4 9h16l1 11H3L4 9ZM8 13h1M11.5 13h1M15 13h1M8 16.5h8',
  phone: 'M8 2.5h8A1.5 1.5 0 0 1 17.5 4v16a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20V4A1.5 1.5 0 0 1 8 2.5ZM11 18.5h2',
  inbox: 'M3.5 13.5 6 5h12l2.5 8.5V19a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-5.5ZM3.5 13.5H8l1.5 2.5h5l1.5-2.5h4.5',
  history: 'M4 12a8 8 0 1 0 2.4-5.7L4 8.5M4 4v4.5h4.5M12 8v4l3 2',
  calendar: 'M4 6.5A1.5 1.5 0 0 1 5.5 5h13A1.5 1.5 0 0 1 20 6.5v12a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-12ZM4 10h16M8 3v4M16 3v4',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3Z',
  logout: 'M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 8l4 4-4 4M19 12H9',
  undo: 'M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11',
  warning: 'M12 3.5 21.5 20h-19L12 3.5ZM12 10v4.5M12 17.5h.01',
  menu: 'M6 3.5h11a1.5 1.5 0 0 1 1.5 1.5v15l-3-1.6-3 1.6-3-1.6-3 1.6V5A1.5 1.5 0 0 1 6 3.5ZM8.5 8h6M8.5 11.5h6M8.5 15h3.5',
  image: 'M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6ZM4 16l4.5-4.5 4 4L15 13l5 5M15.5 9h.01',
  edit: 'M4 20h4L19 9a2.1 2.1 0 0 0-4-4L4 16v4ZM13.5 6.5l4 4',
  move: 'M12 3v18M3 12h18M12 3 9.5 5.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5',
  up: 'M12 19V5M6 11l6-6 6 6',
  down: 'M12 5v14M18 13l-6 6-6-6',
  layout: 'M4 5a1 1 0 0 1 1-1h5v7H4V5ZM14 4h5a1 1 0 0 1 1 1v4h-6V4ZM4 15h6v5H5a1 1 0 0 1-1-1v-4ZM14 13h6v6a1 1 0 0 1-1 1h-5v-7Z',
}
</script>

<template>
  <svg
    :width="props.size ?? 20"
    :height="props.size ?? 20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    :class="['n-icon', { 'n-icon--flip': DIRECTIONAL.has(props.name) }]"
    :role="props.label ? 'img' : undefined"
    :aria-label="props.label"
    :aria-hidden="props.label ? undefined : 'true'"
    focusable="false"
  >
    <path :d="P[props.name] ?? P.more" />
  </svg>
</template>

<style>
.n-icon { flex: none; display: block; }
[dir='rtl'] .n-icon--flip { transform: scaleX(-1); }
</style>
