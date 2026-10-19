/**
 * TCP/IP 模型视图的数据整理（纯函数）：每层按对象类型分组、作用层与对象不同的属性单独成组、
 * 跨层依赖按对象类型汇总、选中对象的跨层依赖。层的归类由后端给出（layers.nodes）。
 */
import type { Model } from '@/views/device-graph/model'
import type { CrossEdge } from './types'

/** 节点所属的对象：对象是自身，其余是最近的对象祖先。 */
export function ownerObject(m: Model, id: string | null): string | null {
  let cur: string | null | undefined = id
  let hops = 0
  while (cur && hops++ < 100) {
    const n = m.nodes.get(cur)
    if (!n) return null
    if (n.kind === 'object') return cur
    cur = n.parent
  }
  return null
}

export interface BandGroup {
  /** `${层}|${Schema}` */
  key: string
  schema: string
  /** 作用层与所属对象不同的属性组 */
  attr: boolean
  /** 属性组：所属对象的 Schema */
  ownerSchema: string | null
  items: string[]
}

export interface BandOptions {
  showDefault: boolean
}

/**
 * 每层的分组：对象按 Schema 分组；与父对象同层的子对象由父对象代表（不重复列出）；
 * 作用层与所属对象不同的属性（例如接口的 vrf 在网络层）在它的层单独成组。
 */
export function bandGroups(m: Model, layerOf: Record<string, string>, o: BandOptions): Map<string, BandGroup[]> {
  const out = new Map<string, Map<string, BandGroup>>()
  const add = (layer: string, schema: string, attr: boolean, ownerSchema: string | null, id: string): void => {
    let g = out.get(layer)
    if (!g) out.set(layer, (g = new Map()))
    const key = `${layer}|${schema}`
    let grp = g.get(key)
    if (!grp) g.set(key, (grp = { key, schema, attr, ownerSchema, items: [] }))
    grp.items.push(id)
  }
  for (const n of m.nodes.values()) {
    const layer = layerOf[n.id]
    if (!layer || !n.schema || n.schema.startsWith('ext:')) continue
    if (!o.showDefault && n.origin === 'default') continue
    if (n.kind === 'object') {
      const po = ownerObject(m, n.parent)
      if (po && layerOf[po] === layer) continue
      add(layer, n.schema, false, null, n.id)
    } else if (n.kind === 'attr') {
      const own = ownerObject(m, n.id)
      if (!own || layerOf[own] === layer) continue
      add(layer, n.schema, true, m.nodes.get(own)?.schema ?? null, n.id)
    }
  }
  const res = new Map<string, BandGroup[]>()
  for (const [layer, g] of out) {
    res.set(layer, [...g.values()].sort((a, b) => Number(a.attr) - Number(b.attr) || b.items.length - a.items.length || a.schema.localeCompare(b.schema)))
  }
  return res
}

/** 节点在 TCP/IP 视图里由哪个分组代表（找不到时 null）。 */
export function groupKeyOf(m: Model, layerOf: Record<string, string>, id: string): string | null {
  const n = m.nodes.get(id)
  const layer = layerOf[id]
  if (!n || !layer || !n.schema) return null
  if (n.kind === 'object') {
    // 与父对象同层时由最上层的同层祖先代表
    let rep = id
    let po = ownerObject(m, n.parent)
    while (po && layerOf[po] === layer) {
      rep = po
      po = ownerObject(m, m.nodes.get(po)?.parent ?? null)
    }
    return `${layer}|${m.nodes.get(rep)?.schema}`
  }
  return `${layer}|${n.schema}`
}

/** 在 TCP/IP 视图中代表节点的“格子”：同层祖先对象，或作用层不同的属性自身。 */
export function chipOf(m: Model, layerOf: Record<string, string>, id: string): string | null {
  const n = m.nodes.get(id)
  if (!n) return null
  if (n.kind === 'attr') {
    const own = ownerObject(m, id)
    if (own && layerOf[own] !== layerOf[id] && layerOf[id]) return id
    return own ? chipOf(m, layerOf, own) : null
  }
  if (n.kind !== 'object') {
    const own = ownerObject(m, id)
    return own ? chipOf(m, layerOf, own) : null
  }
  let rep = id
  let po = ownerObject(m, n.parent)
  while (po && layerOf[po] === layerOf[id]) {
    rep = po
    po = ownerObject(m, m.nodes.get(po)?.parent ?? null)
  }
  return rep
}

export interface GroupLink {
  a: string
  b: string
  count: number
}

