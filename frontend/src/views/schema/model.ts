/** Schema 视图与 Schema 管理共用的数据类型与纯逻辑：树结构、依赖边、覆盖率统计、对比分组。 */

export type I18nText = Record<string, string>

export interface SchemaNode {
  id: string
  parent: string | null
  type: string
  key: string[]
  semantic: I18nText
  range: number[] | null
  choices: string[] | null
  ordered: boolean
  ref: string | null
  deprecated: boolean
  replaced_by: string | null
  status: string
  children: number
}

export interface SchemaDep {
  kind: string
  from: string
  to: string
  note: string
  profiles: string[]
}

export interface SchemaDomain {
  domain: string
  nodes: SchemaNode[]
  deps: SchemaDep[]
}

export interface SchemaData {
  kb_version: string
  node_types: string[]
  domains: SchemaDomain[]
  profiles?: string[]
}

export type EntryState = 'supported' | 'unsupported' | 'unfilled'

export interface CoverageData {
  profiles: string[]
  totals: Record<string, { supported: number; unsupported: number; unfilled: number }>
  matrix: Record<string, Record<string, EntryState>>
}

export interface CompareRow {
  node: string
  domain: string
  semantic: I18nText
  a: { state: EntryState; default: unknown }
  b: { state: EntryState; default: unknown }
  kind: 'same' | 'only_a' | 'only_b' | 'default' | 'unfilled'
}

export interface CompareData {
  a: string
  b: string
  counts: Record<string, number>
  rows: CompareRow[]
}

export interface ProfileRow {
  id: string
  title: string
  vendor: string
  family: string
  platform: string
  software: string
  inherits: string | null
}

export interface ProfileEntry {
  node: string
  state: EntryState
  default?: unknown
  credibility?: string
  inherited?: boolean
  origin?: string
}

export interface ProfileDetail {
  profile: ProfileRow & { lineage: string[] }
  entries: ProfileEntry[]
}

/** 树中的一行：节点、深度、相对父节点的短名。 */
export interface TreeItem {
  node: SchemaNode
  depth: number
  name: string
  domain: string
}

export interface TreeGroup {
  domain: string
  items: TreeItem[]
}

/** 相对父节点的短名：id 以父 id 为前缀时去掉前缀；否则去掉两者的公共段（如 bgp.af 在 bgp.instance 下显示 af）。 */
export function shortName(id: string, parent: string | null): string {
  if (!parent) return id
  if (id.startsWith(parent + '.')) return id.slice(parent.length + 1)
  const a = id.split('.'), b = parent.split('.')
  let i = 0
  while (i < a.length - 1 && i < b.length && a[i] === b[i]) i++
  return a.slice(i).join('.')
}

/** 按功能域整理成树（先序遍历，同级按 id 排序）；父节点不在本域时当作根。 */
export function buildTree(domains: SchemaDomain[]): TreeGroup[] {
  return domains.map((d) => {
    const ids = new Set(d.nodes.map((n) => n.id))
    const kids = new Map<string | null, SchemaNode[]>()
    for (const n of d.nodes) {
      const p = n.parent && ids.has(n.parent) && n.parent !== n.id ? n.parent : null
      if (!kids.has(p)) kids.set(p, [])
      kids.get(p)!.push(n)
    }
    for (const list of kids.values()) list.sort((x, y) => x.id.localeCompare(y.id))
    const items: TreeItem[] = []
    const seen = new Set<string>()
    const walk = (p: string | null, depth: number) => {
      for (const n of kids.get(p) ?? []) {
        if (seen.has(n.id)) continue
        seen.add(n.id)
        items.push({ node: n, depth, name: shortName(n.id, depth ? n.parent : null), domain: d.domain })
        walk(n.id, depth + 1)
      }
    }
    walk(null, 0)
    // 父子成环时剩下的节点按根节点放在最后，不丢节点
    for (const n of d.nodes) if (!seen.has(n.id)) items.push({ node: n, depth: 0, name: n.id, domain: d.domain })
    return { domain: d.domain, items }
  })
}

