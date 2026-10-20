/**
 * AI 建议通用组件的纯逻辑（M8-2，预览 DevelopDocs/ui-preview/M8/suggest.html）：类型、接口路径、计数、默认展开、
 * 运行进度四步、token 格式、哪些采纳需要二次确认、引用跳转目标。组件只负责显示与交互。
 */

export type CheckStatus = 'pass' | 'warn' | 'reject'
export type SugStatus = 'pending' | 'adopted' | 'dismissed' | 'reverted'
export type Category = 'refs_exist' | 'script_valid' | 'kb_review' | 'view_hint' | 'text_only' | string

export interface Reason { code: string; level: 'reject' | 'warn'; ref?: string; detail?: string; line?: number }
export interface Segment { t: 'text' | 'ref' | 'num'; v: string; id?: string; key?: string; found?: boolean }
export interface Check {
  status?: CheckStatus
  reasons?: Reason[]
  display?: string
  /** 标题里的编号换成对象名（代码给出） */
  title_display?: string
  segments?: Segment[]
  result?: { summary?: Record<string, unknown>; result?: Record<string, number>; lines?: PreviewLine[] }
}
export interface RefInfo {
  id?: string
  found: boolean
  type?: string
  label?: string
  node?: string
  line?: number | null
  of?: string
  device_id?: number | null
  device?: string
}
export interface Suggestion {
  id: number
  batch_id: number
  skill: string
  category: Category
  kind: string
  title: string
  content: Record<string, unknown> | null
  original: { title?: string; content?: unknown } | null
  edited: boolean
  refs: RefInfo[]
  check: Check
  check_status: CheckStatus
  status: SugStatus
  kb: boolean
  connection: string
  created_by: string
  created_at: string | null
  decided_by: string
  decided_at: string | null
  adopt_info: Record<string, unknown> | null
  note: string
  reverted_by: string
  reverted_at: string | null
  device_id: number | null
  scope_key: string
}
export interface Batch {
  id: number
  skill: string
  skill_version: string
  mode: 'ai' | 'replay'
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  task_id: string
  connection: string
  ai_source: string
  model: string
  tokens_in: number
  tokens_out: number
  params: Record<string, unknown>
  counts: { total: number; pass: number; warn: number; reject: number }
  error: { key?: string; detail?: string } | null
  scope_key: string
  created_at: string | null
  finished_at: string | null
}
export interface SkillInfo {
  id: string
  title: Record<string, string>
  description: Record<string, string>
  group: string
  enabled: boolean
  scope: 'device' | 'project'
  categories: Category[]
}
export interface SkillList { ai: { configured: boolean; reason: string | null; warn_tokens: number }; skills: SkillInfo[] }
export interface ListResult { total: number; counts: Record<SugStatus, number>; items: Suggestion[] }
export interface Estimate { skill: string; tokens: number; warn: boolean; threshold: number }

/** 项目路径下的接口（这些接口只挂在 /projects/{项目}/… 下）。 */
export function projectPath(project: string, path: string): string {
  return `/projects/${encodeURIComponent(project)}${path}`
}

export function query(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== '') q.set(k, String(v))
  const s = q.toString()
  return s ? `?${s}` : ''
}

export function counts(items: Suggestion[]): Record<CheckStatus | SugStatus, number> {
  const c = { pass: 0, warn: 0, reject: 0, pending: 0, adopted: 0, dismissed: 0, reverted: 0 }
  for (const it of items) {
    c[it.check_status] += 1
    c[it.status] += 1
  }
  return c
}

/** 可以采纳：待处理 / 已忽略 / 已撤销，且没有被代码拒绝。 */
export function adoptable(it: Suggestion): boolean {
  return it.status !== 'adopted' && it.check_status !== 'reject'
}

/** 批量（全部 / 按类别）只取校验通过且待处理的。 */
export function batchIds(items: Suggestion[], category?: Category): number[] {
  return items.filter((it) => it.status === 'pending' && it.check_status === 'pass' && (!category || it.category === category)).map((it) => it.id)
}

export function categoriesOf(items: Suggestion[]): Category[] {
  return [...new Set(items.map((it) => it.category))]
}

/** 默认展开：通过的折叠成一行，有警告或被拒绝且待处理的展开（M8-1 评审推荐）。 */
export function defaultOpen(it: Suggestion): boolean {
  return it.check_status !== 'pass' && it.status === 'pending'
}

export type Filter = 'all' | 'pending' | 'adopted' | 'dismissed'
export function filterItems(items: Suggestion[], f: Filter): Suggestion[] {
  if (f === 'all') return items
  if (f === 'adopted') return items.filter((it) => it.status === 'adopted')
  if (f === 'pending') return items.filter((it) => it.status === 'pending' || it.status === 'reverted')
  return items.filter((it) => it.status === f)
}

