import { toCsv } from './csv'
import { formatDefault } from './format'
import type { Cred, CoverageResult, EntryState, ProfileDetail, Scalar } from './types'

/** 覆盖矩阵：/kb/coverage 给出每个格子的状态，/kb/profiles/{id} 补上可信度、是否继承与默认值。 */

export interface CovCell { state: EntryState; cred?: Cred; inherited?: boolean; origin?: string; default?: Scalar }

export interface VendorDefault { vendor: string; value: string }

export interface CovRow {
  node: string
  domain: string
  type: string
  semantic: Record<string, string>
  deprecated: boolean
  cells: Record<string, CovCell>
  gap: boolean
  /** 一家厂商支持、另一家明确不支持（翻译时告警） */
  supportDiff: boolean
  /** 各厂商默认值不同时列出每家的默认值 */
  defaultDiff: VendorDefault[] | null
}

export function buildCoverage(
  cov: CoverageResult,
  details: Record<string, ProfileDetail | undefined>,
  vendors: Record<string, string>,
): CovRow[] {
  const meta = new Map<string, { domain: string; type: string; semantic: Record<string, string>; deprecated: boolean }>()
  const entry = new Map<string, Map<string, ProfileDetail['entries'][number]>>()
  for (const [pid, d] of Object.entries(details)) {
    if (!d) continue
    const m = new Map<string, ProfileDetail['entries'][number]>()
    for (const e of d.entries) {
      m.set(e.node, e)
      if (!meta.has(e.node)) meta.set(e.node, { domain: e.domain, type: e.type, semantic: e.semantic, deprecated: e.deprecated })
    }
    entry.set(pid, m)
  }
  return Object.keys(cov.matrix)
    .sort()
    .map((node) => {
      const m = meta.get(node) ?? { domain: node.split('.')[0], type: '', semantic: {}, deprecated: false }
      const cells: Record<string, CovCell> = {}
      for (const pid of cov.profiles) {
        const state = cov.matrix[node]?.[pid] ?? 'unfilled'
        const e = entry.get(pid)?.get(node)
        cells[pid] = e && state !== 'unfilled'
          ? { state, cred: e.credibility, inherited: e.inherited, origin: e.origin, default: e.default ?? null }
          : { state }
      }
      const states = Object.values(cells).map((c) => c.state)
      return {
        node,
        ...m,
        cells,
        gap: states.includes('unfilled'),
        supportDiff: supportDiff(cells, vendors),
        defaultDiff: defaultDiff(cells, vendors),
      }
    })
}

/** 每家厂商的支持情况：任一 Profile 支持算支持，否则有明确不支持算不支持；未填写不算差异（那是缺口）。 */
export function supportDiff(cells: Record<string, CovCell>, vendors: Record<string, string>): boolean {
  const states = new Map<string, Set<EntryState>>()
  for (const [pid, c] of Object.entries(cells)) {
    const v = vendors[pid] ?? ''
    states.set(v, (states.get(v) ?? new Set()).add(c.state))
  }
  const vals = [...states.values()].map((s) => (s.has('supported') ? 'supported' : s.has('unsupported') ? 'unsupported' : 'unfilled'))
  return vals.includes('supported') && vals.includes('unsupported')
}

/** 各厂商（取该厂商第一个有默认值的 Profile）默认值不同则返回每家的默认值。 */
export function defaultDiff(cells: Record<string, CovCell>, vendors: Record<string, string>): VendorDefault[] | null {
  const byVendor = new Map<string, string>()
  for (const [pid, c] of Object.entries(cells)) {
    const v = vendors[pid] ?? ''
    if (c.state !== 'supported' || c.default === null || c.default === undefined || byVendor.has(v)) continue
    byVendor.set(v, formatDefault(c.default))
  }
  if (byVendor.size < 2 || new Set(byVendor.values()).size < 2) return null
  return [...byVendor.entries()].map(([vendor, value]) => ({ vendor, value }))
}

export interface CovFilter {
  q: string
  domain: string
  cred: '' | Cred
  gapsOnly: boolean
  diffOnly: boolean
  showDeprecated: boolean
}

/** formOf：节点在当前显示风格下的命令写法（REQ-026），给出时搜索也匹配它。 */
export function filterCoverage(rows: CovRow[], f: CovFilter, formOf?: (r: CovRow) => string): CovRow[] {
  const q = f.q.trim().toLowerCase()
  return rows.filter((r) => {
    if (r.deprecated && !f.showDeprecated) return false
    if (q && !r.node.toLowerCase().includes(q) && !(formOf?.(r) ?? '').toLowerCase().includes(q)) return false
    if (f.domain && r.domain !== f.domain) return false
    if (f.gapsOnly && !r.gap) return false
    if (f.diffOnly && !r.supportDiff && !r.defaultDiff) return false
    const cells = Object.values(r.cells)
    if (f.cred === 'verified') {
      const sup = cells.filter((c) => c.state === 'supported' && c.cred !== undefined)
      if (!sup.length || sup.some((c) => c.cred !== 'verified')) return false
    } else if (f.cred && !cells.some((c) => c.cred === f.cred)) return false
    return true
  })
}

export function groupByDomain(rows: CovRow[]): { domain: string; rows: CovRow[] }[] {
  const out = new Map<string, CovRow[]>()
  for (const r of rows) out.set(r.domain, [...(out.get(r.domain) ?? []), r])
  return [...out.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([domain, rows]) => ({ domain, rows }))
}

/** 功能域内某个 Profile 的覆盖率（不含已废弃节点）与缺口数。 */
export function domainStats(all: CovRow[], domain: string, pid: string): { pct: number; gaps: number } {
  const rows = all.filter((r) => r.domain === domain && !r.deprecated)
  const gaps = rows.filter((r) => r.cells[pid]?.state === 'unfilled').length
  return { pct: rows.length ? Math.round(((rows.length - gaps) / rows.length) * 100) : 0, gaps }
}

export interface CovSummary { nodes: number; domains: number; gaps: number; diffs: number; draft: number }

export function coverageSummary(all: CovRow[]): CovSummary {
  const live = all.filter((r) => !r.deprecated)
  return {
    nodes: live.length,
    domains: new Set(live.map((r) => r.domain)).size,
    gaps: live.filter((r) => r.gap).length,
    diffs: live.filter((r) => r.supportDiff || r.defaultDiff).length,
    draft: live.filter((r) => Object.values(r.cells).some((c) => c.cred === 'draft')).length,
  }
}

function cellText(c: CovCell): string {
  if (c.state !== 'supported') return c.state
  return [c.state, c.cred, c.inherited ? `inherited:${c.origin}` : ''].filter(Boolean).join(' ')
}

export function coverageCsv(rows: CovRow[], pids: string[]): string {
  return toCsv([
    ['node', 'domain', 'type', 'deprecated', ...pids, 'support_diff', 'default_diff'],
    ...rows.map((r) => [
      r.node,
      r.domain,
      r.type,
      r.deprecated,
      ...pids.map((p) => cellText(r.cells[p] ?? { state: 'unfilled' })),
      r.supportDiff,
      r.defaultDiff ? r.defaultDiff.map((d) => `${d.vendor}=${d.value}`).join(' / ') : '',
    ]),
  ])
}
