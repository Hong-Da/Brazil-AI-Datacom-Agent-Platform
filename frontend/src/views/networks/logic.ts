import { activityKey } from '@/project/scope'

/**
 * M9（REQ-045）项目内的网络：前端的类型与纯逻辑（识别色、列表排序与文件夹、搜索、标识、共用矩阵、汇总页的指标、
 * 网络外的对端、成员的加入方式）。数据来自 /projects/<项目>/networks 等接口（见 docs/project-spec.md“M9 后端结果”）。
 */

/** 识别色的 8 个键（后端 networks.PALETTE 的顺序）；明 / 暗色值在 styles/m9.css 的 --n-<键>。 */
export const PALETTE = ['slate', 'indigo', 'green', 'rust', 'teal', 'violet', 'amber', 'rose'] as const
export type NetColor = (typeof PALETTE)[number]

export interface NetBrief { id: number; slug: string; name: string; color: string; default: boolean }
export interface NetFindings { error: number; warning: number; info: number; devices_checked: number; last_run: string | null }
export interface NetCounts {
  devices: number
  shared: number
  pinned: number
  scripts: number
  scripts_with_errors: number
  check_groups: number
  ai_pending: number
  annotations: number
  ignores: number
  overrides: number
  rules: number
  findings: NetFindings
}
export interface NetActivity { actor?: string | null; action: string; at: string }
export interface NetRow extends NetBrief {
  description: string | null
  folder_id: number | null
  folder: string | null
  position: number
  copied_from: { network_id: number; slug: string; name: string; at: string } | null
  last_activity: NetActivity | null
  created_by: string | null
  created_at: string | null
  updated_at: string | null
  counts: NetCounts
  rules?: JoinRule[]
}
export interface NetFolder { id: number; name: string; position: number; networks: string[] }
export interface NetOverview { devices: number; networks: number; in_several: number; only_default: number; imported_today: number; joined_by_rule_today: number }
export interface NetList { networks: NetRow[]; folders: NetFolder[]; palette: string[]; current: string | null; overview: NetOverview }

export interface JoinRule { id: number; kind: 'name' | 'subnet'; pattern: string; enabled: boolean; created_by?: string | null; created_at?: string | null }
export interface RuleList { network: NetBrief; all_new_devices: boolean; rules: JoinRule[]; excluded: { id: number; name: string }[] }
export interface RulePreview {
  kind: string
  pattern: string
  matches: number
  not_in_network: number
  excluded: number
  devices: { id: number; name: string; mgmt_address: string | null; state: 'member' | 'excluded' | 'outside' }[]
  mgmt_available: boolean
}
export interface DevNet extends NetBrief { policy?: 'follow' | 'pin'; version_id?: number | null }
export interface Member {
  device_id: number
  name: string
  vendor: string | null
  platform: string | null
  profile: string | null
  source: 'private' | 'public'
  versions: number
  latest_version_id: number | null
  latest_seq: number | null
  policy: 'follow' | 'pin'
  version_id: number | null
  seq: number | null
  newer_available: boolean
  also_in: DevNet[]
  join_source: string
  rule: JoinRule | null
  joined_by: string | null
  joined_at: string | null
  mgmt_address?: string | null
}
export interface MemberList { network: NetBrief; members: Member[]; total: number }
export interface WorkCounts {
  members: number
  rules: number
  annotations: number
  ignores: number
  overrides: number
  check_groups: number
  scripts: number
  revisions: number
  ai_batches: number
  ai_suggestions: number
  ai_adopted: number
}
export interface DeletePreview { network: NetBrief; deletable: boolean; counts: WorkCounts }

export type Basis = 'components' | 'igp' | 'bgp' | 'name' | 'subnet' | 'ai'
export const BASES: readonly Basis[] = ['components', 'igp', 'bgp', 'name', 'subnet', 'ai']
export interface Suggestion {
  key: string
  name: string
  slug: string
  devices: { id: number; name: string }[]
  count: number
  overlap_existing: (NetBrief & { devices: number })[]
  same_as: NetBrief | null
  overlap_suggestions: string[]
  overlap_devices: number[]
  rule: { kind: 'name' | 'subnet'; pattern: string } | null
  suggestion_ids?: number[] | null
  check: { status: 'pass' | 'reject'; reasons: unknown[] }
  adoptable: boolean
}
export interface SuggestResult { basis: Basis; params: Record<string, unknown>; suggestions: Suggestion[]; total: number; devices: number; ai_configured?: boolean; source?: unknown }
export interface AdoptResult { basis: Basis; created: { key: string; network: NetBrief }[]; skipped: { key: string; reason: string }[] }

