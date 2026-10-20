import { defineStore } from 'pinia'
import { ref, watch, type Ref } from 'vue'
import { i18n, saveLang, type Lang } from '@/i18n'

export type Theme = 'auto' | 'light' | 'dark'
const THEME_KEY = 'lmesh-theme'
const STYLE_KEY = 'lmesh-term-style'
const ICONS_KEY = 'lmesh-icon-set'
/** 设备图标风格（REQ-042）：A 圆柱 cyl、B 几何徽章 geo（默认）、C 线框 line */
export type IconSetPref = 'cyl' | 'geo' | 'line'
const ICON_SETS: IconSetPref[] = ['cyl', 'geo', 'line']

function read(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
function write(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* 忽略 */ }
}

const media = window.matchMedia('(prefers-color-scheme: dark)')

/** 语言、主题、显示风格：保存在浏览器本地（登录状态在会话 Cookie 里，不在这里）。 */
export const usePrefs = defineStore('prefs', () => {
  const lang = ref<Lang>(i18n.global.locale.value as Lang)
  const theme = ref<Theme>(read(THEME_KEY, 'auto') as Theme)
  /** 显示风格（huawei / cisco / nokia）；空表示还没选过，跟随系统默认（/kb/terms 的 default） */
  const termStyle = ref<string>(read(STYLE_KEY, ''))
  /** 设备图标风格（个人偏好，保存在浏览器本地；默认 B 几何徽章） */
  const iconSet = ref<IconSetPref>(((s) => (ICON_SETS.includes(s as IconSetPref) ? s : 'geo'))(read(ICONS_KEY, 'geo')) as IconSetPref)

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
  watch(termStyle, (s) => write(STYLE_KEY, s))
  watch(iconSet, (s) => write(ICONS_KEY, s))
  return { lang, theme, termStyle, iconSet }
})

/** 每个浏览器记住的开关（例如各视图的“显示默认配置”），name 是视图名。 */
export function rememberedFlag(name: string, fallback = false): Ref<boolean> {
  const key = `lmesh-flag-${name}`
  const v = ref(read(key, fallback ? '1' : '0') === '1')
  watch(v, (x) => write(key, x ? '1' : '0'))
  return v
}

/** 每个浏览器记住的选项（字符串）。 */
export function rememberedChoice<T extends string>(name: string, fallback: T): Ref<T> {
  const key = `lmesh-choice-${name}`
  const v = ref(read(key, fallback)) as Ref<T>
  watch(v, (x) => write(key, x))
  return v
}
