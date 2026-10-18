import { toCsv } from './csv'
import { formatDefault } from './format'
import type { CompareKind, CompareResult, CompareRow } from './types'

/** 翻译告警分类：支持情况不同 → 不支持告警；默认值不同 → 默认值差异；一边未填写 → 知识库缺口。 */
export type Warn = 'unsupported' | 'default' | 'unfilled' | 'none'

export function warnOf(kind: CompareKind): Warn {
  if (kind === 'only_a' || kind === 'only_b') return 'unsupported'
  if (kind === 'default') return 'default'
  if (kind === 'unfilled') return 'unfilled'
  return 'none'
}

export function filterCompare(rows: CompareRow[], onlyDiff: boolean, q = ''): CompareRow[] {
  const s = q.trim().toLowerCase()
  return rows.filter((r) => (!onlyDiff || r.kind !== 'same') && (!s || r.node.toLowerCase().includes(s)))
}

export interface CompareSummary { total: number; support: number; default: number; unfilled: number; same: number }

export function compareSummary(c: CompareResult): CompareSummary {
  const n = c.counts
  return { total: c.rows.length, support: n.only_a + n.only_b, default: n.default, unfilled: n.unfilled, same: n.same }
}

/** 差异表 CSV：节点、功能域、两边的支持情况与默认值、告警类型。 */
export function compareCsv(c: CompareResult, rows: CompareRow[]): string {
  const head = ['node', 'domain', `${c.a} state`, `${c.a} default`, `${c.b} state`, `${c.b} default`, 'kind', 'warning']
  return toCsv([
    head,
    ...rows.map((r) => [r.node, r.domain, r.a.state, formatDefault(r.a.default), r.b.state, formatDefault(r.b.default), r.kind, warnOf(r.kind)]),
  ])
}
