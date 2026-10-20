/** 审核队列页面的纯逻辑：类型、标题拆分、修改字段比较、分页、驳回备注、时间显示。 */

export interface ReviewSource {
  doc?: string
  file?: string
  title?: string
  line?: number
  version?: string
  rules?: string
  extracted_by?: string
  via?: string
  kb_version?: string
  method?: string
  [k: string]: unknown
}

export interface ReviewItem {
  id: number
  kind: string
  status: string
  title: string
  target: string
  source: ReviewSource | null
  note: string
  created_at: string | null
  decided_at: string | null
  payload?: Record<string, unknown> | null
}

export interface ReviewList {
  total: number
  items: ReviewItem[]
  counts: Record<string, number>
}

/** 已知类型的显示顺序与配色（未知类型按原名显示，排在后面）。 */
export const KIND_ORDER = ['card', 'schema_node', 'unknown_line', 'mapping', 'conflict', 'profile_entry', 'suggestion', 'rule', 'unknown_card', 'card_maps'] as const
export const KIND_TONE: Record<string, string> = {
  card: 'card',
  schema_node: 'node',
  unknown_line: 'unknown',
  mapping: 'node',
  conflict: 'conflict',
  profile_entry: 'card',
  suggestion: 'node',
  rule: 'node',
  unknown_card: 'unknown',
  card_maps: 'node',
}

/** 后端已注册通过动作的类型；其他类型通过时后端会返回 review.no_action。 */
export const APPROVABLE = new Set(['card', 'conflict', 'unknown_line', 'suggestion', 'rule', 'unknown_card', 'card_maps'])

/** M8-5：AI 建议采纳后进入审核队列的知识库草稿（规则、未识别行命令卡、命令卡映射），由 ai-kb/KbReviewItem.vue 显示与编辑。 */
export const AI_KB_KINDS = new Set(['rule', 'unknown_card', 'card_maps'])

export function sortedKinds(counts: Record<string, number>): string[] {
  const known = KIND_ORDER.filter((k) => (counts[k] ?? 0) > 0) as string[]
  const rest = Object.keys(counts).filter((k) => !known.includes(k) && (counts[k] ?? 0) > 0).sort()
  return [...known, ...rest]
}

export function totalCount(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + (b || 0), 0)
}

/** 命令卡标题形如 “<卡 ID>：<语法>”，拆成两部分；没有分隔符时整段作为语法。 */
export function splitTitle(title: string, target = ''): { id: string; text: string } {
  const i = title.indexOf('：')
  if (i > 0) return { id: title.slice(0, i), text: title.slice(i + 1) }
  return { id: target, text: title }
}

/** 是否 AI 抽取（卡片来源带 extracted_by=ai）。 */
export function isAi(src: ReviewSource | null | undefined): boolean {
  return (src?.extracted_by ?? '') === 'ai' || (src?.method ?? '') === 'ai'
}

/** 来源一行文字：文档 / 文件 / 行号。 */
export function sourceLine(src: ReviewSource | null | undefined): string {
  if (!src) return ''
  const parts: string[] = []
  if (src.title) parts.push(String(src.title))
  else if (src.file) parts.push(String(src.file))
  if (src.version) parts.push(String(src.version))
  if (src.via) parts.push(String(src.via))
  return parts.join(' · ')
}

/** 可在审核时修改的命令卡字段（后端 CARD_FIELDS 的子集，id 不可改）。 */
export const EDIT_FIELDS = ['syntax', 'view', 'enters_view', 'undo', 'default'] as const
export type EditField = (typeof EDIT_FIELDS)[number]

/** 只保留与原值不同、且非空的字段；没有改动时返回 null（直接通过）。 */
export function changedFields(
  original: Partial<Record<EditField, unknown>>,
  form: Partial<Record<EditField, string>>,
): Record<string, string> | null {
  const out: Record<string, string> = {}
  for (const k of EDIT_FIELDS) {
    const v = (form[k] ?? '').trim()
    const o = original[k] == null ? '' : String(original[k]).trim()
    if (v && v !== o) out[k] = v
  }
  return Object.keys(out).length ? out : null
}

/** 分页显示的区间（从 1 开始），total 为 0 时为 0–0。 */
export function pageRange(offset: number, count: number, total: number): { from: number; to: number; total: number } {
  if (!total || !count) return { from: 0, to: 0, total }
  return { from: offset + 1, to: Math.min(offset + count, total), total }
}

