/**
 * 变更影响分析页（POST /api/v1/impact）的数据结构与纯逻辑：路径还原、分组、深度过滤、起点候选、URL 参数。
 */

export type Direction = 'up' | 'down' | 'both'
export interface ImpactNode {
  node: string
  schema: string | null
  kind: string
  domain: string
  depth: number
  via: string | null
  edge: string
  direction: string
  business: string | null
}
export interface ImpactResult {
  device: string
  profile: string
  direction: Direction
  seeds: { node: string; schema: string; domain: string }[]
  nodes: ImpactNode[]
  objects: { node: string; schema: string; domain: string; depth: number; edge: string; business: string | null }[]
  business: { node: string; schema: string; domain: string; type: string; direction: string; path: string[] }[]
  by_domain: Record<string, number>
  by_business: Record<string, string[]>
  summary: { seeds: number; objects: number; business: number }
}

/** 依赖类型 → 边的颜色类别。 */
export function edgeClass(kind: string): 'ref' | 'pre' | 'contains' | 'alias' | 'seed' {
  if (kind === 'seed') return 'seed'
  if (kind === 'contains') return 'contains'
  if (kind === 'prerequisite') return 'pre'
  if (kind === 'alias' || kind === 'key') return 'alias'
  return 'ref'
}

/** 从起点到 id 的路径（沿 via 回溯）。 */
export function pathTo(nodes: ImpactNode[], id: string): string[] {
  const by = new Map(nodes.map((n) => [n.node, n]))
  const out: string[] = []
  const seen = new Set<string>()
  let cur: string | null = id
  while (cur && !seen.has(cur)) {
    seen.add(cur)
    out.unshift(cur)
    cur = by.get(cur)?.via ?? null
  }
  return out
}

/** 按深度过滤（maxDepth 0 表示不限）；起点总在。 */
export function withinDepth(nodes: ImpactNode[], maxDepth: number): ImpactNode[] {
  return maxDepth > 0 ? nodes.filter((n) => n.depth <= maxDepth) : nodes
}

/** 结果列表只列对象（属性节点只是路径上的一环），起点除外。 */
export function listed(nodes: ImpactNode[], objectsOnly: boolean): ImpactNode[] {
  return nodes.filter((n) => n.depth > 0 && (!objectsOnly || n.kind !== 'attr'))
}

export type Tab = 'type' | 'hop' | 'domain'
export const BIZ_ORDER = ['peer', 'vrf', 'interface', 'l2vpn']

/** 分组：type 按业务类别（不是业务对象的归入“其他”），hop 按距离，domain 按功能域。组内按距离、编号排序。 */
export function groupBy(nodes: ImpactNode[], tab: Tab): { key: string; items: ImpactNode[] }[] {
  const m = new Map<string, ImpactNode[]>()
  const keyOf = (n: ImpactNode) => (tab === 'hop' ? String(n.depth) : tab === 'domain' ? n.domain || 'other' : n.business ?? 'other')
  for (const n of nodes) {
    const k = keyOf(n)
    m.set(k, [...(m.get(k) ?? []), n])
  }
  const keys = [...m.keys()]
  if (tab === 'hop') keys.sort((a, b) => Number(a) - Number(b))
  else if (tab === 'type') keys.sort((a, b) => (BIZ_ORDER.indexOf(a) + 1 || 99) - (BIZ_ORDER.indexOf(b) + 1 || 99))
  else keys.sort()
  return keys.map((key) => ({ key, items: [...m.get(key)!].sort((a, b) => a.depth - b.depth || a.node.localeCompare(b.node)) }))
}

/** 概况：受影响的对象数、各业务类别数、涉及的功能域数。 */
export function stripCounts(r: ImpactResult | null, nodes: ImpactNode[]): Record<string, number> {
  const objs = listed(nodes, true)
  const biz = (t: string) => objs.filter((n) => n.business === t).length
  return {
    objects: objs.length,
    peer: biz('peer'),
    vrf: biz('vrf'),
    interface: biz('interface'),
    l2vpn: biz('l2vpn'),
    domains: new Set(objs.map((n) => n.domain).filter(Boolean)).size,
    seeds: r?.seeds.length ?? 0,
  }
}

export interface GNode { id: string; kind: string; schema: string | null }

/** 起点候选：对象节点按名字搜索（不分大小写，匹配规范编号或显示名），最多 limit 个。 */
export function searchNodes(nodes: GNode[], q: string, label: (id: string) => string, limit = 30): GNode[] {
  const s = q.trim().toLowerCase()
  if (!s) return []
  const out: GNode[] = []
  for (const n of nodes) {
    if (n.kind !== 'object' && n.kind !== 'attr') continue
    if (n.id.toLowerCase().includes(s) || label(n.id).toLowerCase().includes(s)) out.push(n)
    if (out.length >= limit) break
  }
  return out
}

/** 常用起点：VPN 实例、前缀列表、路由策略、对等体组、环回口（最多 limit 个）。 */
const PRESET_SCHEMAS = ['vrf.instance', 'rp.prefix_list', 'rp.policy', 'bgp.peer_group', 'rp.community_filter', 'acl.instance']
export function presets(nodes: GNode[], limit = 8): GNode[] {
  const out: GNode[] = []
  for (const s of PRESET_SCHEMAS) {
    for (const n of nodes) if (n.schema === s && n.kind === 'object') out.push(n)
  }
  const lo = nodes.find((n) => n.schema === 'interface' && /\[loopback0\]$/i.test(n.id))
  if (lo) out.push(lo)
  return out.slice(0, limit)
}

type Query = Record<string, string | null | (string | null)[] | undefined>
const all = (q: Query, k: string): string[] => {
  const v = q[k]
  return (Array.isArray(v) ? v : [v]).filter((x): x is string => !!x)
}

/** URL 参数：device、version、node（可多个）、dir、from=change。 */
export function fromQuery(q: Query): { device: number | null; version: number | null; nodes: string[]; dir: Direction; fromChange: boolean } {
  const n = (s: string | undefined) => (s && /^\d+$/.test(s) ? Number(s) : null)
  const dir = all(q, 'dir')[0]
  return {
    device: n(all(q, 'device')[0]),
    version: n(all(q, 'version')[0]),
    nodes: all(q, 'node'),
    dir: dir === 'down' || dir === 'both' ? dir : 'up',
    fromChange: all(q, 'from')[0] === 'change',
  }
}
