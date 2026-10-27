// Start-up shared by every Nest surface (staff PWA, customer PWA, Desk mount).
// Fonts are imported by the standalone PWA entries only (./fonts); Desk keeps its own typeface.
import '../styles/tokens.css'
import '../styles/base.css'

import { reactive } from 'vue'
import ar from '../locales/ar'
import arMore from '../locales/ar-more'
import { dir, lang, registerLocale, setLanguage } from '../lib/i18n'
import { registerWorker } from '../lib/pwa'

export interface SurfaceBoot {
  site_name: string
  user: string
  lang: string
  route?: string
  socketio_port?: number
  __messages?: Record<string, string>
}

export const prefs = reactive({ theme: 'auto' as 'auto' | 'light' | 'dark', lang: 'en' })

function read(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}
function write(key: string, v: string) {
  try { localStorage.setItem(key, v) } catch { /* private mode */ }
}

export function startSurface(opts: { app: string; surface: string; root: HTMLElement; swUrl?: string; scope?: string; standalone?: boolean }) {
  const boot: SurfaceBoot = (window.nest_boot as unknown as SurfaceBoot) ?? { site_name: location.hostname, user: 'Guest', lang: navigator.language.slice(0, 2) }
  registerLocale('ar', { ...ar, ...arMore })
  prefs.lang = read(`${opts.app}:lang`) ?? boot.lang ?? 'en'
  prefs.theme = (read(`${opts.app}:theme`) as typeof prefs.theme) ?? 'auto'
  setLanguage(prefs.lang, boot.__messages ?? {})
  apply(opts.root, opts.standalone !== false)
  if (opts.swUrl && opts.scope && import.meta.env.PROD) void registerWorker(opts.swUrl, opts.scope).catch(() => undefined)
  return boot
}

function apply(root: HTMLElement, standalone: boolean) {
  root.classList.add('nest-root')
  if (standalone) root.classList.add('nest-standalone')
  root.dataset.theme = prefs.theme
  root.setAttribute('dir', dir())
  root.setAttribute('lang', lang())
  if (standalone) {
    document.documentElement.lang = lang()
    document.documentElement.dir = dir()
  }
}

export function toggleLanguage(app: string, root: HTMLElement) {
  prefs.lang = lang() === 'ar' ? 'en' : 'ar'
  write(`${app}:lang`, prefs.lang)
  setLanguage(prefs.lang)
  apply(root, root.classList.contains('nest-standalone'))
}

export function cycleTheme(app: string, root: HTMLElement) {
  prefs.theme = prefs.theme === 'auto' ? 'light' : prefs.theme === 'light' ? 'dark' : 'auto'
  write(`${app}:theme`, prefs.theme)
  root.dataset.theme = prefs.theme
}
