/** 知识库版本页面的纯逻辑：版本号建议、差异整理、回归结果、变更日志。 */

export type Bump = 'major' | 'minor' | 'patch'

export interface KbDiff {
  nodes_added: string[]
  nodes_removed: string[]
  nodes_semantic: string[]
  nodes_deprecated: string[]
  cards_added: string[]
  cards_removed: string[]
  cards_changed: string[]
  defaults_changed: { profile: string; node: string; old: unknown; new: unknown }[]
  profiles_added: string[]
  suggested_bump: Bump
}

export interface Release { version: string; tag: string; commit: string; time: number; message: string }
export interface Commit { commit: string; time: number; message: string }
export interface ReleasesData { releases: Release[]; history: Commit[]; kb_version: string }
export interface DraftData { base: string | null; changes: KbDiff | null; commits: Commit[] }

export interface SampleResult {
  file: string
  gate?: boolean
  passed?: boolean
  ok: boolean
  error?: string
  profile?: string
  lines?: number
  unknown?: number
  coverage?: number
  diffs?: { line: number; original: string[]; rendered: string[] }[]
}
export interface Regression { samples: number; failed: number; results: SampleResult[]; kb_version?: string; at?: string }

/** 与后端 next_version 相同的规则。 */
export function nextVersion(current: string, bump: Bump): string {
  const p = [...current.split('.'), '0', '0', '0'].slice(0, 3).map((x) => parseInt(x, 10) || 0)
  if (bump === 'major') return `${p[0] + 1}.0.0`
  if (bump === 'minor') return `${p[0]}.${p[1] + 1}.0`
  return `${p[0]}.${p[1]}.${p[2] + 1}`
}

/** 留空时后端会采用的版本号：有发布时从上一版升级；首次发布时为当前 kb_version 升级（与后端一致）。 */
export function suggestVersion(base: string | null, kbVersion: string, bump: Bump): string {
  return nextVersion(base ?? kbVersion ?? '0.0.0', bump)
}

export const SEMVER = /^\d+\.\d+\.\d+$/

/** 差异里各类变化的数量（列表都按完整返回）。 */
export function diffCounts(d: KbDiff | null | undefined): Record<Exclude<keyof KbDiff, 'suggested_bump'>, number> & { total: number } {
  const keys = ['nodes_added', 'nodes_removed', 'nodes_semantic', 'nodes_deprecated', 'cards_added', 'cards_removed', 'cards_changed', 'defaults_changed', 'profiles_added'] as const
  const out = { total: 0 } as Record<(typeof keys)[number], number> & { total: number }
  for (const k of keys) {
    out[k] = d?.[k]?.length ?? 0
    out.total += out[k]
  }
  return out
}

/** 草稿区修改表的一行。kind 决定标签文案，bump 是这一类变化带来的版本影响。 */
export interface ChangeRow { kind: string; bump: Bump; id: string; profile?: string; old?: unknown; new?: unknown }

const KIND_BUMP: [keyof KbDiff, string, Bump][] = [
  ['nodes_removed', 'nodeRemoved', 'major'],
  ['nodes_semantic', 'nodeSemantic', 'major'],
  ['nodes_added', 'nodeAdded', 'minor'],
  ['profiles_added', 'profileAdded', 'minor'],
  ['cards_added', 'cardAdded', 'minor'],
  ['nodes_deprecated', 'nodeDeprecated', 'patch'],
  ['cards_removed', 'cardRemoved', 'patch'],
  ['cards_changed', 'cardChanged', 'patch'],
]

/** 把差异展开成表格行（按版本影响从大到小）；默认值变化带 Profile 与新旧值。 */
export function changeRows(d: KbDiff | null | undefined): ChangeRow[] {
  if (!d) return []
  const rows: ChangeRow[] = []
  for (const [key, kind, bump] of KIND_BUMP) for (const id of (d[key] as string[]) ?? []) rows.push({ kind, bump, id })
  for (const c of d.defaults_changed ?? []) rows.push({ kind: 'defaultChanged', bump: 'patch', id: c.node, profile: c.profile, old: c.old, new: c.new })
  const rank: Record<Bump, number> = { major: 0, minor: 1, patch: 2 }
  return rows.sort((a, b) => rank[a.bump] - rank[b.bump])
}

