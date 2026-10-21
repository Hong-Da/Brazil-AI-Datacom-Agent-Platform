import { defineStore } from 'pinia'
import { ref, watch, type Ref } from 'vue'
import { i18n, saveLang, type Lang } from '@/i18n'

export type Theme = 'auto' | 'light' | 'dark'
const THEME_KEY = 'lmesh-theme'
const STYLE_KEY = 'lmesh-term-style'
const ICONS_KEY = 'lmesh-icon-set'
const ASK_INTRO_KEY = 'lmesh-ask-intro'
/** AI 查询页顶部接口信息与说明：展开 / 收起（REQ-051） */
export type AskIntro = 'open' | 'folded'
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

/** 语言、主题、显示风格、图标风格、AI 查询页说明的折叠：保存在浏览器本地；登录后另随账号保存（REQ-047，prefs-sync.ts）。 */
export const usePrefs = defineStore('prefs', () => {
  const lang = ref<Lang>(i18n.global.locale.value as Lang)
  const theme = ref<Theme>(read(THEME_KEY, 'auto') as Theme)
  /** 显示风格（huawei / cisco / nokia）；空表示还没选过，跟随系统默认（/kb/terms 的 default） */
  const termStyle = ref<string>(read(STYLE_KEY, ''))
  /** 设备图标风格（个人偏好，保存在浏览器本地；默认 B 几何徽章） */
  const iconSet = ref<IconSetPref>(((s) => (ICON_SETS.includes(s as IconSetPref) ? s : 'geo'))(read(ICONS_KEY, 'geo')) as IconSetPref)

  const askIntro = ref<AskIntro>(read(ASK_INTRO_KEY, 'open') === 'folded' ? 'folded' : 'open')

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
  watch(askIntro, (s) => write(ASK_INTRO_KEY, s))
  /** 随账号保存的状态（REQ-047，见 prefs-sync.ts）：local 只存本地 / saving 正在写入账号 / saved 已保存到账号 / error 写入失败 */
  const syncState = ref<'local' | 'saving' | 'saved' | 'error'>('local')
  return { lang, theme, termStyle, iconSet, askIntro, syncState }
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
