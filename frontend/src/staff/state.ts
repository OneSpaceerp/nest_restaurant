import { createTill, type Till } from '@shared/till/till'

let till: Till | null = null

export function useTill(): Till {
  if (!till) till = createTill('nest_restaurant', (window.nest_boot as { site_name?: string } | undefined)?.site_name ?? location.hostname)
  return till
}

export const SVC = (m: string) => `nest_restaurant.api.service.${m}`

export interface MenuOption { code: string; name: string; sold_out: boolean; price: number | null }
export interface MenuGroup { group: string; min: number; max: number; options: MenuOption[] }
export interface MenuItem { item_code: string; name: string; name_ar?: string | null; description?: string | null; allergens: string[]; dietary: string[]; image?: string | null; price: number; sold_out: boolean; course?: number; options: MenuGroup[] }
export interface Menu { currency: string; sections: { name: string; items: MenuItem[] }[] }

export interface OrderLine {
  line_id: string
  item_code: string
  item_name: string
  qty: number
  sent_qty: number
  paid_qty: number
  rate_preview: number
  course: number
  seat: number | null
  held: number
  note: string | null
  modifiers: { code: string; name: string }[]
  source: string
  void_reason: string | null
  progress: Record<string, number>
}
export interface Order {
  order: string
  version: number
  status: string
  service_type: string
  table: string | null
  table_label: string | null
  covers: number
  order_number: number
  subtotal_preview: number
  paid_amount: number
  waiter?: string
  visit_code?: string
  lines: OrderLine[]
  tickets?: { name: string; station: string; status: string; kind: string }[]
  invoices?: { invoice: string; amount: number; part: string }[]
}

/** The furthest production state any unit of a line has reached, in words for staff. */
export function lineStage(l: OrderLine): 'Not sent' | 'Sent' | 'Preparing' | 'Ready' | 'Served' | 'Voided' {
  if (l.void_reason && !l.qty) return 'Voided'
  if (l.sent_qty < l.qty) return 'Not sent'
  const p = l.progress
  if ((p.Served ?? 0) >= l.qty) return 'Served'
  if ((p.Ready ?? 0) + (p.Served ?? 0) >= l.qty) return 'Ready'
  if (p.Preparing) return 'Preparing'
  return 'Sent'
}