/** 运行四步：本地脱敏 → 发送 → 生成 → 代码校验（后端任务的 message）。返回当前步序号 0–3，结束为 4。 */
export const STEPS = ['sanitize', 'send', 'generate', 'check'] as const
export function stepOf(message: string, status: string): number {
  if (status === 'done') return 4
  const i = STEPS.indexOf(message as (typeof STEPS)[number])
  return i < 0 ? 0 : i
}

export function fmtTokens(n: number | null | undefined): string {
  const v = Number(n ?? 0)
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
}

/** 预计输入是否超过提示线（0 = 不提示）。 */
export function bigRequest(tokens: number, threshold: number): boolean {
  return threshold > 0 && tokens > threshold
}

/** 会改动配置、脚本或知识库的采纳需要二次确认（附模拟结果，勾选“已查看”）；只影响显示与纯文字的不需要。 */
export function needsConfirm(category: Category): boolean {
  return category === 'script_valid' || category === 'kb_review' || category === 'graph_edit'
}

/** 30 天内可撤销；之后（或对象又被改过）用版本历史回退。 */
export const REVERT_DAYS = 30
export function canRevert(it: Suggestion, now: Date = new Date()): boolean {
  if (it.status !== 'adopted' || !it.decided_at) return false
  return (now.getTime() - new Date(it.decided_at).getTime()) / 86400000 < REVERT_DAYS
}

export interface JumpTarget { name: string; params?: Record<string, string | number>; query?: Record<string, string> }
/** 引用 → 页面：图中对象到设备配置图（带节点），设备到设备分析，行号到配置图并定位行。 */
export function jumpTarget(r: RefInfo): JumpTarget | null {
  if (!r.found || r.device_id == null) return null
  if (r.type && PAGE_REF_TYPES.has(r.type)) return null // 差异条目、问题、命令卡：由所在页面处理（定位到表格行）
  if (r.node) return { name: 'device-graph', params: { id: r.device_id }, query: { node: r.node } }
  if (r.type === 'device' || r.id?.startsWith('d')) return { name: 'device-analysis', params: { id: r.device_id } }
  if (r.line != null) return { name: 'device-graph', params: { id: r.device_id }, query: { line: String(r.line) } }
  return null
}

export function refText(r: RefInfo): string {
  if (r.label) return r.label
  if (r.line != null && !r.id) return `L${r.line}`
  return r.id ?? '?'
}

/** 编辑框的初始文字：text_only 编辑正文，其他类别编辑 JSON 内容。 */
export function editText(it: Suggestion): string {
  const c = it.content ?? {}
  if (it.category === 'text_only' && typeof c.text === 'string') return c.text
  if (it.category === 'script_valid' && typeof c.script === 'string') return c.script
  return JSON.stringify(c, null, 2)
}

/** 编辑框文字 → 新的 content；JSON 不合法时返回 null。 */
export function editContent(it: Suggestion, text: string): Record<string, unknown> | null {
  const c = it.content ?? {}
  if (it.category === 'text_only' && typeof c.text === 'string') return { ...c, text }
  if (it.category === 'script_valid' && typeof c.script === 'string') return { ...c, script: text }
  try {
    const v = JSON.parse(text)
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
  } catch {
    return null
  }
}

export function pick(map: Record<string, string> | undefined, lang: string): string {
  if (!map) return ''
  return map[lang] || map.en || map['zh-CN'] || ''
}

// ---------------------------------------------------------------- M8-3 日常分析组：卡片内容与各页面的范围

/** 这些引用由所在页面处理跳转（差异条目 c*、问题 f*、命令卡 k*），不换页。 */
export const PAGE_REF_TYPES = new Set(['diff', 'finding', 'card'])

/** 卡片正文：text_only / refs_exist 的 content.text，脚本的 content.explain。 */
export function bodyText(it: Suggestion): string {
  const c = it.content ?? {}
  if (it.category === 'script_valid') return typeof c.explain === 'string' ? c.explain : ''
  if (it.category === 'view_hint' || it.category === 'peer_link' || it.category === 'sanitize_rule' || it.category === 'kb_review') return ''
  return typeof c.text === 'string' ? c.text : ''
}

export type Level = 'high' | 'medium' | 'low'
const LV: Record<string, 'hi' | 'mid' | 'lo'> = { high: 'hi', medium: 'mid', low: 'lo' }
/** 风险（变化解读）或优先级（问题解读）：{k: 'risk'|'prio', v, cls}；没有或取值不对时 null。 */
export function levelOf(it: Suggestion): { k: 'risk' | 'prio'; v: Level; cls: 'hi' | 'mid' | 'lo' } | null {
  const c = it.content ?? {}
  for (const k of ['risk', 'priority'] as const) {
    const v = String(c[k] ?? '').toLowerCase()
    if (LV[v]) return { k: k === 'risk' ? 'risk' : 'prio', v: v as Level, cls: LV[v] }
  }
  return null
}

