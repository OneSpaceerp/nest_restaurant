import { reactive } from 'vue'

export type ToastTone = 'ok' | 'danger' | 'warn' | 'info'
export interface Toast { id: number; tone: ToastTone; text: string; action?: { label: string; run: () => void } }

export const toasts = reactive<Toast[]>([])
let seq = 0

/** Success/info auto-dismiss; errors stay until dismissed (feedback-patterns guidance). */
export function toast(text: string, tone: ToastTone = 'ok', action?: Toast['action']) {
  const id = ++seq
  toasts.push({ id, tone, text, action })
  if (tone === 'ok' || tone === 'info') setTimeout(() => dismiss(id), action ? 6000 : 3500)
  return id
}

export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}
