/**
 * 安全基线页（POST /api/v1/baseline、GET /baseline/rules、POST /baseline/report）的数据结构与纯逻辑：
 * 设备 × 规则矩阵、得分档、不符合项的证据行、参考命令合并、矩阵 CSV。
 */

export type Cell = 'pass' | 'fail' | 'na'
export type Severity = 'error' | 'warning' | 'info'
export type I18n = Record<string, string>

export interface Rule {
  id: string
  severity: Severity
  target: string
  domain: string
  tags: string[]
  profiles: string[]
  enabled: boolean
  title: I18n
  message: I18n
  suggestion: I18n
  remedy: { huawei?: string[]; cisco?: string[] }
  source: string
}
export interface Failure {
  rule: string
  severity: Severity
  node: string
  schema: string | null
  key: string
  lines: number[]
  evidence: string[]
  message: { key: string; params: Record<string, unknown> }
  suggestion: { key: string; params: Record<string, unknown> }
  remedy: string[]
}
export interface DeviceResult {
  device: string
  profile: string
  family: string
  style: string
  score: number
  summary: { pass: number; fail: number; na: number; failed_by_severity: Record<Severity, number>; has_errors: boolean }
  results: Record<string, Cell>
  failures: Failure[]
}
export interface BaselineInfo { id: string; title: I18n; description: I18n; includes: string[]; chain: string[]; rules?: number }
export interface BaselineResult {
  baseline: string
  baseline_info: BaselineInfo
  rules: Rule[]
  matrix: { rules: string[]; devices: string[]; cells: Cell[][] }
  devices: DeviceResult[]
  summary: { devices: number; rules: number; score: number; pass: number; fail: number; na: number; failures: number; has_errors: boolean; by_rule: Record<string, { pass: number; fail: number; na: number }> }
  texts: Record<string, I18n>
}
export interface RulesInfo { profiles: BaselineInfo[]; rules: Rule[]; total: number }

/** 得分档：< 70 低（红），< 95 中（琥珀），其余好（青）。 */
export function scoreBand(s: number): 'lo' | 'mid' | 'hi' {
  return s < 70 ? 'lo' : s < 95 ? 'mid' : 'hi'
}

/** 矩阵的一格。 */
export function cellOf(r: BaselineResult, rule: string, device: string): Cell {
  const i = r.matrix.rules.indexOf(rule)
  const j = r.matrix.devices.indexOf(device)
  return i < 0 || j < 0 ? 'na' : r.matrix.cells[i]?.[j] ?? 'na'
}

/** 有不符合项的设备数、不符合项按级别计数。 */
export function stripCounts(r: BaselineResult): { affected: number; bySev: Record<Severity, number> } {
  const bySev: Record<Severity, number> = { error: 0, warning: 0, info: 0 }
  let affected = 0
  for (const d of r.devices) {
    if (d.failures.length) affected++
    for (const f of d.failures) bySev[f.severity]++
  }
  return { affected, bySev }
}

/** 设备的不符合项按规则归组（同一规则可有多个实例），按严重度、规则顺序排序。 */
export function failuresByRule(d: DeviceResult, order: string[]): { rule: string; items: Failure[] }[] {
  const m = new Map<string, Failure[]>()
  for (const f of d.failures) m.set(f.rule, [...(m.get(f.rule) ?? []), f])
  const rank = { error: 0, warning: 1, info: 2 }
  return [...m.entries()]
    .map(([rule, items]) => ({ rule, items }))
    .sort((a, b) => rank[a.items[0].severity] - rank[b.items[0].severity] || order.indexOf(a.rule) - order.indexOf(b.rule))
}

/**
 * 一台设备的参考命令合起来（每条规则一段，前面一行注释写规则编号）；去掉重复的整段。
 * 只是参考命令，不是可直接下发的脚本（基线修复由人确认后走增量变更）。
 */
export function remedyText(d: DeviceResult, title: (rule: string) => string): string {
  const comment = d.family.startsWith('huawei') ? '#' : '!'
  const seen = new Set<string>()
  const out: string[] = []
  for (const f of d.failures) {
    const body = f.remedy.join('\n')
    if (!body || seen.has(body)) continue
    seen.add(body)
    out.push(`${comment} ${f.rule} ${title(f.rule)}`, ...f.remedy)
  }
  return out.join('\n')
}

/** 设备 × 规则矩阵 CSV（行 = 规则）。 */
export function matrixCsv(r: BaselineResult, title: (rule: string) => string): (string | number)[][] {
  const rows: (string | number)[][] = [['rule', 'severity', 'title', ...r.matrix.devices]]
  const sev = new Map(r.rules.map((x) => [x.id, x.severity]))
  r.matrix.rules.forEach((id, i) => rows.push([id, sev.get(id) ?? '', title(id), ...r.matrix.cells[i]]))
  rows.push(['score', '', '', ...r.matrix.devices.map((d) => r.devices.find((x) => x.device === d)?.score ?? '')])
  return rows
}
