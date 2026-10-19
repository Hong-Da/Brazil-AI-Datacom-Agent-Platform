/** Profile 条目默认值的输入方式与校验（M6-9）：随 Schema 节点的数据类型变化。 */
import { formatOk, isFormatType } from '../schema/typefields'
import { parseDefault } from './format'
import type { Entry, Scalar } from './types'

/** bool：三态分段按钮（不设置 / 开启 / 关闭）；enum：下拉；int：数字框；text：文本框（格式类型另做格式校验）。 */
export type DefaultKind = 'bool' | 'enum' | 'int' | 'text'

export type DefaultMeta = Pick<Entry, 'type' | 'choices' | 'range'>

export function defaultKind(m: DefaultMeta): DefaultKind {
  if (m.type === 'boolean' || m.type === 'flag') return 'bool'
  if (m.type === 'enum' && m.choices?.length) return 'enum'
  if (m.type === 'integer') return 'int'
  return 'text'
}

/** 默认值的问题（profiles.dErr.* 文案键）；空串表示合格。空值表示没有默认值，总是合格。 */
export function checkDefault(text: string, m: DefaultMeta): '' | 'int' | 'range' | 'choice' | 'bool' | 'format' {
  const s = text.trim()
  if (!s) return ''
  switch (defaultKind(m)) {
    case 'bool':
      return s === 'true' || s === 'false' ? '' : 'bool'
    case 'enum':
      return m.choices!.includes(s) ? '' : 'choice'
    case 'int': {
      if (!/^-?\d+$/.test(s)) return 'int'
      const r = m.range
      return r && r.length === 2 && (Number(s) < r[0]! || Number(s) > r[1]!) ? 'range' : ''
    }
    default:
      return isFormatType(m.type) && !formatOk(m.type, s) ? 'format' : ''
  }
}

/** 输入转成 YAML 标量：布尔 → true / false，整数 → 数字，枚举 → 文字；其余沿用原来的规则（保持原值的类型）。 */
export function parseTyped(text: string, m: DefaultMeta, previous?: Scalar): Scalar {
  const s = text.trim()
  if (s === '') return null
  switch (defaultKind(m)) {
    case 'bool':
      return s === 'true'
    case 'int':
      return /^-?\d+$/.test(s) ? Number(s) : s
    case 'enum':
      return s
    default:
      return parseDefault(s, previous)
  }
}
