/** AI 用量统计（REQ-040 追加）：时间范围、查询参数、按天柱状图的几何、汇总表。 */

export interface UsageRow { key: string; id?: number | null; calls: number; errors: number; tokens_in: number; tokens_out: number }
export type Group = 'day' | 'user' | 'connection' | 'feature' | 'model'
export const BREAKDOWNS = ['user', 'connection', 'feature', 'model'] as const
export type Breakdown = (typeof BREAKDOWNS)[number]

/** GET /ai/usage */
export interface Usage {
  from: string
  to: string
  scope: 'all' | 'mine'
  totals: Omit<UsageRow, 'key' | 'id'>
  by_day: UsageRow[]
  by_user: UsageRow[]
  by_connection: UsageRow[]
  by_feature: UsageRow[]
  by_model: UsageRow[]
}

export const PRESETS = [7, 30, 90] as const

/** YYYY-MM-DD（按 UTC 日期，与后端一致）。 */
export function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10)
}

/** 最近 n 天（含今天）。 */
export function lastDays(n: number, today = new Date()): { from: string; to: string } {
  const to = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))
  const from = new Date(to.getTime() - (n - 1) * 86_400_000)
  return { from: isoDay(from), to: isoDay(to) }
}

export function validRange(from: string, to: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && from <= to
}

export interface UsageParams { from: string; to: string; user?: string; connectionId?: number | null; group?: Group }

/** 查询字符串（空值不带）。 */
export function usageQuery(p: UsageParams): string {
  const q = new URLSearchParams()
  q.set('from', p.from)
  q.set('to', p.to)
  if (p.group) q.set('group', p.group)
  if (p.user) q.set('user', p.user)
  if (p.connectionId != null) q.set('connection_id', String(p.connectionId))
  return q.toString()
}

export function csvName(group: Group, from: string, to: string): string {
  return `ai-usage-${group}-${from}-${to}.csv`
}

export const total = (r: Pick<UsageRow, 'tokens_in' | 'tokens_out'>): number => r.tokens_in + r.tokens_out

/** 坐标轴的上限：1 / 2 / 5 × 10^k，不小于最大值。 */
export function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p
  return 10 * p
}

export interface Bar { key: string; x: number; w: number; hIn: number; hOut: number; row: UsageRow }

/** 按天堆叠柱（输入在下、输出在上）：宽 width、高 height 的绘图区，柱间留 gap。 */
export function dayBars(rows: UsageRow[], width: number, height: number, gap = 2): { bars: Bar[]; max: number } {
  const max = niceMax(Math.max(0, ...rows.map(total)))
  const n = Math.max(1, rows.length)
  const slot = width / n
  const w = Math.max(1, slot - gap)
  const bars = rows.map((r, i) => ({
    key: r.key,
    x: i * slot + (slot - w) / 2,
    w,
    hIn: (r.tokens_in / max) * height,
    hOut: (r.tokens_out / max) * height,
    row: r,
  }))
  return { bars, max }
}

/** x 轴上显示的日期标签：最多约 maxLabels 个，均匀取，首尾都在。 */
export function labelIdx(n: number, maxLabels = 7): number[] {
  if (n <= 0) return []
  if (n <= maxLabels) return [...Array(n).keys()]
  const step = Math.ceil((n - 1) / (maxLabels - 1))
  const out: number[] = []
  for (let i = 0; i < n; i += step) out.push(i)
  if (out[out.length - 1] !== n - 1) {
    if (n - 1 - out[out.length - 1] < step / 2) out.pop()
    out.push(n - 1)
  }
  return out
}

/** 汇总表的占比（相对第一名）。 */
export function shareOf(rows: UsageRow[]): number[] {
  const m = Math.max(1, ...rows.map(total))
  return rows.map((r) => total(r) / m)
}

export function shortDay(day: string): string {
  return day.slice(5)
}
