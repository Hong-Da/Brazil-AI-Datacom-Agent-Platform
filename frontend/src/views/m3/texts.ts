/**
 * 后端结果中的文案键（translate.warn.*、translate.unsupported.*、template.finding.*、template.value.* 等）按当前语言渲染。
 * 三语文案取自后端 src/lmesh/locales（backend-texts.json 由脚本从那里抽出），与 CLI 的说法一致；
 * 没有登记的键原样显示键名。参数中的取值原样代入（列表用逗号连接）。
 */
import { pickLang } from '@/i18n'
import TEXTS from './backend-texts.json'

type LangMap = Record<string, string>
const T = TEXTS as Record<string, LangMap>

export function hasText(key: string): boolean {
  return key in T
}

export function show(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.map(show).join(', ')
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}=${show(x)}`).join(', ')
  return String(v)
}

/** 把 {param} 换成参数值；没有的参数原样保留。 */
export function fill(tpl: string, params: Record<string, unknown>): string {
  return tpl.replace(/\{(\w+)\}/g, (m, k: string) => (k in params && params[k] !== null && params[k] !== undefined ? show(params[k]) : m))
}

export function msg(key: string, params: Record<string, unknown> = {}, lang = 'zh-CN'): string {
  const m = T[key]
  return m ? fill(pickLang(m, lang) || m.en || key, params) : key
}