/** 按 id 子串筛选（不区分大小写）；空查询原样返回，去掉没有命中的功能域。 */
export function filterTree(groups: TreeGroup[], q: string): TreeGroup[] {
  const s = q.trim().toLowerCase()
  if (!s) return groups
  return groups
    .map((g) => ({ domain: g.domain, items: g.items.filter((it) => it.node.id.toLowerCase().includes(s)) }))
    .filter((g) => g.items.length > 0)
}

export function allNodes(domains: SchemaDomain[]): SchemaNode[] {
  return domains.flatMap((d) => d.nodes)
}

export function allDeps(domains: SchemaDomain[]): SchemaDep[] {
  return domains.flatMap((d) => d.deps)
}

export function nodeDomain(domains: SchemaDomain[]): Map<string, string> {
  const m = new Map<string, string>()
  for (const d of domains) for (const n of d.nodes) m.set(n.id, d.domain)
  return m
}

/** 后端依赖类型 → 界面边样式（e.ref 等文案与 .g-edge.ref 等样式）。 */
export const DEP_STYLE: Record<string, string> = {
  reference: 'ref',
  prerequisite: 'pre',
  side_effect: 'side',
  mutex: 'mutex',
  cross_device: 'cross',
}
export const EDGE_STYLES = ['ref', 'pre', 'side', 'mutex', 'cross'] as const

export function depStyle(kind: string): string {
  return DEP_STYLE[kind] ?? 'ref'
}

/** 依赖规则是否在某个 Profile 中生效（profiles 为空表示全部）。 */
export function depApplies(dep: SchemaDep, profile: string | null): boolean {
  return !profile || !dep.profiles?.length || dep.profiles.includes(profile)
}

export interface NodeEdge {
  style: string
  kind: string
  other: string
  dir: 'out' | 'in'
  note: string
}

/** 一个节点的依赖：出边（它依赖谁）与入边（谁依赖它）。 */
export function edgesOf(deps: SchemaDep[], id: string): NodeEdge[] {
  const out: NodeEdge[] = []
  for (const d of deps) {
    if (d.from === id) out.push({ style: depStyle(d.kind), kind: d.kind, other: d.to, dir: 'out', note: d.note })
    else if (d.to === id) out.push({ style: depStyle(d.kind), kind: d.kind, other: d.from, dir: 'in', note: d.note })
  }
  return out
}

export interface Cov {
  sup: number
  tot: number
  unf: number
  uns: number
  pct: number
}

/** 某 Profile 在给定节点集合上的激活情况（已废弃节点不计入）。 */
export function coverageOf(nodes: SchemaNode[], matrix: CoverageData['matrix'], profile: string): Cov {
  let sup = 0, tot = 0, unf = 0, uns = 0
  for (const n of nodes) {
    if (n.deprecated) continue
    tot++
    const st = matrix[n.id]?.[profile] ?? 'unfilled'
    if (st === 'supported') sup++
    else if (st === 'unsupported') uns++
    else unf++
  }
  return { sup, tot, unf, uns, pct: tot ? Math.round((sup * 100) / tot) : 0 }
}

export function credibilityCounts(entries: ProfileEntry[], deprecated: Set<string>): Record<'verified' | 'reviewed' | 'draft', number> {
  const c = { verified: 0, reviewed: 0, draft: 0 }
  for (const e of entries) {
    if (e.state !== 'supported' || deprecated.has(e.node)) continue
    if (e.credibility === 'verified' || e.credibility === 'reviewed' || e.credibility === 'draft') c[e.credibility]++
  }
  return c
}

export interface CompareGroups {
  onlyA: CompareRow[]
  onlyB: CompareRow[]
  defaults: CompareRow[]
  unfilled: CompareRow[]
}

/** 对比结果按类型分组（已废弃节点不列出）。 */
export function compareGroups(rows: CompareRow[], deprecated: Set<string>): CompareGroups {
  const g: CompareGroups = { onlyA: [], onlyB: [], defaults: [], unfilled: [] }
  for (const r of rows) {
    if (deprecated.has(r.node)) continue
    if (r.kind === 'only_a') g.onlyA.push(r)
    else if (r.kind === 'only_b') g.onlyB.push(r)
    else if (r.kind === 'default') g.defaults.push(r)
    else if (r.kind === 'unfilled') g.unfilled.push(r)
  }
  return g
}

/** 默认值的显示文本：null / undefined 为空串，其他值原样转字符串。 */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