/** 拓扑：网络外的对端（GET|POST …/topology 的 outside.links）。 */
export interface OutsideLink {
  id: string
  type: string
  confidence?: string | null
  inside: { device: string; interface?: string | null; address?: string | null }
  peer: { device: string; device_id: number | null; interface?: string | null; address?: string | null; networks: NetBrief[] }
}

// ---------------------------------------------------------------- 识别色与名称

/** 网络的识别色类（.nc-<键>，设置 --nc / --nci）；全部设备用项目蓝 nc-all。 */
export function colorClass(color: string | null | undefined): string {
  return `nc-${PALETTE.includes(color as NetColor) ? color : 'slate'}`
}

/** 升级时建的默认网络名称是中文“默认网络”；其他语言里显示译文（改过名的照原样）。 */
export const DEFAULT_NAME = '默认网络'
export function netName(n: Pick<NetBrief, 'name' | 'default'> | null | undefined, defaultLabel: string): string {
  if (!n) return ''
  return n.default && n.name === DEFAULT_NAME ? defaultLabel : n.name
}

/** 名称 → 网址里的标识（小写字母、数字、连字符）；没有可用字符时用 fallback。 */
export function slugify(name: string, fallback = 'net'): string {
  const s = name.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64)
  return s || fallback
}
export const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/

// ---------------------------------------------------------------- 列表与文件夹

/** 显示顺序：最外层（默认网络在前，再按位置），然后按文件夹顺序列出各文件夹里的网络。 */
export function netTree(list: Pick<NetList, 'networks' | 'folders'> | null): { root: NetRow[]; folders: { folder: NetFolder; nets: NetRow[] }[] } {
  if (!list) return { root: [], folders: [] }
  const byPos = (a: NetRow, b: NetRow) => Number(b.default) - Number(a.default) || a.position - b.position || a.id - b.id
  const fids = new Set(list.folders.map((f) => f.id))
  const root = list.networks.filter((n) => n.folder_id === null || !fids.has(n.folder_id)).sort(byPos)
  const folders = [...list.folders].sort((a, b) => a.position - b.position || a.id - b.id).map((f) => ({ folder: f, nets: list.networks.filter((n) => n.folder_id === f.id).sort(byPos) }))
  return { root, folders }
}
export function netOrder(list: Pick<NetList, 'networks' | 'folders'> | null): NetRow[] {
  const t = netTree(list)
  return [...t.root, ...t.folders.flatMap((f) => f.nets)]
}

/** 切换器的搜索：名称或标识包含关键字（不分大小写）；文件夹名称命中时列出整个文件夹。 */
export function matchNet(n: Pick<NetRow, 'name' | 'slug'>, q: string, folder?: string | null, label?: string): boolean {
  const k = q.trim().toLowerCase()
  if (!k) return true
  return [n.name, n.slug, label ?? '', folder ?? ''].some((x) => x.toLowerCase().includes(k))
}

// ---------------------------------------------------------------- 共用矩阵

/** 两两共用的设备数（对角线为网络自己的设备数）；devices 是项目层 /devices 每行的 networks。 */
export function overlapMatrix(nets: Pick<NetBrief, 'id'>[], devices: { networks?: Pick<NetBrief, 'id'>[] }[]): number[][] {
  const idx = new Map(nets.map((n, i) => [n.id, i]))
  const m = nets.map(() => nets.map(() => 0))
  for (const d of devices) {
    const ins = (d.networks ?? []).map((x) => idx.get(x.id)).filter((x): x is number => x !== undefined)
    for (const a of ins) for (const b of ins) m[a][b] += 1
  }
  return m
}

// ---------------------------------------------------------------- 全部设备时按网络的页面显示的汇总

/** 各页面在汇总里显示什么（GET /networks 的 counts）。 */
export type SumKind = 'findings' | 'scripts' | 'topology' | 'members' | 'devices'
export function sumKindOf(page: string): SumKind {
  if (page === 'check' || page === 'cleanup' || page === 'baseline' || page === 'consistency') return 'findings'
  if (page === 'scripts' || page === 'check-project') return 'scripts'
  if (page === 'topology') return 'topology'
  if (page === 'members') return 'members'
  return 'devices'
}

/** 汇总页按网络排序：默认网络在前，其余按列表顺序（同 netOrder）。 */
export function summaryRows(list: NetList | null): NetRow[] {
  return netOrder(list)
}

// ---------------------------------------------------------------- 拓扑：网络外的对端

export interface PeerStub { id: string; peer: string; peerId: number | null; networks: NetBrief[]; links: OutsideLink[]; inside: string[] }

