/**
 * 拓扑视图的设备图标与分组分层（REQ-042 / M8-3 拓扑整理）：把拓扑节点、项目视图标注、待采纳的 AI 建议合成每台设备的
 * 显示信息（图形、厂商、角标、是否 ghost、小字），以及按分组成列、按角色分层的位置。纯函数，便于测试。
 */
import {
  annoByDevice, badgesOf, glyphOfRole, isRole, pendingOf, peerLinks, resolveRole,
  type Annotation, type PendingSuggestion, type Resolved, type Role, vendorCode,
} from '@/components/devicon/logic'
import type { Badge, VendorCode } from '@/components/devicon/lmi'
import type { TopoNode } from './topology'

export interface NodeMark {
  id: string
  glyph: string
  vendor: VendorCode | ''
  badges: Badge[]
  /** 待采纳的 AI 角色建议：图标画成紫色虚线半透明 */
  ghost: boolean
  /** 当前角色（已生效）与来源 */
  resolved: Resolved
  /** 待采纳的建议值（角色 / 分组 / 层次） */
  pendingRole: Role | null
  pendingGroup: string | null
  group: string
  layer: number | null
  label: string
}

export interface ExtraEdge { id: string; source: string; target: string; kind: 'peer' | 'ai'; label: string }
export interface ExtraNode { id: string; label: string; glyph: 'peer' | 'cloud'; ghost: boolean }

export interface MarkInput {
  nodes: TopoNode[]
  annotations: Annotation[]
  pending: PendingSuggestion[]
  /** 设备编号 → 设备列表里的 stale */
  stale?: Record<number, boolean>
  showAi: boolean
}

/** 角色 → 默认层（0 外部、1 核心、2 汇聚 / PE、3 接入、4 客户侧）。 */
export function bandOfRole(r: Role | null | undefined): number {
  switch (r) {
    case 'core': case 'p': return 1
    case 'aggregation': case 'pe': return 2
    case 'access': return 3
    case 'ce': return 4
    default: return 3
  }
}

export function buildMarks(inp: MarkInput): { marks: Map<string, NodeMark>; extraNodes: ExtraNode[]; extraEdges: ExtraEdge[] } {
  const byDev = annoByDevice(inp.annotations)
  const pend = inp.showAi ? pendingOf(inp.pending) : { hints: [], peers: [] }
  const marks = new Map<string, NodeMark>()
  const byId = new Map<number, string>()
  for (const n of inp.nodes) {
    if (n.device_id != null) byId.set(n.device_id, n.id)
    const a = n.device_id != null ? byDev.get(String(n.device_id)) : undefined
    const resolved = resolveRole(a, n.profile, n.family)
    const hints = n.device_id != null ? pend.hints.filter((h) => h.device_id === n.device_id) : []
    const pr = hints.find((h) => h.key === 'role' && isRole(h.value) && h.value !== resolved.role)
    const pg = hints.find((h) => h.key === 'group' && typeof h.value === 'string')
    const ghost = !!pr
    const layerA = a?.layer?.value
    marks.set(n.id, {
      id: n.id,
      glyph: pr ? glyphOfRole(pr.value as Role) : resolved.glyph,
      vendor: vendorCode(n.family, n.profile),
      badges: badgesOf({ cons: n.issues > 0, stale: n.device_id != null && !!inp.stale?.[n.device_id], ai: hints.length > 0 }),
      ghost,
      resolved,
      pendingRole: pr ? (pr.value as Role) : null,
      pendingGroup: pg ? String(pg.value) : null,
      group: typeof a?.group?.value === 'string' ? a.group.value : '',
      layer: typeof layerA === 'number' ? layerA : null,
      label: typeof a?.label?.value === 'string' ? a.label.value : '',
    })
  }
  const extraNodes: ExtraNode[] = []
  const extraEdges: ExtraEdge[] = []
  const seenExt = new Set<string>()
  const ext = (key: string, label: string, ghost: boolean): string => {
    const id = `ext:${key}`
    if (!seenExt.has(id)) {
      seenExt.add(id)
      extraNodes.push({ id, label, glyph: 'peer', ghost })
    } else if (!ghost) {
      const x = extraNodes.find((e) => e.id === id)
      if (x) x.ghost = false
    }
    return id
  }
  for (const p of peerLinks(inp.annotations)) {
    const a = p.a.device_id != null ? byId.get(p.a.device_id) : undefined
    if (!a) continue
    const b = p.b.device_id != null ? byId.get(p.b.device_id) : ext(p.b.address || p.label || p.b.name || String(p.id), p.b.address || p.b.name || p.label, false)
    if (!b) continue
    extraEdges.push({ id: `peer:${p.id}`, source: a, target: b, kind: 'peer', label: p.label })
  }
  for (const p of pend.peers) {
    const a = p.a != null ? byId.get(p.a) : undefined
    if (!a) continue
    const b = p.b != null ? byId.get(p.b) : ext(p.bLabel || String(p.id), p.bLabel, true)
    if (!b) continue
    extraEdges.push({ id: `ai:${p.id}`, source: a, target: b, kind: 'ai', label: p.label })
  }
  return { marks, extraNodes, extraEdges }
}

/** 有分组或角色（手工 / 采纳的 AI）时按“分组成列、角色分层”排版；都没有时交给力导向布局。 */
export function useBands(marks: Map<string, NodeMark>): boolean {
  for (const m of marks.values()) if (m.group || m.resolved.source !== 'platform' || m.layer !== null) return true
  return false
}

export interface Pos { x: number; y: number }

/**
 * 分组成列、分层成行：未分组的在最左列；每列宽度按该列同一层里最多的设备数；外部对端放在第 0 层。
 * 返回每个节点的位置（cytoscape preset 布局用）。
 */
export function bandLayout(items: { id: string; group: string; band: number }[], dx = 170, dy = 150): Map<string, Pos> {
  const groups = [...new Set(items.map((i) => i.group))].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b, undefined, { numeric: true })))
  const out = new Map<string, Pos>()
  let x0 = 0
  for (const g of groups) {
    const inG = items.filter((i) => i.group === g)
    const rows = new Map<number, string[]>()
    for (const i of inG) rows.set(i.band, [...(rows.get(i.band) ?? []), i.id])
    const width = Math.max(1, ...[...rows.values()].map((r) => r.length))
    for (const [band, ids] of rows) {
      ids.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
      const off = ((width - ids.length) * dx) / 2
      ids.forEach((id, k) => out.set(id, { x: x0 + off + k * dx, y: band * dy }))
    }
    x0 += width * dx + dx * 0.6
  }
  return out
}
