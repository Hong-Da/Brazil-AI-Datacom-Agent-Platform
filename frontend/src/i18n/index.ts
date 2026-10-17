import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN.json'
import en from './en.json'
import ptBR from './pt-BR.json'

export const LANGS = [
  { code: 'zh-CN', label: '中文' },
  { code: 'en', label: 'English' },
  { code: 'pt-BR', label: 'Português (Brasil)' },
] as const
export type Lang = (typeof LANGS)[number]['code']
const KEY = 'lmesh-lang'

/** 首次打开跟随浏览器语言（zh / en / pt），无法匹配时用中文；手动切换后以保存值为准。 */
export function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved && LANGS.some((l) => l.code === saved)) return saved as Lang
  } catch { /* 浏览器存储不可用时忽略 */ }
  for (const tag of navigator.languages ?? [navigator.language]) {
    const low = (tag || '').toLowerCase()
    if (low.startsWith('zh')) return 'zh-CN'
    if (low.startsWith('en')) return 'en'
    if (low.startsWith('pt')) return 'pt-BR'
  }
  return 'zh-CN'
}

export function saveLang(lang: Lang): void {
  try { localStorage.setItem(KEY, lang) } catch { /* 忽略 */ }
  document.documentElement.lang = lang
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLang(),
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN, en, 'pt-BR': ptBR },
  missingWarn: false,
  fallbackWarn: false,
})
