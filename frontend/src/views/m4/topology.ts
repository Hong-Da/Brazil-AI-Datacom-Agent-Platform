/**
 * 拓扑与跨设备一致性页（POST /api/v1/consistency）的数据结构与纯逻辑：
 * 把同一对接口上的链路（同网段 + 其上的 OSPF / IS-IS / LDP / 接口 BFD）合成一条“邻接”，BGP、伪线、远端 LDP、静态 BFD 各自成线；
 * 每条线的状态取其中链路的最高级别；发现按链路归组；两端事实对比。
 */

export type Severity = 'error' | 'warning' | 'info'
export interface End { device: string; interface?: string | null; address?: string | null; node?: string | null; facts?: Record<string, unknown> }
export interface Link {
  id: string
  type: string
  a: End
  b: End
  vrf?: string
  segment?: string | null
  over?: string | null
  confidence: 'high' | 'medium' | 'low'
  basis: { rule: string; a_node?: string | null; b_node?: string | null; detail?: string }
  issues: string[]
  severity: Severity | null
  p2p?: boolean
  ibgp?: boolean
}
export interface TopoNode {
  id: string
  device_id: number | null
  version_id: number | null
  source: string
  profile: string
  family: string
  loopbacks: string[]
  lsr_id: string | null
  asn: string | null
  interfaces: number
  links: number
  issues: number
}
export interface FindingEnd { device: string; end: string; node: string | null; schema: string | null; value: unknown; lines: number[] }
export interface Finding {
  id: string
  rule: string
  severity: Severity
  domain: string
  link: string
  link_type: string
  device: string
  node: string | null
  lines: number[]
  devices: string[]
  ends: FindingEnd[]
  message: { key: string; params: Record<string, unknown> }
  suggestion: { key: string; params: Record<string, unknown> }
}
export interface Unresolved { type: string; device: string; node: string; address?: string }
export interface ConsistencyResult {
  nodes: TopoNode[]
  links: Link[]
  unresolved: Unresolved[]
  duplicates: unknown[]
  findings: Finding[]
  summary: {
    total: number
    by_severity: Record<Severity, number>
    topology: { devices: number; links: number; by_type: Record<string, number>; unresolved: number; duplicates: number }
  }
  rules_loaded: number
  rules_skipped: { id: string; missing: string[] }[]
  texts: Record<string, Record<string, string>>
}

export type Kind = 'phy' | 'bgp' | 'l2'
export type Status = 'ok' | 'warn' | 'bad'

/** 一条显示的线：同一对接口上的链路合在一起。 */
export interface Group { id: string; kind: Kind; links: Link[]; a: string; b: string; ai: string; bi: string; status: Status; issues: number; segment: string }

const RANK: Record<string, number> = { error: 3, warning: 2, info: 1 }
export const sevRank = (s: Severity | null | undefined) => (s ? RANK[s] ?? 0 : 0)
export function statusOf(sev: Severity | null | undefined): Status {
  return sev === 'error' ? 'bad' : sev ? 'warn' : 'ok'
}
export function maxSeverity(list: (Severity | null | undefined)[]): Severity | null {
  let best: Severity | null = null
  for (const s of list) if (sevRank(s) > sevRank(best)) best = s ?? null
  return best
}

const OVERLAY = new Set(['ospf', 'isis', 'ldp', 'bfd'])

/** 链路 → 显示的线。 */
export function groupLinks(links: Link[]): Group[] {
  const out = new Map<string, Group>()
  const mk = (l: Link, kind: Kind): Group => ({
    id: l.id, kind, links: [l], a: l.a.device, b: l.b.device, ai: l.a.interface ?? '', bi: l.b.interface ?? '', status: 'ok', issues: 0, segment: l.segment ?? '',
  })
  for (const l of links) if (l.type === 'subnet') out.set(l.id, mk(l, 'phy'))
  for (const l of links) {
    if (l.type === 'subnet') continue
    if (OVERLAY.has(l.type) && l.over && out.has(l.over)) out.get(l.over)!.links.push(l)
    else out.set(l.id, mk(l, l.type === 'bgp' ? 'bgp' : OVERLAY.has(l.type) && l.type !== 'bfd' ? 'phy' : 'l2'))
  }
  for (const g of out.values()) {
    g.status = statusOf(maxSeverity(g.links.map((l) => l.severity)))
    g.issues = g.links.reduce((n, l) => n + l.issues.length, 0)
  }
  return [...out.values()]
}

/** 链路编号 → 所在的线。 */
export function groupOfLink(groups: Group[]): Map<string, Group> {
  const m = new Map<string, Group>()
  for (const g of groups) for (const l of g.links) m.set(l.id, g)
  return m
}

/** 线上的协议标记（OSPF、IS-IS、LDP、BFD）。 */
export function protocols(g: Group): string[] {
  return g.links.filter((l) => l.type !== 'subnet').map((l) => l.type)
}

/** 两端事实对比：列出两端都有或一端有的事实，标出不同的。 */
export function factRows(l: Link): { k: string; a: string; b: string; diff: boolean }[] {
  const fa = l.a.facts ?? {}
  const fb = l.b.facts ?? {}
  const keys = [...new Set([...Object.keys(fa), ...Object.keys(fb)])]
  const show = (v: unknown) => (v === undefined || v === null || v === '' ? '—' : Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v))
  return keys.map((k) => {
    const a = show(fa[k])
    const b = show(fb[k])
    return { k, a, b, diff: a !== b && !['address', 'network', 'ip', 'local', 'peer'].includes(k) }
  })
}

export type SevFilter = '' | Severity

export function filterFindings(list: Finding[], sev: SevFilter, device = ''): Finding[] {
  return list
    .filter((f) => (!sev || f.severity === sev) && (!device || f.devices.includes(device)))
    .sort((a, b) => sevRank(b.severity) - sevRank(a.severity) || a.link.localeCompare(b.link))
}

/** 设备的线（含它是哪一端）。 */
export function groupsOf(groups: Group[], device: string): Group[] {
  return groups.filter((g) => g.a === device || g.b === device)
}

/** 短接口名（GigabitEthernet → GE 等），用于图上的标注。 */
export function shortIf(n: string): string {
  return n.replace(/^GigabitEthernet/i, 'GE').replace(/^TenGigabitEthernet/i, 'Te').replace(/^Port-channel/i, 'Po').replace(/^Eth-Trunk/i, 'Eth-Trunk').replace(/^LoopBack/i, 'Lo').replace(/^Loopback/i, 'Lo')
}

/** 一致性发现的 CSV 行（表头 + 每条发现一行）。 */
export function findingsCsv(list: Finding[], text: (f: Finding, k: 'message' | 'suggestion') => string): (string | number)[][] {
  const rows: (string | number)[][] = [['severity', 'rule', 'link_type', 'a_device', 'a_end', 'a_value', 'a_lines', 'b_device', 'b_end', 'b_value', 'b_lines', 'message', 'suggestion']]
  for (const f of list) {
    const [a, b] = [f.ends[0], f.ends[1]]
    const v = (e: FindingEnd | undefined) => (e ? [e.device, e.end, String(e.value ?? ''), e.lines.join(' ')] : ['', '', '', ''])
    rows.push([f.severity, f.rule, f.link_type, ...v(a), ...v(b), text(f, 'message'), text(f, 'suggestion')])
  }
  return rows
}
