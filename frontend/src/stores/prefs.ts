import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { i18n, saveLang, type Lang } from '@/i18n'

export type Theme = 'auto' | 'light' | 'dark'
const THEME_KEY = 'lmesh-theme'
const TOKEN_KEY = 'lmesh-token'

function read(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
function write(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* 忽略 */ }
}

const media = window.matchMedia('(prefers-color-scheme: dark)')

/** 语言、主题、API 令牌：保存在浏览器本地。 */
export const usePrefs = defineStore('prefs', () => {
  const lang = ref<Lang>(i18n.global.locale.value as Lang)
  const theme = ref<Theme>(read(THEME_KEY, 'auto') as Theme)
  const token = ref<string>(read(TOKEN_KEY, ''))

  function applyTheme(): void {
    const dark = theme.value === 'dark' || (theme.value === 'auto' && media.matches)
    // 设计系统按 data-theme（实际生效的明 / 暗）取色；Element Plus 按 .dark 类
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    document.documentElement.setAttribute('data-theme-pref', theme.value)
  }
  media.addEventListener('change', applyTheme)
  watch(theme, (t) => { write(THEME_KEY, t); applyTheme() }, { immediate: true })
  watch(lang, (l) => { i18n.global.locale.value = l; saveLang(l) }, { immediate: true })
  watch(token, (t) => write(TOKEN_KEY, t))
  return { lang, theme, token }
})
