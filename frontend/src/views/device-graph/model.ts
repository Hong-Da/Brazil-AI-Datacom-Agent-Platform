/**
 * 设备配置图的数据整理：把接口返回的扁平节点 / 边整理成树（按功能域：设备 → 功能域 → 对象 → 属性；
 * 按视图层级：设备 → 对象 → 子对象 → 属性，不插入功能域这一层），
 * 计算收起 / 展开后的可见部分、依赖边聚合到可见祖先、配置行与节点的对应关系。
 * 纯函数，不依赖 DOM，便于测试；大图（约 2500 节点）只渲染可见部分。
 */
import type { Note } from '@/i18n/note'
import type { ApiEdge, ApiNode, GraphData } from './types'

export type TKind = 'device' | 'domain' | 'object' | 'attr' | 'raw' | 'unknown' | 'ext' | 'rawgroup'

export interface TNode {
  id: string
  kind: TKind
  label: string
  value: string
  schema: string | null
  origin: string
  lines: number[]
  domain: string
  parent: string | null
  children: string[]
  depth: number
  /** 子树（不含自身）的节点数 */
  size: number
  /** 子树内有未识别行 */
  hasUnknown: boolean
  api?: ApiNode
}

export interface Model {
  root: string
  nodes: Map<string, TNode>
  /** 依赖边（不含 contains） */
  deps: ApiEdge[]
  /** 行号 → 最深的真实节点 */
  lineOwner: Map<number, string>
  rawLines: Set<number>
  unknownLines: number[]
  /** 出现的功能域（按 Schema 顺序，raw 最后） */
  domains: string[]
}

export const RAW_DOMAIN = 'raw'
export const DEP_KINDS = ['reference', 'prerequisite', 'side_effect', 'mutex'] as const
export const EDGE_KINDS = ['contains', ...DEP_KINDS] as const
/** 接口的边类型 → 样式用的短名（与设计系统 --e-ref 等变量一致） */
export const EDGE_SHORT: Record<string, string> = {
  contains: 'contains',
  reference: 'ref',
  prerequisite: 'pre',
  side_effect: 'side',
  mutex: 'mutex',
}

