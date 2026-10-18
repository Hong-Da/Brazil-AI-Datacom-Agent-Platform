/**
 * 关系图谱（REQ-027）的数据：每个对象一个圆点（属性不单独成点，归到所属对象），
 * 连线是包含（对象之间的父子）与依赖（引用 / 前置 / 副作用 / 互斥，端点归到所属对象后去重）。
 * 纯函数，不依赖 DOM。
 */
import type { Model, TNode } from './model'

export interface FNode {
  id: string
  label: string
  kind: string
  domain: string
  origin: string
  /** 相邻圆点数（决定圆点大小） */
  degree: number
}

export interface FEdge {
  id: string
  kind: string
  source: string
  target: string
}

export interface ForceOptions {
  showDefault: boolean
  /** 显示原文、未识别与扩展命令节点 */
  showRaw: boolean
  /** 依赖边类型（reference 等）；contains 总是带上 */
  kinds?: Set<string>
}

export interface ForceData {
  nodes: FNode[]
  edges: FEdge[]
  /** 任意节点（含属性）→ 代表它的圆点 */
  owner: (id: string | null) => string | null
}

const OBJECT_KINDS = new Set(['object'])
const RAW_KINDS = new Set(['raw', 'unknown', 'ext'])

function isDot(n: TNode, o: ForceOptions): boolean {
  if (!n.api) return false // 设备、功能域、原文分组不是圆点
  if (n.origin === 'default' && !o.showDefault) return false
  if (OBJECT_KINDS.has(n.kind)) return true
  return o.showRaw && RAW_KINDS.has(n.kind)
}

export function buildForce(m: Model, o: ForceOptions): ForceData {
  const dots = new Set<string>()
  for (const n of m.nodes.values()) if (n.kind !== 'device' && isDot(n, o)) dots.add(n.id)

  const cache = new Map<string, string | null>()
  const owner = (id: string | null): string | null => {
    if (!id) return null
    if (cache.has(id)) return cache.get(id)!
    let cur: string | null | undefined = id
    let hops = 0
    while (cur && !dots.has(cur) && hops++ < 200) cur = m.nodes.get(cur)?.parent
    const r = cur && dots.has(cur) ? cur : null
    cache.set(id, r)
    return r
  }

  const edges = new Map<string, FEdge>()
  const nb = new Map<string, Set<string>>()
  const link = (kind: string, a: string, b: string): void => {
    const id = `${kind}|${a}|${b}`
    if (edges.has(id)) return
    edges.set(id, { id, kind, source: a, target: b })
    if (!nb.has(a)) nb.set(a, new Set())
    if (!nb.has(b)) nb.set(b, new Set())
    nb.get(a)!.add(b)
    nb.get(b)!.add(a)
  }
  for (const id of dots) {
    const p = owner(m.nodes.get(id)!.parent)
    if (p && p !== id) link('contains', p, id)
  }
  for (const e of m.deps) {
    if (o.kinds && !o.kinds.has(e.kind)) continue
    // 隐藏默认值时，默认值节点（含默认属性）的依赖也不画
    if (!o.showDefault && (m.nodes.get(e.from)?.origin === 'default' || m.nodes.get(e.to)?.origin === 'default')) continue
    const a = owner(e.from)
    const b = owner(e.to)
    if (a && b && a !== b) link(e.kind, a, b)
  }
  const nodes: FNode[] = [...dots].map((id) => {
    const n = m.nodes.get(id)!
    return { id, label: n.kind === 'raw' || n.kind === 'unknown' ? (n.value || n.label).trim() : n.label, kind: n.kind, domain: n.domain, origin: n.origin, degree: nb.get(id)?.size ?? 0 }
  })
  return { nodes, edges: [...edges.values()], owner }
}

/** 圆点直径：按连接数，10～40。 */
export function dotSize(degree: number): number {
  return Math.round(Math.min(40, 10 + 3.4 * Math.sqrt(degree)))
}

/** 功能域 → 分类色变量（--dom-1 … --dom-10），按功能域顺序循环。 */
export function domainColorVar(domain: string, order: string[]): string {
  const i = order.indexOf(domain)
  return `--dom-${((i < 0 ? order.length : i) % 10) + 1}`
}

/** 每个功能域的圆点数（图例用）。 */
export function domainCounts(nodes: FNode[]): Map<string, number> {
  const c = new Map<string, number>()
  for (const n of nodes) c.set(n.domain, (c.get(n.domain) ?? 0) + 1)
  return c
}