/** 跨设备问题判断更可能出错的一端：编号 → 设备名（引用里有时用引用的名字）。 */
export function suspectOf(it: Suggestion): string | null {
  const s = (it.content ?? {}).suspect
  if (typeof s !== 'string' || !s) return null
  return it.refs.find((r) => r.id === s)?.label ?? s
}

/** 推测对端的一行：A 端（设备 + 接口）⟷ B 端（设备 + 接口，或外部对端的说明）。 */
export function peerLine(it: Suggestion): { a: string; b: string; external: boolean } | null {
  if (it.category !== 'peer_link') return null
  const c = it.content ?? {}
  const name = (id: unknown) => {
    const k = String(id ?? '')
    return it.refs.find((r) => r.id === k)?.label ?? k
  }
  const side = (dev: unknown, itf: unknown) => [name(dev), typeof itf === 'string' ? itf : ''].filter(Boolean).join(' ')
  const external = c.external === true
  return {
    a: side(c.a, c.a_interface),
    b: external ? String(c.label ?? name(c.b)) : side(c.b, c.b_interface),
    external,
  }
}

/** 能力对比说明里的命令写法：[{card: 命令卡（引用里的名字）, text}]。 */
export function commandsOf(it: Suggestion): { card: string; text: string }[] {
  const list = (it.content ?? {}).commands
  if (!Array.isArray(list)) return []
  return list
    .filter((x): x is { card?: unknown; text?: unknown } => !!x && typeof x === 'object')
    .map((x) => {
      const id = String(x.card ?? '')
      return { card: it.refs.find((r) => r.id === id)?.label ?? id, text: String(x.text ?? '') }
    })
}

// ---------- 覆盖核对（变化解读：没有被任何意图解释到的差异由代码列出）
export interface CoverageItem { id: string; label: string; op?: string; node?: string | null; type?: string }
export interface Coverage {
  batch_id: number | null
  prefix: string
  total: number
  covered: string[]
  uncovered: CoverageItem[]
  by_suggestion: Record<string, string[]>
}

/**
 * 差异表的行打标：按 node（优先）或 label 与没被解释的差异对上 → 'uncov'；其余在有覆盖结果时为 'cov'。
 * rows 给出每行的 node 与 label；返回与 rows 同序的标记（没有覆盖结果时全为 ''）。
 */
export function coverageMarks(rows: { node?: string | null; label?: string | null }[], cov: Coverage | null): ('cov' | 'uncov' | '')[] {
  if (!cov || !cov.batch_id || !cov.total) return rows.map(() => '')
  const nodes = new Set(cov.uncovered.map((u) => u.node).filter((x): x is string => !!x))
  const labels = new Set(cov.uncovered.map((u) => u.label).filter(Boolean))
  return rows.map((r) => ((r.node && nodes.has(r.node)) || (r.label && labels.has(r.label)) ? 'uncov' : 'cov'))
}

// ---------- 各页面的范围（必须与后端的 scope_key 一致）
export const diffScope = (source: 'compare' | 'history', a: number, b: number) => `${source}:${a}:${b}`
export const checkScope = (deviceId: number) => `check:${deviceId}`
export const CONSISTENCY_SCOPE = 'consistency'
export function impactScope(deviceId: number, direction: string, nodes: string[]): string {
  return `impact:${deviceId}:${direction}:${[...nodes].sort().join(',')}`.slice(0, 200)
}
export const featureScope = (node: string, a: string, b: string) => `feature:${node}:${a}:${b}`

// ---------------------------------------------------------------- M8-5 规范与合规、知识库构建、报告

export interface TrialHit { sample: string; node: string; key: string; line: number | null }
export interface Trial { samples: number; applicable: number; samples_applicable: number; hits: number; samples_hit: number; items: TrialHit[] }
export type KbDetail =
  | { kind: 'rule'; yaml: string; trial: Trial | null }
  | { kind: 'unknown_card'; cause: string; target: string; base: string; cardText: string; reparse: { lines: number; recognized: number } | null }
  | { kind: 'card_maps'; target: string; maps: { node: string; expr: string }[]; checks: Record<string, string> | null }
  | { kind: 'sanitize'; line: number; text: string; before: string; after: string; sanKind: string; pattern: string; occurrences: number | null; explain: string }
  | { kind: 'other'; reviewKind: string; target: string; json: string }

