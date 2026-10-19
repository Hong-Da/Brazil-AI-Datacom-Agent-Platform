/**
 * 结构化脚本的数据整理（纯函数）：行的父子关系与折叠、按功能域筛选、隐藏默认值行的插入、按字符区间切分着色片段、
 * 虚拟滚动的可见窗口。大配置（现网约 2300 行）只渲染窗口内的行。
 */
import type { DefaultLine, ScriptData, ScriptLine } from './types'

export interface ScriptIndex {
  byNo: Map<number, ScriptLine>
  kids: Map<number, number[]>
  /** 目标节点 → 引用它的行 */
  refs: Map<string, number[]>
  /** 行号 → 插在它后面的默认值行 */
  defaultsAfter: Map<number, DefaultLine[]>
  /** 默认值节点 → 默认值行 */
  defaultByNode: Map<string, DefaultLine>
}

export function indexScript(s: ScriptData): ScriptIndex {
  const byNo = new Map<number, ScriptLine>()
  const kids = new Map<number, number[]>()
  for (const l of s.lines) {
    byNo.set(l.no, l)
    if (l.parent) {
      const arr = kids.get(l.parent) ?? []
      arr.push(l.no)
      kids.set(l.parent, arr)
    }
  }
  const defaultsAfter = new Map<number, DefaultLine[]>()
  const defaultByNode = new Map<string, DefaultLine>()
  for (const d of s.defaults) {
    defaultByNode.set(d.node, d)
    if (d.after === null) continue
    const arr = defaultsAfter.get(d.after) ?? []
    arr.push(d)
    defaultsAfter.set(d.after, arr)
  }
  return { byNo, kids, refs: new Map(Object.entries(s.refs)), defaultsAfter, defaultByNode }
}

export type Row = { type: 'line'; no: number } | { type: 'def'; d: DefaultLine }

export interface RowOptions {
  /** 折叠的行（视图块的进入行） */
  fold: Set<number>
  /** 只看一个功能域（'' 为全部）：保留该功能域的行及其所在块的上级行 */
  domain: string
  showDefaults: boolean
}

/** 某行是否被折叠的祖先挡住。 */
export function hiddenByFold(ix: ScriptIndex, no: number, fold: Set<number>): boolean {
  let p = ix.byNo.get(no)?.parent ?? null
  let hops = 0
  while (p && hops++ < 64) {
    if (fold.has(p)) return true
    p = ix.byNo.get(p)?.parent ?? null
  }
  return false
}

/** 按功能域筛选时保留的行：该功能域的行与它们的上级行。 */
export function domainKeep(s: ScriptData, ix: ScriptIndex, domain: string): Set<number> | null {
  if (!domain) return null
  const keep = new Set<number>()
  for (const l of s.lines) {
    if (l.domain !== domain) continue
    let c: number | null = l.no
    let hops = 0
    while (c && !keep.has(c) && hops++ < 64) {
      keep.add(c)
      c = ix.byNo.get(c)?.parent ?? null
    }
  }
  return keep
}

/** 可见的行（含插入的默认值行），按显示顺序。 */
export function visibleRows(s: ScriptData, ix: ScriptIndex, o: RowOptions): Row[] {
  const keep = domainKeep(s, ix, o.domain)
  const out: Row[] = []
  for (const l of s.lines) {
    if (keep && !keep.has(l.no)) continue
    if (o.fold.size && hiddenByFold(ix, l.no, o.fold)) continue
    out.push({ type: 'line', no: l.no })
    if (o.showDefaults && !o.fold.has(l.no)) for (const d of ix.defaultsAfter.get(l.no) ?? []) out.push({ type: 'def', d })
  }
  return out
}

/** 后代行数（折叠后显示“… N”）。 */
export function descendantCount(ix: ScriptIndex, no: number): number {
  let n = 0
  const stack = [...(ix.kids.get(no) ?? [])]
  while (stack.length) {
    const c = stack.pop()!
    n++
    stack.push(...(ix.kids.get(c) ?? []))
  }
  return n
}

/** 全部折叠：顶层有子行的块。 */
export function foldAll(ix: ScriptIndex): Set<number> {
  const out = new Set<number>()
  for (const [no] of ix.kids) if (!ix.byNo.get(no)?.parent) out.add(no)
  return out
}

/** 展开某行的全部上级，使它可见。 */
export function revealLine(ix: ScriptIndex, no: number, fold: Set<number>): Set<number> {
  const out = new Set(fold)
  let p = ix.byNo.get(no)?.parent ?? null
  let hops = 0
  while (p && hops++ < 64) {
    out.delete(p)
    p = ix.byNo.get(p)?.parent ?? null
  }
  return out
}

export interface Segment {
  text: string
  cls: '' | 'kw' | 'pa' | 'rf'
  ref?: string
}

/** 按字符区间把一行切成着色片段（区间外的空白与文字原样保留）。 */
export function segments(l: ScriptLine): Segment[] {
  const out: Segment[] = []
  let pos = 0
  const spans = [...(l.spans ?? [])].sort((a, b) => a.s - b.s)
  for (const s of spans) {
    if (s.s < pos || s.e > l.text.length) continue
    if (s.s > pos) out.push({ text: l.text.slice(pos, s.s), cls: '' })
    const cls = s.t === 'kw' ? 'kw' : s.t === 'param' ? 'pa' : 'rf'
    out.push({ text: l.text.slice(s.s, s.e), cls, ref: s.t === 'ref' ? s.ref?.[0] : undefined })
    pos = s.e
  }
  if (pos < l.text.length) out.push({ text: l.text.slice(pos), cls: '' })
  return out
}

/** 虚拟滚动的窗口：[开始, 结束) 行下标（上下各多渲染 overscan 行）。 */
export function windowOf(scrollTop: number, height: number, rowH: number, total: number, overscan = 20): [number, number] {
  const start = Math.max(0, Math.floor(scrollTop / rowH) - overscan)
  const end = Math.min(total, Math.ceil((scrollTop + height) / rowH) + overscan)
  return [start, Math.max(start, end)]
}

/** 行在可见行中的下标（默认值行按节点找）；找不到时 -1。 */
export function rowIndex(rows: Row[], target: { line?: number; node?: string }): number {
  return rows.findIndex((r) => (r.type === 'line' ? target.line !== undefined && r.no === target.line : target.node !== undefined && r.d.node === target.node))
}
