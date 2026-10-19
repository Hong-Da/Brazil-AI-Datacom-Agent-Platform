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
  result?: { summary?: Record<string, unknown>; result?: Record<string, number> }
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
  return category === 'script_valid' || category === 'kb_review'
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
