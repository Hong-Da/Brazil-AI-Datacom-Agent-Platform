/**
 * 特性能力查询页（REQ-023）的纯逻辑：格子的支持标记、按功能域分组、按可见 Profile 重新判断差异、一句话结论、Profile 对比的排序与 CSV。
 * 后端接口：GET /features、/features/detail、/features/diff（结构见 docs/api.md）。结论全部来自知识库，不经过 AI。
 */

export type L3 = Partial<Record<'zh-CN' | 'en' | 'pt-BR', string>>
export interface ProfileInfo { id: string; title: string; vendor: string; family: string; platform: string; software: string; inherits: string | null }
export interface PCell {
  state: 'supported' | 'unsupported' | 'unfilled'
  default?: unknown
  cards?: string[]
  syntax?: string[]
  undo?: string[]
  views?: string[]
  credibility?: string
  source?: string
  sources?: { doc?: string; file?: string; title?: string; line?: number; version?: string; patched?: string }[]
  verified?: string
  inherited?: boolean
  origin?: string
  when?: Record<string, string>
}
export interface Feature {
  node: string
  domain: string
  type: string
  parent?: string
  semantic: L3
  range: unknown
  choices: unknown
  secret?: boolean
  kind: 'same' | 'differs' | 'gap'
  score?: number
  profiles: Record<string, PCell>
}
export interface FeaturesResult {
  q: string
  profiles: ProfileInfo[]
  items: Feature[]
  total: number
  truncated: boolean
  hidden_same: number
  counts: Record<string, Record<string, number>>
  kb_version: string
}
export interface DiffRow { node: string; domain: string; type: string; semantic: L3; kind: 'default' | 'only_a' | 'only_b' | 'unfilled' | 'same'; syntax_differs: boolean; a: PCell; b: PCell }
export interface DiffResult { a: ProfileInfo; b: ProfileInfo; domain: string | null; counts: Record<string, number>; hidden_same: number; rows: DiffRow[]; kb_version: string }

export type Sup = 'y' | 'n' | 'u' | 'i'
/** 格子的支持标记：继承来的支持结论显示为 ↑（D-0093：继承格子保持“↑ + 默认值”）。 */
export function supOf(c: PCell | undefined): Sup {
  if (!c || c.state === 'unfilled') return 'u'
  if (c.state === 'unsupported') return 'n'
  return c.inherited ? 'i' : 'y'
}
export const supported = (c: PCell | undefined) => c?.state === 'supported'

export function showDefault(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** 按可见的 Profile 重新判断：same 全部相同 / differs 支持或默认值不同 / gap 有未填写。 */
export function kindFor(f: Feature, pids: string[]): Feature['kind'] {
  const cells = pids.map((p) => f.profiles[p])
  if (cells.some((c) => !c || c.state === 'unfilled')) return 'gap'
  const sig = new Set(cells.map((c) => `${c!.state}|${showDefault(c!.default)}`))
  return sig.size > 1 ? 'differs' : 'same'
}

/** 默认值与第一个支持的列不同（格子里标琥珀色）。 */
export function defaultDiffers(f: Feature, pids: string[], pid: string): boolean {
  const first = pids.map((p) => f.profiles[p]).find((c) => supported(c) && c!.default !== null && c!.default !== undefined)
  const c = f.profiles[pid]
  if (!first || !supported(c) || c.default === null || c.default === undefined) return false
  return showDefault(c.default) !== showDefault(first.default)
}

export function groupByDomain<T extends { domain: string }>(items: T[], order: string[]): { domain: string; items: T[] }[] {
  const m = new Map<string, T[]>()
  for (const it of items) {
    const d = it.domain || 'other'
    if (!m.has(d)) m.set(d, [])
    m.get(d)!.push(it)
  }
  const idx = (d: string) => { const i = order.indexOf(d); return i < 0 ? 999 : i }
  return [...m.entries()].sort((a, b) => idx(a[0]) - idx(b[0]) || a[0].localeCompare(b[0])).map(([domain, items]) => ({ domain, items }))
}

export interface Answer { feature: Feature; total: number; supported: string[]; unsupported: string[]; unfilled: string[]; defaults: string[]; syntaxByFamily: { family: string; pid: string; syntax: string }[] }

/** 搜索的一句话结论（由知识库计算）：取得分最高的特性，统计可见 Profile 中的支持情况、默认值与各平台族的写法。 */
export function quickAnswer(items: Feature[], profiles: ProfileInfo[]): Answer | null {
  if (!items.length) return null
  const f = [...items].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0]
  const pids = profiles.map((p) => p.id)
  const sup = pids.filter((p) => supported(f.profiles[p]))
  const defs = [...new Set(sup.map((p) => f.profiles[p].default).filter((v) => v !== null && v !== undefined).map(showDefault))]
  const byFam: Answer['syntaxByFamily'] = []
  for (const p of profiles) {
    const c = f.profiles[p.id]
    if (supported(c) && c.syntax?.length && !byFam.some((x) => x.family === p.family)) byFam.push({ family: p.family, pid: p.id, syntax: c.syntax[0] })
  }
  return {
    feature: f,
    total: pids.length,
    supported: sup,
    unsupported: pids.filter((p) => f.profiles[p]?.state === 'unsupported'),
    unfilled: pids.filter((p) => !f.profiles[p] || f.profiles[p].state === 'unfilled'),
    defaults: defs,
    syntaxByFamily: byFam,
  }
}

/** 命令语法着色：<参数> 与 { | } [ ] 分开。 */
export function synParts(s: string): { s: string; c: '' | 'pm' | 'op' }[] {
  const out: { s: string; c: '' | 'pm' | 'op' }[] = []
  const re = /(<[^>]+>)|([[\]{}|])/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({ s: s.slice(last, m.index), c: '' })
    out.push({ s: m[0], c: m[1] ? 'pm' : 'op' })
    last = m.index + m[0].length
  }
  if (last < s.length) out.push({ s: s.slice(last), c: '' })
  return out
}

export const DIFF_ORDER = ['default', 'only_a', 'only_b', 'unfilled', 'same'] as const

/** 对比表排序：默认值不同 → 只有 A → 只有 B → 一边未填写 → 相同（只是写法不同）。 */
export function sortDiff(rows: DiffRow[]): DiffRow[] {
  return [...rows].sort((x, y) => DIFF_ORDER.indexOf(x.kind) - DIFF_ORDER.indexOf(y.kind) || x.node.localeCompare(y.node))
}

/** 对比表 CSV（表头三语之一，由调用方给出）。 */
export function diffCsvRows(rows: DiffRow[], head: string[], kindName: (k: string) => string, stateName: (s: string) => string): string[][] {
  const side = (c: PCell) => (c.state === 'supported' ? [(c.syntax ?? []).join(' / '), showDefault(c.default)] : [stateName(c.state), ''])
  return [head, ...rows.map((r) => [r.node, r.domain, kindName(r.kind), ...side(r.a), ...side(r.b)])]
}
