/**
 * REQ-042 设备图标的取值逻辑（纯函数）：角色（手工标注 > 采纳的 AI 建议 > 平台默认）、平台外形、厂商标识、
 * 视图标注与待采纳的拓扑整理建议的整理。
 */
import { vendorKey } from '@/vendor'
import type { Badge, VendorCode } from './lmi'

/** 后端的角色取值（view_annotations / topology-roles）。 */
export type Role = 'core' | 'aggregation' | 'access' | 'pe' | 'p' | 'ce'
export const ROLES: Role[] = ['core', 'aggregation', 'access', 'pe', 'p', 'ce']
export type RoleSource = 'user' | 'ai' | 'platform'

/** 角色 → 图形名（aggregation 的图形叫 agg）。 */
export function glyphOfRole(r: Role | string): string {
  return r === 'aggregation' ? 'agg' : r
}

export function isRole(v: unknown): v is Role {
  return typeof v === 'string' && (ROLES as string[]).includes(v)
}

/** 平台默认外形：华为 ATN → plat_atn，Cisco ASR 920 → plat_asr920，Nokia 7750 / SR → plat_7750；其他按厂商取最接近的。 */
export function platformGlyph(...hints: (string | null | undefined)[]): string {
  const s = hints.filter(Boolean).join(' ').toLowerCase()
  if (/\batn\b|atn[-_ ]?\d|huawei-atn/.test(s)) return 'plat_atn'
  if (/asr[-_ ]?920|asr920/.test(s)) return 'plat_asr920'
  if (/7750|7250|sr[-_ ]?os|sros|\bsr-\d|nokia/.test(s)) return 'plat_7750'
  for (const h of hints) {
    const k = vendorKey(h)
    if (k === 'huawei') return 'plat_atn'
    if (k === 'cisco') return 'plat_asr920'
    if (k === 'nokia') return 'plat_7750'
  }
  if (/vrp|huawei/.test(s)) return 'plat_atn'
  if (/ios|cisco/.test(s)) return 'plat_asr920'
  return 'plat_atn'
}

/** 厂商标识 HW / CS / NK（不认识的不画）。 */
export function vendorCode(...hints: (string | null | undefined)[]): VendorCode | '' {
  for (const h of hints) {
    const k = vendorKey(h)
    if (k === 'huawei') return 'hw'
    if (k === 'cisco') return 'cs'
    if (k === 'nokia') return 'nk'
  }
  const s = hints.filter(Boolean).join(' ').toLowerCase()
  if (/vrp|atn/.test(s)) return 'hw'
  if (/ios|asr/.test(s)) return 'cs'
  if (/sros|7750/.test(s)) return 'nk'
  return ''
}

export interface Annotation {
  id: number
  target_type: string
  target: string
  key: string
  value: unknown
  source: 'user' | 'ai'
  suggestion_id: number | null
  updated_by: string
  updated_at: string | null
}

/** 一台设备的标注（device 目标，按 key）。 */
export type DeviceAnno = Partial<Record<'role' | 'group' | 'label' | 'layer', Annotation>>

export function annoByDevice(list: Annotation[]): Map<string, DeviceAnno> {
  const m = new Map<string, DeviceAnno>()
  for (const a of list) {
    if (a.target_type !== 'device') continue
    if (!['role', 'group', 'label', 'layer'].includes(a.key)) continue
    const cur = m.get(a.target) ?? {}
    cur[a.key as keyof DeviceAnno] = a
    m.set(a.target, cur)
  }
  return m
}

export interface Resolved { glyph: string; role: Role | null; source: RoleSource }

/** 角色取值：手工标注优先，其次采纳的 AI 建议，最后按平台画设备外形。 */
export function resolveRole(anno: DeviceAnno | undefined, ...platformHints: (string | null | undefined)[]): Resolved {
  const a = anno?.role
  if (a && isRole(a.value)) return { glyph: glyphOfRole(a.value), role: a.value, source: a.source === 'user' ? 'user' : 'ai' }
  return { glyph: platformGlyph(...platformHints), role: null, source: 'platform' }
}

/** 采纳的 AI 推测对端（link 目标、key peer）。 */
export interface PeerEnd { device_id: number | null; name: string; interface: string | null; address: string | null }
export interface PeerAnno { id: number; a: PeerEnd; b: PeerEnd; external: boolean; label: string; source: string }

export function peerLinks(list: Annotation[]): PeerAnno[] {
  const out: PeerAnno[] = []
  for (const x of list) {
    if (x.target_type !== 'link' || x.key !== 'peer' || !x.value || typeof x.value !== 'object') continue
    const v = x.value as { a?: PeerEnd; b?: PeerEnd; external?: boolean; label?: string }
    if (!v.a || !v.b) continue
    out.push({ id: x.id, a: v.a, b: v.b, external: !!v.external || v.b.device_id == null, label: v.label ?? '', source: x.source })
  }
  return out
}

/** 待采纳的拓扑整理建议（GET /ai/suggestions 的条目，只取用到的字段）。 */
export interface PendingRef { id?: string; found?: boolean; type?: string | null; label?: string | null; device_id?: number | null }
export interface PendingSuggestion {
  id: number
  category: string
  kind: string
  status: string
  check_status: string
  content: Record<string, unknown> | null
  refs: PendingRef[]
}

export interface PendingHint { id: number; device_id: number; key: string; value: unknown }
export interface PendingPeer { id: number; a: number | null; b: number | null; aLabel: string; bLabel: string; external: boolean; label: string }

function refDevice(s: PendingSuggestion, rid: unknown): { id: number | null; label: string } {
  const r = s.refs.find((x) => x.id === rid)
  return { id: r?.device_id ?? null, label: String(r?.label ?? rid ?? '') }
}

/** 待采纳、没被拒绝的建议 → 角色 / 分组提示与推测对端。 */
export function pendingOf(list: PendingSuggestion[]): { hints: PendingHint[]; peers: PendingPeer[] } {
  const hints: PendingHint[] = []
  const peers: PendingPeer[] = []
  for (const s of list) {
    if (s.status !== 'pending' || s.check_status === 'reject' || !s.content) continue
    const c = s.content
    if (s.category === 'view_hint') {
      const d = refDevice(s, c.target)
      if (d.id != null) hints.push({ id: s.id, device_id: d.id, key: String(c.key ?? ''), value: c.value })
    } else if (s.category === 'peer_link') {
      const a = refDevice(s, c.a)
      const b = refDevice(s, c.b)
      peers.push({ id: s.id, a: a.id, b: b.id, aLabel: a.label, bLabel: b.label, external: !!c.external || b.id == null, label: String(c.label ?? '') })
    }
  }
  return { hints, peers }
}

/** 一台设备的状态角标（顺序由 lmi 按优先级排）。 */
export function badgesOf(o: { check?: boolean; cons?: boolean; stale?: boolean; ai?: boolean }): Badge[] {
  const out: Badge[] = []
  if (o.check) out.push('check')
  if (o.cons) out.push('cons')
  if (o.stale) out.push('stale')
  if (o.ai) out.push('ai')
  return out
}
