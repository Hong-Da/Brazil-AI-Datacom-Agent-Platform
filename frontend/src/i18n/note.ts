/**
 * 知识库依赖 / 副作用说明（note）的取值：后端返回三语字典 {zh-CN, en, pt-BR}，
 * 旧数据或字段名、别名等可能仍是字符串。所有显示 note 的地方都用 noteText 按当前界面语言取值。
 */
import { pickLang } from './index'

const LANGS = ['zh-CN', 'en', 'pt-BR']

export type LangText = Record<string, string>
export type Note = LangText | string | null | undefined

/** 是否三语文本（键都是支持的语言；空对象也算，取值为空）。 */
export function isLangText(v: unknown): v is LangText {
  return !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).every((k) => LANGS.includes(k))
}

/** 按语言取说明：缺失时回退英文、中文；字符串原样返回；没有说明时为空串。 */
export function noteText(n: unknown, lang: string): string {
  if (n === null || n === undefined) return ''
  if (typeof n === 'string') return n
  return isLangText(n) ? pickLang(n, lang) : ''
}

/** 文案参数中的三语文本换成对应语言（例如检查发现参数里的 note）。 */
export function localizeParams(params: Record<string, unknown> | null | undefined, lang: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(params ?? {})) out[k] = isLangText(v) ? pickLang(v, lang) : v
  return out
}
