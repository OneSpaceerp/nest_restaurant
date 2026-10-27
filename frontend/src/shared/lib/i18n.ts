// English/Arabic strings with genuine RTL, locale-aware numbers, dates and currency.
// Frappe's own translations (boot.__messages) are consulted first so site translators can override.

import { reactive } from 'vue'

type Dict = Record<string, string>

const state = reactive({ lang: 'en', dir: 'ltr' as 'ltr' | 'rtl', extra: {} as Dict })
const dictionaries: Record<string, Dict> = { en: {} }

export function registerLocale(lang: string, dict: Dict) {
  dictionaries[lang] = { ...(dictionaries[lang] ?? {}), ...dict }
}

export function setLanguage(lang: string, frappeMessages: Dict = {}) {
  state.lang = dictionaries[lang] ? lang : lang.split('-')[0] in dictionaries ? lang.split('-')[0] : 'en'
  state.dir = ['ar', 'he', 'fa', 'ur'].includes(state.lang) ? 'rtl' : 'ltr'
  state.extra = frappeMessages
}

export function lang() {
  return state.lang
}
export function dir() {
  return state.dir
}

/** Translate with {0}-style placeholders. English source strings are the keys. */
export function t(source: string, ...args: (string | number)[]): string {
  const raw = state.extra[source] ?? dictionaries[state.lang]?.[source] ?? source
  return args.reduce<string>((s, a, i) => s.replaceAll(`{${i}}`, String(a)), raw)
}

const numberCache = new Map<string, Intl.NumberFormat>()
function nf(key: string, make: () => Intl.NumberFormat) {
  if (!numberCache.has(key)) numberCache.set(key, make())
  return numberCache.get(key)!
}

/** Money with the currency's own minor units; Arabic UI uses Arabic-Indic digits only if the site asks. */
export function money(amount: number | string | null | undefined, currency = 'USD', opts: { digits?: 'latn' | 'arab' } = {}) {
  const value = Number(amount ?? 0)
  const locale = `${state.lang === 'ar' ? 'ar' : 'en'}-u-nu-${opts.digits ?? 'latn'}`
  try {
    return nf(`${locale}|${currency}`, () => new Intl.NumberFormat(locale, { style: 'currency', currency, currencyDisplay: 'narrowSymbol' })).format(value)
  } catch {
    return `${value.toFixed(2)} ${currency}`
  }
}

export function qty(n: number | string) {
  const v = Number(n)
  return nf(`q|${state.lang}`, () => new Intl.NumberFormat(state.lang === 'ar' ? 'ar-u-nu-latn' : 'en', { maximumFractionDigits: 3 })).format(v)
}

export function time(d: Date | string) {
  const date = typeof d === 'string' ? new Date(d.replace(' ', 'T')) : d
  return new Intl.DateTimeFormat(state.lang === 'ar' ? 'ar-u-nu-latn' : 'en', { hour: 'numeric', minute: '2-digit' }).format(date)
}

export function minutesAgo(mins: number) {
  if (mins < 1) return t('just now')
  return t('{0} min', Math.round(mins))
}
