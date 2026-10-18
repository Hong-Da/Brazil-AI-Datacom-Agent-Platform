/**
 * AI 查询与护栏页（REQ-024）的纯逻辑：查询语句着色、逐句核对状态、护栏五个阶段的状态、问题分组、交给增量变更的暂存。
 * 后端接口：GET /ask/status、POST /ask、POST /generate、POST /guard（结构见 docs/api.md）。
 * AI 的输出只在代码核对之后显示：回答的每句话带核对状态，生成的配置逐行带护栏结论。
 */

export interface AskStatus { configured: boolean; status: 'ready' | 'not_configured'; provider: string | null; models: { ask: string | null; generate: string | null }; sanitize: string; guard_without_ai: boolean; grammar?: { syntax: string } }
export interface QCell { value: unknown; origin: string; nodes: string[]; lines: number[]; secret?: boolean }
export interface QRow { n: number; device: string; device_id: number | null; version_id: number | null; node: string; schema: string; key: unknown; label: string; lines: number[]; cells: Record<string, QCell> }
export interface QueryResult { text: string; object: string; columns: { field: string; schema: string | null; type: string; secret: boolean }[]; rows: QRow[]; count: number; truncated?: boolean }
export interface Fact { row: number; field: string; value: unknown; actual: unknown; ok: boolean; node?: string }
export interface Statement { text: string; cites: number[]; facts: Fact[]; count: unknown; status: 'passed' | 'corrected' | 'unverifiable'; issues: { key: string; params: Record<string, unknown> }[]; corrected_text: string | null; nodes: string[] }
export interface Sent { step: string; system: string; prompt: string; reply?: string }
export interface AiInfo { model: string; calls: number; tokens_in: number; tokens_out: number; ms: number }
export interface AskResult {
  question: string
  question_sent: string
  attempts: { query: string; error: { key: string; params: Record<string, unknown> } | null }[]
  status: 'answered' | 'query_invalid'
  query_text?: string
  result: QueryResult | null
  answer: { statements: Statement[]; summary: Record<string, number> } | null
  sent: Sent[]
  ai: AiInfo
}
export interface GuardIssue { id: string; status: 'bad' | 'warn' | 'ok'; stage: 'parse' | 'deps' | 'template' | 'conflict'; rule: string; line: number | null; lines: number[]; message: { key: string; params: Record<string, unknown> }; text: string; fix?: string }
export interface GuardLine { no: number; text: string; status: 'ok' | 'bad' | 'warn' | 'ctx' | 'skip'; kind: string; card: string | null; issues: string[]; nodes: string[] }
export interface GuardResult {
  device: string
  profile: string
  family: string
  verdict: 'passed' | 'blocked'
  lines: GuardLine[]
  issues: GuardIssue[]
  stages: Record<string, { status: 'ok' | 'bad' | 'warn' | 'skipped'; bad: number; warn: number; lines?: number }>
  summary: { lines: number; bad: number; warn: number; ok: number; skipped: number }
  script?: { available: boolean; script?: string; script_plain?: string; rollback?: string; verify_ok?: boolean; ops?: number; reason?: string }
  merged_text?: string
  error?: { key: string; params: Record<string, unknown> }
}
export interface GenerateResult { request: string; request_sent: string; device: string; profile: string; rounds: { round: number; text: string; guard: GuardResult }[]; final: { round: number; text: string; guard: GuardResult }; verdict: string; sent: Sent[]; ai: AiInfo }

export type Vs = 'ok' | 'bad' | 'fix' | 'na'
/** 逐句核对状态 → 样式：通过 ✓、被更正（原句划掉）✕、无法校验 ?。 */
export const stmtCls = (s: Statement['status']): 'ok' | 'bad' | 'na' => (s === 'passed' ? 'ok' : s === 'corrected' ? 'bad' : 'na')

export function stmtCounts(st: Statement[]): { passed: number; corrected: number; unverifiable: number } {
  const c = { passed: 0, corrected: 0, unverifiable: 0 }
  for (const s of st) c[s.status]++
  return c
}