/** 版本影响规则中每档的数量（用于高亮当前生效的那一档）。 */
export function bumpCounts(d: KbDiff | null | undefined): Record<Bump, number> {
  const out: Record<Bump, number> = { major: 0, minor: 0, patch: 0 }
  for (const r of changeRows(d)) out[r.bump]++
  return out
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** 秒级时间戳 → 本地 “YYYY-MM-DD HH:mm”。 */
export function fmtTime(sec: number | string | null | undefined): string {
  if (sec === null || sec === undefined || sec === '') return ''
  const d = typeof sec === 'number' ? new Date(sec * 1000) : new Date(sec)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 回归：按 “门槛样本失败 → 非门槛失败 → 通过” 排序；passed 缺省时按 ok 判断。 */
export function samplePassed(r: SampleResult): boolean {
  return r.passed ?? r.ok
}
export function sortSamples(rs: SampleResult[]): SampleResult[] {
  const w = (r: SampleResult) => (samplePassed(r) ? 2 : r.gate === false ? 1 : 0)
  return [...rs].sort((a, b) => w(a) - w(b))
}

/** 最近一次回归是否早于草稿区的最后一次提交（之后又改过知识库，结果可能已过时）。 */
export function regressionStale(reg: Regression | null | undefined, commits: Commit[]): boolean {
  if (!reg?.at || !commits.length) return false
  const at = new Date(reg.at).getTime() / 1000
  return commits.some((c) => c.time > at)
}

/** 变更日志：每个发布版本包含从它的提交到上一个发布之间的提交；最新发布之后的提交归入未发布（version=null）。 */
export interface LogEntry { version: string | null; release: Release | null; commits: Commit[] }
export function changelog(releases: Release[], history: Commit[]): LogEntry[] {
  const byCommit = new Map<string, Release>()
  for (const r of releases) byCommit.set(r.commit.slice(0, 12), r)
  const out: LogEntry[] = []
  let cur: LogEntry = { version: null, release: null, commits: [] }
  for (const c of history) {
    const r = byCommit.get(c.commit.slice(0, 12))
    if (r) {
      if (cur.commits.length || cur.release) out.push(cur)
      cur = { version: r.version, release: r, commits: [] }
    }
    cur.commits.push(c)
  }
  if (cur.commits.length || cur.release) out.push(cur)
  // 历史只取了最近若干条：没出现在历史里的旧版本也列出来（没有提交明细）
  const seen = new Set(out.map((e) => e.version))
  for (const r of releases) if (!seen.has(r.version)) out.push({ version: r.version, release: r, commits: [] })
  return out
}

/** 发布失败（409）时 e.data 的几种形态。 */
export type ReleaseFailure =
  | { type: 'invalid'; issues: { level: string; code: string; message: string; file?: string }[] }
  | { type: 'regression'; regression: Regression }
  | { type: 'exists'; version: string }
  | { type: 'other' }
export function releaseFailure(data: unknown): ReleaseFailure {
  if (Array.isArray(data)) {
    const errors = data.filter((i) => i && i.level === 'error')
    return { type: 'invalid', issues: errors.length ? errors : data }
  }
  if (data && typeof data === 'object' && 'results' in data) return { type: 'regression', regression: data as Regression }
  if (typeof data === 'string' && data) return { type: 'exists', version: data }
  return { type: 'other' }
}

/** 导入预览（dry_run）的结果。 */
export interface ImportPlan { kb_version: string; added: string[]; unchanged: string[]; conflicts: string[]; issues: { level?: string; code?: string; message: string; file?: string }[]; applied: boolean; review_items?: number[] }
