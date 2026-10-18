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

type Dict = Record<string, string>
type PageFile = Record<Lang, Dict>

/**
 * 页面文案：src/i18n/pages/<页面>.json，结构 {"zh-CN": {...}, "en": {...}, "pt-BR": {...}}，
 * 键自动加上页面名前缀，例如 pages/dashboard.json 的 "title" → t('dashboard.title')。
 */
const pageFiles = import.meta.glob<PageFile>('./pages/*.json', { eager: true, import: 'default' })

export function pageMessages(): Record<Lang, Dict> {
  const out: Record<Lang, Dict> = { 'zh-CN': {}, en: {}, 'pt-BR': {} }
  for (const [path, file] of Object.entries(pageFiles)) {
    const name = path.replace(/^.*\/(.+)\.json$/, '$1')
    for (const lang of Object.keys(out) as Lang[]) {
      for (const [k, v] of Object.entries(file[lang] ?? {})) out[lang][`${name}.${k}`] = v
    }
  }
  return out
}

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

const pages = pageMessages()

export const i18n = createI18n({
  legacy: false,
  locale: initialLang(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': { ...zhCN, ...pages['zh-CN'] },
    en: { ...en, ...pages.en },
    'pt-BR': { ...ptBR, ...pages['pt-BR'] },
  },
  missingWarn: false,
  fallbackWarn: false,
})

/** 按当前语言取 Schema 等多语言字段（{zh-CN, en, pt-BR}），缺失时依次回退到英文、中文。 */
export function pickLang(m: Record<string, string> | null | undefined, lang: string): string {
  if (!m) return ''
  return m[lang] || m.en || m['zh-CN'] || Object.values(m)[0] || ''
}