/** 网络外的对端按对端设备归并（同一台对端的多条链路画成一个短线末端）。 */
export function peerStubs(links: OutsideLink[]): PeerStub[] {
  const by = new Map<string, PeerStub>()
  for (const l of links) {
    const k = l.peer.device
    let s = by.get(k)
    if (!s) {
      s = { id: `out:${k}`, peer: k, peerId: l.peer.device_id, networks: l.peer.networks ?? [], links: [], inside: [] }
      by.set(k, s)
    }
    s.links.push(l)
    if (!s.inside.includes(l.inside.device)) s.inside.push(l.inside.device)
  }
  return [...by.values()].sort((a, b) => a.peer.localeCompare(b.peer, undefined, { numeric: true }))
}

/** “显示网络外的对端”按账号与网络记在浏览器里（默认关）。 */
export function outsideKey(user: string | null | undefined, project: string | null | undefined, net: string | null | undefined): string {
  return `lmesh-net-outside:${user ?? ''}:${project ?? ''}:${net ?? ''}`
}

// ---------------------------------------------------------------- 成员

/** 加入方式 → 文案键与图标。 */
export function joinOf(source: string): { key: string; icon: string } {
  switch (source) {
    case 'upgrade':
    case 'default':
      return { key: 'default', icon: 'layers' }
    case 'rule':
      return { key: 'rule', icon: 'rules' }
    case 'suggestion':
      return { key: 'suggestion', icon: 'wand' }
    case 'copy':
      return { key: 'copy', icon: 'copy' }
    case 'import':
      return { key: 'import', icon: 'upload' }
    default:
      return { key: 'manual', icon: 'user' }
  }
}

/** 最近 24 小时内加入的成员（“今天加入”过滤）。 */
export function joinedRecently(m: Pick<Member, 'joined_at'>, now = Date.now()): boolean {
  if (!m.joined_at) return false
  const t = Date.parse(m.joined_at)
  return Number.isFinite(t) && now - t < 24 * 3600 * 1000
}

export type MemberFilter = '' | 'shared' | 'pin' | 'new'
export function filterMembers(list: Member[], q: string, f: MemberFilter, now = Date.now()): Member[] {
  const k = q.trim().toLowerCase()
  return list.filter((m) => {
    if (k && !`${m.name} ${m.mgmt_address ?? ''}`.toLowerCase().includes(k)) return false
    if (f === 'shared') return m.also_in.some((x) => !x.default)
    if (f === 'pin') return m.policy === 'pin'
    if (f === 'new') return joinedRecently(m, now)
    return true
  })
}

/** 设备名通配（* ?）是否命中，与后端 rule_matches 一致（不分大小写）。 */
export function globMatch(pattern: string, name: string): boolean {
  const re = new RegExp(`^${pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`, 'i')
  return re.test(name)
}

// ---------------------------------------------------------------- 最近活动

/** 网络的最近活动（last_activity.action）→ 文案键 net.act.<键>；映射不到返回 null（显示原文）。 */
export function netActivityKey(action: string | null | undefined): string | null {
  if (!action) return null
  if (action === 'create') return 'create'
  if (/^members\.(add|policy|remove)$/.test(action)) return action.replace('.', '_')
  if (/ \/view-annotations/.test(action)) return 'annotations'
  if (/ \/ai\//.test(action)) return 'ai'
  if (/^(PUT|DELETE) \/rules/.test(action)) return 'rules'
  return activityKey(action)
}

// ---------------------------------------------------------------- 设备页的网络过滤

export type NetDevFilter = string // '' | 'several' | 'only' | 'pin' | 'n:<网络>'
/**
 * 设备页按网络过滤（行的 networks 来自 /devices）：several 项目层 = 在两个以上非默认网络里、网络里 = 也在其他非默认网络；
 * only = 只在默认网络；pin = 本网络固定了版本；n:<标识> = 在那个网络里。
 */
export function netDevFilter<T extends { networks?: Pick<NetBrief, 'slug' | 'default'>[]; network_policy?: string }>(list: T[], f: NetDevFilter, cur: string | null = null): T[] {
  if (!f) return list
  return list.filter((d) => {
    const non = (d.networks ?? []).filter((x) => !x.default)
    if (f === 'several') return cur ? non.some((x) => x.slug !== cur) : non.length > 1
    if (f === 'only') return non.length === 0
    if (f === 'pin') return d.network_policy === 'pin'
    if (f.startsWith('n:')) return non.some((x) => x.slug === f.slice(2))
    return true
  })
}
