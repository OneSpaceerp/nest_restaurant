import { createMemoryHistory, createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/floor' },
  { path: '/floor', name: 'floor', component: () => import('./views/FloorView.vue') },
  { path: '/order/:name', name: 'order', component: () => import('./views/OrderView.vue'), props: true },
  { path: '/kitchen/:station?', name: 'kitchen', component: () => import('./views/KitchenView.vue'), props: true, meta: { bare: true } },
  { path: '/counter', name: 'counter', component: () => import('./views/CounterView.vue'), meta: { shift: true } },
  { path: '/menu', name: 'menu', component: () => import('./views/MenuBuilderView.vue') },
  { path: '/bookings', name: 'bookings', component: () => import('./views/BookingsView.vue') },
  { path: '/shift', name: 'shift', component: () => import('./views/ShiftPage.vue'), meta: { shift: true } },
  { path: '/sync', name: 'sync', component: () => import('./views/SyncPage.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/floor' },
]

export function makeRouter(mode: 'pwa' | 'desk') {
  return createRouter({ history: mode === 'pwa' ? createWebHistory('/nest-restaurant') : createMemoryHistory(), routes })
}
