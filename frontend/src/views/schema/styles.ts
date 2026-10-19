import { STYLES } from '@/terms/terms'

/** Schema 节点在各显示风格下的写法（REQ-026）：对象给命令模板与叫法，属性给命令关键字。 */

export interface TermsLike {
  template(schema: string, style: string): string | null
  name(schema: string, style: string): string
  attr(schema: string, style: string): string | null
}

export interface StyleRow {
  style: string
  /** 命令写法：对象是模板（如 ip vpn-instance {name}），属性是关键字 */
  form: string
  /** 对象的叫法；属性为空 */
  name: string
  current: boolean
}

/** 节点卡片用：每种风格一行，当前风格排在前面；没有登记写法的风格不列出。 */
export function styleRows(t: TermsLike, id: string, type: string, current: string, styles: readonly string[] = STYLES): StyleRow[] {
  const rows: StyleRow[] = []
  for (const s of styles) {
    const form = type === 'object' ? t.template(id, s) : t.attr(id, s)
    if (!form) continue
    rows.push({ style: s, form, name: type === 'object' ? t.name(id, s) : '', current: s === current })
  }
  return rows.sort((a, b) => Number(b.current) - Number(a.current))
}

/** 列表里规范编号旁的小字：当前风格的命令写法，没有登记时为空。 */
export function styleForm(t: TermsLike, id: string, type: string, style: string): string {
  return (type === 'object' ? t.template(id, style) : t.attr(id, style)) ?? ''
}
