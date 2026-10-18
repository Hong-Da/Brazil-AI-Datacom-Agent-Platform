/** 对比结果的纯逻辑：编号拆分与显示、差异行模型、筛选、按功能域分组、计数、判定依据。 */
import type { CompareResult, DefaultOnly, Diff, SideVal } from './types'

/** 界面上的差异类型（changed 显示为 modified，与 m2.css 的 .dk 类一致；na = 只有一侧有默认值、不可比） */
export type RowType = 'added' | 'removed' | 'modified' | 'renamed' | 'na'
export const ROW_TYPES: RowType[] = ['added', 'removed', 'modified', 'renamed', 'na']
export const TYPE_SYM: Record<RowType, string> = { added: '+', removed: '−', modified: '~', renamed: '⇢', na: '≠' }

export interface Row {
  id: string
  type: RowType
  domain: string
  node: string
  diff: Diff | null
  dflt: DefaultOnly | null
  /** 规范编号是另一条差异的下级（例如改名对象里的内容差异） */
  child: boolean
}

/** 按 / 拆分编号，方括号里的 / 不拆（键里可能有接口名、原文行）。 */
export function splitPath(id: string): string[] {
  const out: string[] = []
  let depth = 0
  let cur = ''
  for (const ch of id) {
    if (ch === '[') depth++
    else if (ch === ']') depth = Math.max(0, depth - 1)
    if (ch === '/' && depth === 0) {
      out.push(cur)
      cur = ''
    } else cur += ch
  }
  if (cur || out.length) out.push(cur)
  return out
}

/** 一段编号的显示：interface[GE0/0/1] → interface GE0/0/1 */
export function prettySeg(seg: string): string {
  const i = seg.indexOf('[')
  if (i < 0 || !seg.endsWith(']')) return seg
  return `${seg.slice(0, i)} ${seg.slice(i + 1, -1)}`
}

/** 列表里的两行：o（主行）与 a（副行）。属性：主行是所属对象，副行是属性名；对象：主行是自身，副行是上级。 */
export function describe(node: string, nodeKind: string): { o: string; a: string } {
  const segs = splitPath(node)
  const last = segs[segs.length - 1] ?? node
  const parent = segs.slice(0, -1).map(prettySeg).join(' › ')
  if (nodeKind === 'attr') return { o: parent || prettySeg(last), a: parent ? prettySeg(last) : '' }
  return { o: prettySeg(last), a: parent }
}