const KW = /\b(FIND|ON|WHERE|AND|RETURN|WITH|DEFAULTS|LIMIT|EXISTS|NOT|IN)\b/g
/** 查询语句着色：关键字与字符串分开（片段数组，模板里逐段渲染）。 */
export function queryParts(text: string): { s: string; c: '' | 'k' | 's' }[] {
  const out: { s: string; c: '' | 'k' | 's' }[] = []
  const re = new RegExp(`${KW.source}|("(?:[^"\\\\]|\\\\.)*"|'(?:[^'\\\\]|\\\\.)*')`, 'g')
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ s: text.slice(last, m.index), c: '' })
    out.push({ s: m[0], c: m[2] ? 's' : 'k' })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ s: text.slice(last), c: '' })
  return out
}

export function cellShow(c: QCell | undefined): { text: string; kind: 'none' | 'def' | 'secret' | 'val' } {
  if (!c) return { text: '—', kind: 'none' }
  if (c.secret) return { text: c.value ? 'configured' : 'not configured', kind: 'secret' }
  if (c.origin === 'none' || c.origin === 'unsupported' || c.value === null || c.value === undefined || c.value === '') return { text: '—', kind: 'none' }
  const v = Array.isArray(c.value) ? c.value.join(', ') : typeof c.value === 'object' ? JSON.stringify(c.value) : String(c.value)
  return { text: v, kind: c.origin === 'default' ? 'def' : 'val' }
}

export const STAGES = ['gen', 'parse', 'graph', 'deps', 'template', 'conflict'] as const
export type StageKey = (typeof STAGES)[number]
export interface StageView { key: StageKey; cls: 'ok' | 'bad' | 'warn' | 'ai' | 'none'; bad: number; warn: number; lines: number; skipped: boolean }

/** 护栏五个阶段（加上第一格“生成 / 来源”）的状态。 */
export function stageViews(g: GuardResult | null, ai: boolean): StageView[] {
  return STAGES.map((key) => {
    if (key === 'gen') return { key, cls: ai ? 'ai' : 'none', bad: 0, warn: 0, lines: g?.summary.lines ?? 0, skipped: false }
    const s = g?.stages?.[key]
    if (!s) return { key, cls: 'none', bad: 0, warn: 0, lines: 0, skipped: true }
    const cls = s.status === 'bad' ? 'bad' : s.status === 'warn' ? 'warn' : s.status === 'skipped' ? 'none' : 'ok'
    return { key, cls, bad: s.bad, warn: s.warn, lines: s.lines ?? 0, skipped: s.status === 'skipped' }
  })
}

/** 问题按 拦截 → 注意 → 已核对的要点 分组。 */
export function issueGroups(issues: GuardIssue[]): { status: GuardIssue['status']; items: GuardIssue[] }[] {
  return (['bad', 'warn', 'ok'] as const).map((s) => ({ status: s, items: issues.filter((i) => i.status === s) })).filter((g) => g.items.length)
}

/** 引用编号对应的行。 */
export const rowOf = (r: QueryResult | null, n: number): QRow | null => r?.rows.find((x) => x.n === n) ?? null

/** 交给增量变更：合并后的完整配置放在会话存储里，增量变更页按 handoff=1 取出（文本太长不放进地址）。 */
export const HANDOFF_KEY = 'lmesh-change-handoff'
export interface Handoff { device: number; text: string; profile?: string }
export function saveHandoff(h: Handoff): boolean {
  try { sessionStorage.setItem(HANDOFF_KEY, JSON.stringify(h)); return true } catch { return false }
}
export function takeHandoff(): Handoff | null {
  try {
    const s = sessionStorage.getItem(HANDOFF_KEY)
    if (!s) return null
    sessionStorage.removeItem(HANDOFF_KEY)
    const h = JSON.parse(s) as Handoff
    return typeof h.device === 'number' && typeof h.text === 'string' ? h : null
  } catch { return null }
}