/** 跨层依赖按分组汇总（概览连线）。 */
export function groupLinks(m: Model, layerOf: Record<string, string>, cross: CrossEdge[]): GroupLink[] {
  const agg = new Map<string, GroupLink>()
  for (const e of cross) {
    const a = groupKeyOf(m, layerOf, e.from)
    const b = groupKeyOf(m, layerOf, e.to)
    if (!a || !b || a === b) continue
    const k = `${a}>${b}`
    const g = agg.get(k)
    if (g) g.count += e.count
    else agg.set(k, { a, b, count: e.count })
  }
  return [...agg.values()]
}

/** 对象的跨层依赖（出边在前）。 */
export function crossOf(cross: CrossEdge[], obj: string | null): { edge: CrossEdge; out: boolean; other: string }[] {
  if (!obj) return []
  const out: { edge: CrossEdge; out: boolean; other: string }[] = []
  for (const e of cross) {
    if (e.from === obj) out.push({ edge: e, out: true, other: e.to })
    else if (e.to === obj) out.push({ edge: e, out: false, other: e.from })
  }
  return out.sort((x, y) => Number(y.out) - Number(x.out))
}

/** 层的显示名（当前语言；没有时用编号）。 */
export function layerName(info: { id: string; name: Record<string, string> | null }[], id: string | null | undefined, lang: string, fallback: string): string {
  if (!id) return fallback
  const x = info.find((l) => l.id === id)
  return (x?.name && (x.name[lang] || x.name.en)) || id
}

/* ---------- 合并相似（REQ-034 评审修改）：同组内键只差末尾编号的对象合并成一个范围格子 ---------- */

export type ChipEntry =
  | { merged: false; id: string }
  | { merged: true; key: string; stem: string; from: number; to: number; members: string[] }

/** 合并至少要有几个成员（两个时合并省不了地方） */
export const MERGE_MIN = 3

/**
 * 把一组格子里“相似”的对象合并：标签（对象的键）去掉末尾编号后相同的对象归为一簇，簇的成员不少于 min 个时合并，
 * 例如 GigabitEthernet0/2/0…7、子接口 GE0/2/1.101…108、对等体 10.255.0.101…103。属性格子与没有末尾编号的对象不合并。
 * 合并后的格子放在第一个成员原来的位置，成员按编号排序。
 */
export function mergeSimilar(items: string[], labelOf: (id: string) => string, isObject: (id: string) => boolean, min = MERGE_MIN): ChipEntry[] {
  const parse = (id: string): { stem: string; n: number } | null => {
    if (!isObject(id)) return null
    const m = /^(.*?)(\d+)$/.exec(labelOf(id))
    // 地址（10.0.149.40、2001:db8::1）末尾的数字不是编号，合并成范围会误读
    if (!m || /\d+\.\d+\.\d+\.$/.test(m[1]!) || /[0-9a-f]*:[0-9a-f]*:$/i.test(m[1]!)) return null
    return { stem: m[1]!, n: Number(m[2]) }
  }
  const parsed = new Map<string, { stem: string; n: number }>()
  const byStem = new Map<string, string[]>()
  for (const id of items) {
    const p = parse(id)
    if (!p) continue
    parsed.set(id, p)
    const list = byStem.get(p.stem)
    if (list) list.push(id)
    else byStem.set(p.stem, [id])
  }
  const out: ChipEntry[] = []
  const done = new Set<string>()
  for (const id of items) {
    const p = parsed.get(id)
    const members = p ? byStem.get(p.stem)! : null
    if (!p || !members || members.length < min) {
      out.push({ merged: false, id })
      continue
    }
    if (done.has(p.stem)) continue
    done.add(p.stem)
    const sorted = [...members].sort((a, b) => parsed.get(a)!.n - parsed.get(b)!.n)
    out.push({ merged: true, key: p.stem, stem: p.stem, from: parsed.get(sorted[0]!)!.n, to: parsed.get(sorted[sorted.length - 1]!)!.n, members: sorted })
  }
  return out
}

const STEM_SHORT: [RegExp, string][] = [
  [/TenGigabitEthernet/, 'Te'],
  [/HundredGigE/, 'Hu'],
  [/XGigabitEthernet/, 'XGE'],
  [/GigabitEthernet/, 'GE'],
]

/** 合并格子的文字：接口名用简写，例如 “GE0/2/1–8”。 */
export function mergedText(e: { stem: string; from: number; to: number }): string {
  let stem = e.stem
  for (const [re, s] of STEM_SHORT) if (re.test(stem)) { stem = stem.replace(re, s); break }
  return `${stem}${e.from}–${e.to}`
}