/** 把值整理成一行文字。 */
export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.map(formatValue).join(', ')
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${k}=${formatValue(x)}`)
      .join(', ')
  }
  return String(v)
}

function keyText(k: unknown): string {
  if (k === null || k === undefined) return ''
  if (typeof k === 'object' && !Array.isArray(k)) {
    return Object.values(k as Record<string, unknown>)
      .filter((x) => x !== null && x !== undefined && x !== '')
      .map(formatValue)
      .join(' ')
  }
  return formatValue(k)
}

function lastSeg(s: string): string {
  const i = s.lastIndexOf('.')
  return i >= 0 ? s.slice(i + 1) : s
}

/** id 最后一段（去掉 [...] 键），例如 interface[Lo0]/mtu → mtu。 */
function idLeaf(id: string): string {
  let depth = 0
  let start = 0
  for (let i = 0; i < id.length; i++) {
    const c = id[i]
    if (c === '[') depth++
    else if (c === ']') depth--
    else if (c === '/' && depth === 0) start = i + 1
  }
  return id.slice(start).replace(/\[.*$/, '')
}

/** 节点在图上的名字。 */
export function nodeLabel(n: ApiNode): string {
  switch (n.kind) {
    case 'device':
      return formatValue(n.value)
    case 'object': {
      const leaf = n.schema ? lastSeg(n.schema) : idLeaf(n.id)
      const k = keyText(n.key)
      return k ? `${leaf} ${k}` : leaf
    }
    case 'attr':
      return n.schema ? lastSeg(n.schema) : idLeaf(n.id)
    case 'ext':
      // ext:<厂商>.<命令卡>[.N|~N] → 命令卡名
      return n.schema ? n.schema.replace(/^ext:[^.]*\./, '').replace(/[.~]\d+$/, '') : idLeaf(n.id)
    default:
      return (n.text ?? '').trim() || n.id
  }
}

/** Schema 节点 id → 功能域。用 /kb/schema 的各域节点建表；Schema 前缀（如 rp.、static.）不一定等于功能域名。 */
export function domainResolver(domains: { domain: string; nodes: { id: string }[] }[]): (schema: string) => string | null {
  // 先按节点编号（及其上级编号）精确查找：interface.bfd 属于 bfd 域而 interface 属于 interface 域；查不到时按首段兜底（先登记的域优先）
  const exact = new Map<string, string>()
  const roots = new Map<string, string>()
  for (const d of domains) {
    for (const n of d.nodes) {
      exact.set(n.id, d.domain)
      const r = n.id.split('.')[0]
      if (!roots.has(r) || n.id === r) roots.set(r, d.domain)
    }
  }
  return (schema) => {
    if (!schema || schema.startsWith('ext:')) return null
    for (let s = schema; s; s = s.includes('.') ? s.slice(0, s.lastIndexOf('.')) : '') {
      const d = exact.get(s)
      if (d) return d
    }
    return roots.get(schema.split('.')[0]) ?? null
  }
}

function firstLine(n: TNode): number {
  return n.lines.length ? Math.min(...n.lines) : Number.MAX_SAFE_INTEGER
}

export interface BuildOptions {
  /** 功能域顺序（来自 Schema） */
  domainOrder?: string[]
  /** 把同一对象下的原文节点收进一个“raw ×N”组 */
  groupRaw?: boolean
  /** 在设备下插入功能域分组（默认 true）；false 时按视图层级（对象的父子关系）组织 */
  byDomain?: boolean
  /** 节点名（显示风格的命令写法）；返回 null 时用默认名 */
  labeler?: (n: ApiNode) => string | null | undefined
}

export function buildModel(data: GraphData, domainOf: (schema: string) => string | null, opts: BuildOptions = {}): Model {
  const nodes = new Map<string, TNode>()
  let root = 'device'
  for (const a of data.nodes) {
    const kind = (['device', 'object', 'attr', 'raw', 'unknown', 'ext'].includes(a.kind) ? a.kind : 'object') as TKind
    if (kind === 'device') root = a.id
    nodes.set(a.id, {
      id: a.id,
      kind,
      label: opts.labeler?.(a) || nodeLabel(a),
      value: kind === 'attr' || kind === 'ext' ? formatValue(a.value) : kind === 'raw' || kind === 'unknown' ? (a.text ?? '') : '',
      schema: a.schema,
      origin: a.origin || 'explicit',
      lines: [...(a.lines ?? [])].sort((x, y) => x - y),
      domain: '',
      parent: null,
      children: [],
      depth: 0,
      size: 0,
      hasUnknown: kind === 'unknown',
      api: a,
    })
  }
  if (!nodes.has(root)) {
    nodes.set(root, {
      id: root, kind: 'device', label: data.device ?? root, value: '', schema: null, origin: 'explicit',
      lines: [], domain: '', parent: null, children: [], depth: 0, size: 0, hasUnknown: false,
    })
  }
  const deps: ApiEdge[] = []
  for (const e of data.edges) {
    if (e.kind !== 'contains') {
      if (nodes.has(e.from) && nodes.has(e.to)) deps.push(e)
      continue
    }
    const c = nodes.get(e.to)
    if (c && nodes.has(e.from) && c.parent === null && e.to !== root) c.parent = e.from
  }
  // 父节点被筛掉的节点（例如按功能域取图时的原文行）挂到设备下
  for (const n of nodes.values()) if (n.id !== root && n.parent === null) n.parent = root

  // 功能域：按 Schema 判定，ext / raw / unknown 跟随父节点
  const resolve = (n: TNode, seen = 0): string => {
    if (n.domain) return n.domain
    if (n.id === root) return ''
    const own = n.schema ? domainOf(n.schema) : null
    if (own) return (n.domain = own)
    const p = n.parent ? nodes.get(n.parent) : undefined
    const d = p && p.id !== root && seen < 200 ? resolve(p, seen + 1) : ''
    return (n.domain = d || RAW_DOMAIN)
  }
  for (const n of nodes.values()) resolve(n)

  // 设备下插入功能域分组（按视图层级时只记下出现的功能域，供筛选）
  const byDomain = opts.byDomain !== false
  const present = new Set<string>()
  for (const n of nodes.values()) if (n.parent === root) present.add(n.domain)
  const order = opts.domainOrder ?? []
  const domains = [...present].sort((a, b) => {
    const ia = a === RAW_DOMAIN ? 1e6 : order.indexOf(a) < 0 ? 1e5 : order.indexOf(a)
    const ib = b === RAW_DOMAIN ? 1e6 : order.indexOf(b) < 0 ? 1e5 : order.indexOf(b)
    return ia - ib || a.localeCompare(b)
  })
  for (const d of byDomain ? domains : []) {
    nodes.set(`domain:${d}`, {
      id: `domain:${d}`, kind: 'domain', label: d, value: '', schema: null, origin: 'explicit',
      lines: [], domain: d, parent: root, children: [], depth: 1, size: 0, hasUnknown: false,
    })
  }
  if (byDomain) for (const n of nodes.values()) if (n.parent === root && n.kind !== 'domain') n.parent = `domain:${n.domain}`

  // 原文节点分组（在对象下；按功能域时顶层原文已由 raw 功能域收起，按视图层级时设备下的原文也收成一组）
  if (opts.groupRaw) {
    const byParent = new Map<string, TNode[]>()
    for (const n of nodes.values()) {
      if (n.kind !== 'raw' || !n.parent || n.parent.startsWith('domain:')) continue
      const arr = byParent.get(n.parent) ?? []
      arr.push(n)
      byParent.set(n.parent, arr)
    }
    for (const [pid, arr] of byParent) {
      const gid = `rawgroup:${pid}`
      const lines = arr.flatMap((n) => n.lines).sort((a, b) => a - b)
      nodes.set(gid, {
        id: gid, kind: 'rawgroup', label: `raw ×${arr.length}`, value: '', schema: null, origin: 'explicit',
        lines, domain: pid === root ? RAW_DOMAIN : nodes.get(pid)!.domain, parent: pid, children: [], depth: 0, size: 0, hasUnknown: false,
      })
      for (const n of arr) n.parent = gid
    }
  }

  // 子节点列表（按首行排序，没有行的默认节点排在后面）
  for (const n of nodes.values()) if (n.parent) nodes.get(n.parent)!.children.push(n.id)
  for (const n of nodes.values()) {
    if (n.children.length > 1) {
      n.children.sort((a, b) => {
        const na = nodes.get(a)!
        const nb = nodes.get(b)!
        if (na.kind === 'domain' && nb.kind === 'domain') return domains.indexOf(na.domain) - domains.indexOf(nb.domain)
        return firstLine(na) - firstLine(nb) || a.localeCompare(b)
      })
    }
  }
  // 深度、子树大小、子树内未识别
  const walk = (id: string, depth: number): void => {
    const n = nodes.get(id)!
    n.depth = depth
    let size = 0
    for (const c of n.children) {
      walk(c, depth + 1)
      const cn = nodes.get(c)!
      size += 1 + cn.size
      if (cn.hasUnknown) n.hasUnknown = true
    }
    n.size = size
  }
  walk(root, 0)

  // 行号 → 最深的真实节点（分组节点不参与）
  const lineOwner = new Map<number, string>()
  const rawLines = new Set<number>()
  const unknown = new Set<number>()
  for (const n of nodes.values()) {
    if (n.kind === 'rawgroup' || n.kind === 'domain') continue
    for (const l of n.lines) {
      const cur = lineOwner.get(l)
      if (!cur || nodes.get(cur)!.depth < n.depth) lineOwner.set(l, n.id)
      if (n.kind === 'raw') rawLines.add(l)
      if (n.kind === 'unknown') unknown.add(l)
    }
  }
  return { root, nodes, deps, lineOwner, rawLines, unknownLines: [...unknown].sort((a, b) => a - b), domains }
}

/** 祖先 id（从父节点到根）。 */
export function ancestors(m: Model, id: string): string[] {
  const out: string[] = []
  let n = m.nodes.get(id)
  while (n && n.parent) {
    out.push(n.parent)
    n = m.nodes.get(n.parent)
  }
  return out
}

export interface ViewOptions {
  expanded: Set<string>
  showDefault: boolean
  /** 只看一个功能域（'' 为全部） */
  domain: string
  /** 每个父节点最多显示的子节点数；超出部分收进“更多”节点 */
  limits?: Map<string, number>
  defaultLimit?: number
}

export interface VisNode {
  id: string
  /** 'more' 为“还有 N 个”占位节点 */
  more?: { parent: string; count: number }
  parent: string | null
  /** 有可展开的子节点 */
  expandable: boolean
  expanded: boolean
  /** 收起时隐藏的后代数 */
  hidden: number
}

export const MORE_PREFIX = 'more:'

function isShown(m: Model, n: TNode, o: ViewOptions): boolean {
  if (!o.showDefault && n.origin === 'default') return false
  // 只看一个功能域：设备下一层（功能域分组，或按视图层级时的顶层对象）按功能域筛选
  if (o.domain && n.parent === m.root && n.domain !== o.domain) return false
  return true
}

/** 可显示的子节点（已按显示规则过滤）。 */
export function shownChildren(m: Model, id: string, o: ViewOptions): string[] {
  const n = m.nodes.get(id)
  if (!n) return []
  return n.children.filter((c) => isShown(m, m.nodes.get(c)!, o))
}

/** 按展开状态算出要画的节点（树序）。 */
export function visibleTree(m: Model, o: ViewOptions): VisNode[] {
  const out: VisNode[] = []
  const limitOf = (id: string) => o.limits?.get(id) ?? o.defaultLimit ?? 120
  const visit = (id: string, parent: string | null): void => {
    const kids = shownChildren(m, id, o)
    const open = o.expanded.has(id) && kids.length > 0
    out.push({ id, parent, expandable: kids.length > 0, expanded: open, hidden: open ? 0 : m.nodes.get(id)!.size })
    if (!open) return
    const lim = limitOf(id)
    kids.slice(0, lim).forEach((c) => visit(c, id))
    if (kids.length > lim) {
      out.push({ id: `${MORE_PREFIX}${id}`, more: { parent: id, count: kids.length - lim }, parent: id, expandable: false, expanded: false, hidden: 0 })
    }
  }
  visit(m.root, null)
  return out
}

/** 在预算内一层层展开（广度优先），首屏不至于一次渲染全部节点。 */
export function autoExpand(m: Model, o: Omit<ViewOptions, 'expanded'>, budget = 80): Set<string> {
  const expanded = new Set<string>([m.root])
  let count = 1 + shownChildren(m, m.root, { ...o, expanded }).length
  let level = [m.root]
  while (level.length) {
    const next: string[] = []
    for (const id of level) {
      for (const c of shownChildren(m, id, { ...o, expanded })) {
        const k = shownChildren(m, c, { ...o, expanded }).length
        if (!k) continue
        if (count + k > budget) return expanded
        expanded.add(c)
        count += k
        next.push(c)
      }
    }
    level = next
  }
  return expanded
}

/** 展开节点的整棵子树（最多 cap 个节点，超出时只展开到能容纳的层）。 */
export function expandSubtree(m: Model, id: string, expanded: Set<string>, o: Omit<ViewOptions, 'expanded'>, cap = 300): Set<string> {
  const out = new Set(expanded)
  for (const a of ancestors(m, id)) out.add(a)
  let level = [id]
  let count = 0
  while (level.length) {
    const kidsOfLevel = level.map((x) => shownChildren(m, x, { ...o, expanded: out }))
    const add = kidsOfLevel.reduce((s, k) => s + k.length, 0)
    if (count > 0 && count + add > cap) break
    level.forEach((x, i) => { if (kidsOfLevel[i].length) out.add(x) })
    count += add
    level = kidsOfLevel.flat()
  }
  return out
}

/** 收起节点及其所有后代。 */
export function collapseSubtree(m: Model, id: string, expanded: Set<string>): Set<string> {
  const out = new Set(expanded)
  const walk = (x: string): void => {
    out.delete(x)
    for (const c of m.nodes.get(x)?.children ?? []) walk(c)
  }
  walk(id)
  if (id === m.root) out.add(m.root)
  return out
}

/** 节点在可见图中的代表：自身可见时是自身，否则是最近的可见祖先。 */
export function visibleRep(m: Model, id: string, visible: Set<string>): string | null {
  let cur: string | null | undefined = id
  while (cur) {
    if (visible.has(cur)) return cur
    cur = m.nodes.get(cur)?.parent
  }
  return null
}

export interface AggEdge {
  id: string
  kind: string
  source: string
  target: string
  count: number
  /** 去重后的依赖说明（三语字典或字符串，显示时用 noteText 取值） */
  notes: Note[]
  /** 原始边里有一端是 focus 节点 */
  hot: boolean
}

/** 依赖边聚合到可见祖先；同一对可见节点、同一类型的边合成一条并计数。 */
export function aggregateEdges(m: Model, visible: Set<string>, kinds: Set<string>, focus: string | null): AggEdge[] {
  const agg = new Map<string, AggEdge>()
  for (const e of m.deps) {
    if (!kinds.has(e.kind)) continue
    const a = visibleRep(m, e.from, visible)
    const b = visibleRep(m, e.to, visible)
    if (!a || !b || a === b) continue
    const key = `${e.kind}|${a}|${b}`
    let g = agg.get(key)
    if (!g) {
      g = { id: `dep:${key}`, kind: e.kind, source: a, target: b, count: 0, notes: [], hot: false }
      agg.set(key, g)
    }
    g.count++
    const nk = JSON.stringify(e.note ?? '')
    if (e.note && nk !== '{}' && !g.notes.some((x) => JSON.stringify(x) === nk)) g.notes.push(e.note)
    if (focus && (e.from === focus || e.to === focus)) g.hot = true
  }
  return [...agg.values()]
}

/** 节点的依赖边：出边（本节点依赖谁）与入边（谁依赖本节点）。 */
export function nodeDeps(m: Model, id: string): { out: ApiEdge[]; in: ApiEdge[] } {
  return { out: m.deps.filter((e) => e.from === id), in: m.deps.filter((e) => e.to === id) }
}

/** 搜索：匹配名字、取值、Schema、id，最多 limit 个。 */
export function searchNodes(m: Model, q: string, limit = 200): string[] {
  const s = q.trim().toLowerCase()
  if (!s) return []
  const out: string[] = []
  for (const n of m.nodes.values()) {
    if (n.kind === 'domain' || n.kind === 'rawgroup') continue
    if (`${n.label}\n${n.value}\n${n.schema ?? ''}\n${n.id}`.toLowerCase().includes(s)) {
      out.push(n.id)
      if (out.length >= limit) break
    }
  }
  return out
}

/** 配置文本按行切分；末尾的换行不算一行。 */
export function splitLines(text: string | null | undefined): string[] {
  if (!text) return []
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  if (lines.length && lines[lines.length - 1] === '') lines.pop()
  return lines
}

/** 连续行号合并成区间：[1,2,3,7] → [[1,3],[7,7]]。 */
export function lineRanges(lines: number[]): [number, number][] {
  const s = [...new Set(lines)].sort((a, b) => a - b)
  const out: [number, number][] = []
  for (const l of s) {
    const last = out[out.length - 1]
    if (last && l === last[1] + 1) last[1] = l
    else out.push([l, l])
  }
  return out
}

/** 在有序行号列表里找下一个 / 上一个（循环）。 */
export function stepLine(list: number[], cur: number | null, dir: 1 | -1): number | null {
  if (!list.length) return null
  const c = cur ?? (dir > 0 ? 0 : Number.MAX_SAFE_INTEGER)
  if (dir > 0) return list.find((l) => l > c) ?? list[0]
  for (let i = list.length - 1; i >= 0; i--) if (list[i] < c) return list[i]
  return list[list.length - 1]
}

/** 节点需要高亮的行：自身的行；没有行的分组节点取子树的行（最多 2000 行）。 */
export function highlightLines(m: Model, id: string | null): Set<number> {
  const out = new Set<number>()
  if (!id) return out
  const n = m.nodes.get(id)
  if (!n || n.kind === 'device') return out
  if (n.lines.length) {
    n.lines.forEach((l) => out.add(l))
    return out
  }
  if (n.kind !== 'domain') return out
  const stack = [...n.children]
  while (stack.length && out.size < 2000) {
    const c = m.nodes.get(stack.pop()!)!
    c.lines.forEach((l) => out.add(l))
    stack.push(...c.children)
  }
  return out
}