/** 有效值的文字：对象值按键值拼接，列表用逗号。 */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.map(fmtValue).join(', ')
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}=${fmtValue(x)}`).join(' · ')
  return String(v)
}

export function buildRows(r: CompareResult): Row[] {
  const rows: Row[] = r.diffs.map((d, i) => ({
    id: `d${i}`,
    type: d.kind === 'changed' ? 'modified' : d.kind,
    domain: d.domain || 'raw',
    node: d.node,
    diff: d,
    dflt: null,
    child: false,
  }))
  const nodes = rows.map((x) => x.node)
  for (const row of rows) row.child = nodes.some((p) => p !== row.node && row.node.startsWith(p + '/'))
  r.default_only.forEach((d, i) => rows.push({ id: `n${i}`, type: 'na', domain: d.domain || 'raw', node: d.node, diff: null, dflt: d, child: false }))
  return rows
}

export interface SideShow { text: string; origin: string; lines: number[] }

/** 一侧的显示值；absent 表示这一侧没有。 */
export function sideOf(row: Row, side: 'a' | 'b'): SideShow {
  if (row.dflt) {
    if (row.dflt.side === side) return { text: fmtValue(row.dflt.value), origin: 'default', lines: [] }
    return { text: '', origin: 'absent', lines: [] }
  }
  const v: SideVal | null | undefined = row.diff?.[side]
  if (!v) return { text: '', origin: 'absent', lines: [] }
  return { text: fmtValue(v.value), origin: v.origin || 'explicit', lines: v.lines ?? [] }
}

export interface RowFilter {
  /** '' 表示全部差异类型；'na' 只看不可比项 */
  type: RowType | ''
  domain: string
  q: string
  /** 类型为全部时，是否展开不可比（default_only）项 */
  showNa: boolean
}

export function rowText(row: Row): string {
  const d = row.diff
  return [row.node, d?.a?.node ?? '', d?.b?.node ?? '', sideOf(row, 'a').text, sideOf(row, 'b').text, d?.from ?? '', d?.to ?? '', row.diff?.schema ?? row.dflt?.schema ?? ''].join(' ').toLowerCase()
}

export function filterRows(rows: Row[], f: RowFilter): Row[] {
  const q = f.q.trim().toLowerCase()
  return rows.filter((r) => {
    if (f.type) {
      if (r.type !== f.type) return false
    } else if (r.type === 'na' && !f.showNa) return false
    if (f.domain && r.domain !== f.domain) return false
    if (q && !rowText(r).includes(q)) return false
    return true
  })
}

export function countTypes(rows: Row[]): Record<RowType, number> {
  const c: Record<RowType, number> = { added: 0, removed: 0, modified: 0, renamed: 0, na: 0 }
  for (const r of rows) c[r.type]++
  return c
}

export interface Group { domain: string; rows: Row[]; counts: Record<RowType, number>; folded: number }

/** 按功能域分组，保持后端的顺序（功能域按知识库顺序、组内按编号）；folded 是该域被折叠的不可比项数。 */
export function groupRows(rows: Row[], allRows: Row[] = rows, showNa = true): Group[] {
  const order: string[] = []
  const m = new Map<string, Row[]>()
  for (const r of rows) {
    if (!m.has(r.domain)) {
      m.set(r.domain, [])
      order.push(r.domain)
    }
    m.get(r.domain)!.push(r)
  }
  const out = order.map((d) => ({ domain: d, rows: m.get(d)!, counts: countTypes(m.get(d)!), folded: 0 }))
  if (!showNa) {
    for (const g of out) g.folded = allRows.filter((r) => r.type === 'na' && r.domain === g.domain).length
  }
  return out
}

/** 结果里出现过的功能域（按出现顺序）。 */
export function domainsOf(rows: Row[]): string[] {
  return [...new Set(rows.map((r) => r.domain))]
}

export interface Why { key: string; params: Record<string, string | number> }

/** 判定依据：由结果字段推出的说明（文案键 + 参数），不是 AI 生成的。 */
export function explain(row: Row): Why {
  if (row.dflt) return { key: 'why.na', params: { side: row.dflt.side.toUpperCase(), other: row.dflt.side === 'a' ? 'B' : 'A', v: fmtValue(row.dflt.value) } }
  const d = row.diff!
  const a = sideOf(row, 'a')
  const b = sideOf(row, 'b')
  if (d.node_kind === 'raw') return { key: 'why.raw', params: {} }
  if (d.node_kind === 'ext') return { key: d.kind === 'changed' ? 'why.extChanged' : 'why.ext', params: {} }
  switch (d.kind) {
    case 'renamed':
      return { key: 'why.renamed', params: { from: d.from ?? a.text, to: d.to ?? b.text, sim: Math.round((d.similarity ?? 1) * 100), n: d.related.length } }
    case 'changed':
      if (a.origin === 'default' || b.origin === 'default') return { key: 'why.changedDefault', params: { a: a.text, b: b.text } }
      return { key: 'why.changed', params: { a: a.text, b: b.text } }
    case 'added':
      return d.node_kind === 'object' ? { key: 'why.addedObj', params: { n: d.count ?? 0 } } : { key: 'why.addedAttr', params: { v: b.text } }
    default:
      return d.node_kind === 'object' ? { key: 'why.removedObj', params: { n: d.count ?? 0 } } : { key: 'why.removedAttr', params: { v: a.text } }
  }
}

/** 原文行高亮的样式类（m2.css 的 .code .l.d-*）。 */
export function lineClass(type: RowType, side: 'a' | 'b'): string {
  if (type === 'renamed') return 'd-ren'
  if (type === 'modified') return 'd-mod'
  if (type === 'na') return 'd-eq'
  return side === 'a' ? 'd-del' : 'd-add'
}

/** 选中项的上一项 / 下一项（键盘上下移动）。 */
export function stepRow(rows: Row[], sel: string | null, delta: number): string | null {
  if (!rows.length) return null
  const i = rows.findIndex((r) => r.id === sel)
  if (i < 0) return rows[0].id
  return rows[Math.min(rows.length - 1, Math.max(0, i + delta))].id
}
