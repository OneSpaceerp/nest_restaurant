import '@shared/app/fonts'
import { createApp, h } from 'vue'
import { dismissSplash, startSurface } from '@shared/app/surface'
import BookingApp from './BookingApp.vue'
import GuestApp from './GuestApp.vue'

const root = document.getElementById('app')!
startSurface({ app: 'nest_rest_guest', surface: 'customer', root, swUrl: '/nest-restaurant/customer/sw.js', scope: '/nest-restaurant/customer/' })
const isBooking = location.pathname.startsWith('/nest-restaurant/customer/book')
createApp({ render: () => h(isBooking ? BookingApp : GuestApp, { root }) }).mount(root)
dismissSplash()