/** 处理掉一条后：当前页变空且不是第一页时退回上一页。 */
export function offsetAfterRemoval(offset: number, remainingOnPage: number, limit: number): number {
  return remainingOnPage <= 0 && offset > 0 ? Math.max(0, offset - limit) : offset
}

/** 处理完当前项后选中的下一项：优先下一项，没有时取上一项。 */
export function nextId(ids: number[], current: number): number | null {
  const i = ids.indexOf(current)
  if (i < 0) return ids[0] ?? null
  return ids[i + 1] ?? ids[i - 1] ?? null
}

/** 驳回备注：原因 + 补充说明。 */
export function rejectNote(reason: string, extra: string): string {
  const e = extra.trim()
  return e ? `${reason}：${e}` : reason
}

/** 后端时间：没有时区的 ISO 按 UTC 处理。 */
export function parseTime(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const s = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 相对时间：返回 [数值, 单位]，单位 m / h / d；不足 1 分钟算 1 分钟。 */
export function age(iso: string | null | undefined, now: Date = new Date()): [number, 'm' | 'h' | 'd'] | null {
  const d = parseTime(iso)
  if (!d) return null
  const min = Math.max(1, Math.floor((now.getTime() - d.getTime()) / 60000))
  if (min < 60) return [min, 'm']
  if (min < 60 * 24) return [Math.floor(min / 60), 'h']
  return [Math.floor(min / 1440), 'd']
}

/** 冲突条目的包内预览是否完整（后端只截取前 4000 字节）；不完整时不能整段编辑后写回。 */
export function previewComplete(preview: string): boolean {
  return new TextEncoder().encode(preview).length < 4000
}

/** 未识别行附卡：五个字段都要填。 */
export interface UnknownCard { id: string; syntax: string; view: string; family: string; domain: string }
export function unknownCardReady(c: UnknownCard): boolean {
  return (['id', 'syntax', 'view', 'family', 'domain'] as const).every((k) => c[k].trim() !== '')
}
export function unknownCardEmpty(c: UnknownCard): boolean {
  return (['id', 'syntax', 'view', 'family', 'domain'] as const).every((k) => c[k].trim() === '')
}

// ---------- M8-5：AI 草稿条目（rule / unknown_card / card_maps）通过时的修改

/** 未识别行命令卡可改的字段（id 只在“缺命令卡”时可改）。 */
export const UCARD_FIELDS = ['id', 'syntax', 'view', 'undo'] as const
export type UcardField = (typeof UCARD_FIELDS)[number]

/** 草稿卡 → 表单（对象字段转 JSON 文本）。 */
export function ucardForm(card: Record<string, unknown> | null | undefined): Record<UcardField, string> {
  const c = card ?? {}
  const s = (v: unknown) => (v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v))
  return { id: s(c.id), syntax: s(c.syntax), view: s(c.view), undo: s(c.undo) }
}

/** 与草稿相比改过的字段（去掉首尾空白；syntax、view 不能改成空）；没有改动时为 null。 */
export function ucardEdited(card: Record<string, unknown> | null | undefined, form: Record<UcardField, string>, idEditable: boolean): Record<string, string> | null | 'incomplete' {
  const o = ucardForm(card)
  const out: Record<string, string> = {}
  for (const k of UCARD_FIELDS) {
    if (k === 'id' && !idEditable) continue
    const v = form[k].trim()
    if (v === o[k].trim()) continue
    if (!v && k !== 'undo') return 'incomplete'
    out[k] = v
  }
  return Object.keys(out).length ? out : null
}

/** 映射表编辑：JSON 对象（Schema 节点 → 表达式），不能为空；与原值相同时为 null。 */
export function parseMaps(text: string, original: unknown): { maps: Record<string, unknown> | null } | { error: 'json' | 'empty' } {
  let v: unknown
  try { v = JSON.parse(text) } catch { return { error: 'json' } }
  if (!v || typeof v !== 'object' || Array.isArray(v)) return { error: 'json' }
  if (!Object.keys(v).length) return { error: 'empty' }
  return { maps: JSON.stringify(v) === JSON.stringify(original ?? {}) ? null : (v as Record<string, unknown>) }
}
