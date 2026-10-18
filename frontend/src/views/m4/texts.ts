/**
 * M4 页面里后端结果的文案键（change.dep.*、migrate.step.*、translate.warn.*、consistency 的 xd.*、baseline.* 等）按当前语言渲染。
 * 固定的键取自后端 src/lmesh/locales（backend-texts.json 由脚本从那里抽出，再并上 M3 的一份）；
 * 规则文件里的文案（一致性规则、基线规则）随结果一起返回（texts），调用时作为 extra 传入。没有登记的键原样显示键名。
 */
import { pickLang } from '@/i18n'
import { localizeParams } from '@/i18n/note'
import { fill } from '@/views/m3/texts'
import M3 from '@/views/m3/backend-texts.json'
import M4 from './backend-texts.json'

export type LangMap = Record<string, string>
export type Texts = Record<string, LangMap>

const T: Texts = { ...(M3 as Texts), ...(M4 as Texts) }

export function hasText(key: string, extra?: Texts): boolean {
  return key in T || !!(extra && key in extra)
}

export function msg(key: string, params: Record<string, unknown> = {}, lang = 'zh-CN', extra?: Texts): string {
  const m = extra?.[key] ?? T[key]
  return m ? fill(pickLang(m, lang) || m.en || key, localizeParams(params, lang)) : key
}

/** {key, params} 形式的文案（检查发现的 message / suggestion）。 */
export function keyText(v: { key: string; params?: Record<string, unknown> } | null | undefined, lang: string, extra?: Texts): string {
  return v ? msg(v.key, v.params ?? {}, lang, extra) : ''
}