function cardLines(card: unknown): string {
  if (!card || typeof card !== 'object') return ''
  return Object.entries(card as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join('\n')
}

/** 知识库草稿（规则、命令卡、映射）与脱敏补充的显示内容；content 来自 AI，结果（试跑、重新解析、检查）来自代码。 */
export function kbDetail(it: Suggestion): KbDetail {
  const c = (it.content ?? {}) as Record<string, unknown>
  const p = (c.payload && typeof c.payload === 'object' ? c.payload : {}) as Record<string, unknown>
  const res = (it.check.result ?? {}) as Record<string, unknown>
  if (it.category === 'sanitize_rule') {
    const text = String(c.text ?? '')
    const shown = it.refs.find((r) => r.line != null)
    const line = Number(c.line ?? shown?.line ?? 0)
    return {
      kind: 'sanitize', line, text, before: '', after: '', sanKind: String(c.kind ?? 'other'),
      pattern: String((res as { pattern?: string }).pattern ?? c.pattern ?? ''),
      occurrences: typeof (res as { occurrences?: number }).occurrences === 'number' ? (res as { occurrences: number }).occurrences : null,
      explain: typeof c.explain === 'string' ? c.explain : '',
    }
  }
  const rk = String(c.review_kind ?? '')
  if (rk === 'rule') return { kind: 'rule', yaml: String(p.yaml ?? ''), trial: (res.trial as Trial | undefined) ?? null }
  if (rk === 'unknown_card') {
    const base = String(p.base ?? '')
    return {
      kind: 'unknown_card', cause: String(p.cause ?? it.kind ?? 'missing'), target: String(c.target ?? ''),
      base: it.refs.find((r) => r.id === base)?.label ?? base, cardText: cardLines(p.card),
      reparse: (res.reparse as { lines: number; recognized: number } | undefined) ?? null,
    }
  }
  if (rk === 'card_maps') {
    const maps = p.maps && typeof p.maps === 'object' ? Object.entries(p.maps as Record<string, unknown>) : []
    return {
      kind: 'card_maps', target: String(c.target ?? ''), maps: maps.map(([node, expr]) => ({ node, expr: typeof expr === 'string' ? expr : JSON.stringify(expr) })),
      checks: (res.checks as Record<string, string> | undefined) ?? null,
    }
  }
  return { kind: 'other', reviewKind: rk, target: String(c.target ?? ''), json: JSON.stringify(p, null, 2) }
}

// ---------- 报告摘要的范围（必须与后端 ai_report_summary.scope_key 一致）
export type ReportKind = 'check' | 'baseline' | 'compare' | 'change'
export interface SideSpec { device_id?: number | null; version_id?: number | null }
function sideKey(s: SideSpec | null | undefined): string {
  if (!s) return ''
  if (s.version_id != null) return `v${s.version_id}`
  if (s.device_id != null) return `d${s.device_id}`
  return ''
}
/** report:check:<设备>、report:baseline:<基线>:<设备,…>、report:compare:<A>:<B>、report:change:<当前>:<目标>；配置文本时为 null（不支持摘要）。 */
export function reportScope(kind: ReportKind, p: { device_id?: number | null; device_ids?: number[]; baseline?: string; a?: SideSpec; b?: SideSpec; current?: SideSpec; target?: SideSpec }): string | null {
  if (kind === 'check') return p.device_id != null ? `report:check:${p.device_id}` : null
  if (kind === 'baseline') {
    const ids = [...new Set(p.device_ids ?? [])].sort((x, y) => x - y)
    return ids.length ? `report:baseline:${p.baseline || 'basic'}:${ids.join(',')}` : null
  }
  const [a, b] = kind === 'compare' ? [p.a, p.b] : [p.current, p.target]
  const ka = sideKey(a)
  const kb = sideKey(b)
  return ka && kb ? `report:${kind}:${ka}:${kb}` : null
}

// ---------------------------------------------------------------- M8-4 变更与割接组：代码给出的预览行

/** 预览的一行（代码生成）：k = ai 来自 AI 的内容（紫色）、code 代码生成或补发、bad 被拒绝的部分、warn 代码无法确认、frame 结构行 */
export interface PreviewLine { text: string; k: 'ai' | 'code' | 'bad' | 'warn' | 'frame' | string }

/** 变更与割接组的类别：卡片显示代码给出的预览行（改动与生成的脚本、方案段落、目标写法的解析、映射表、模板与等价核对）。 */
export const CHANGE_CATEGORIES = new Set(['graph_edit', 'plan_section', 'translate_eq', 'naming_rules', 'template_draft'])

export function previewLines(it: Suggestion): PreviewLine[] {
  const ls = it.check.result?.lines
  return Array.isArray(ls) ? ls.filter((x) => x && typeof x.text === 'string') : []
}
