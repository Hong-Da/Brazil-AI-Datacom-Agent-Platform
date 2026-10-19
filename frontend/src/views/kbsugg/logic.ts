/** 知识库建议（REQ-036，POST/GET /kb/suggestions，审核类型 suggestion）的数据结构与纯逻辑。 */

export type SuggestKind = 'default' | 'syntax' | 'description' | 'other'
export const SUGGEST_KINDS: SuggestKind[] = ['default', 'syntax', 'description', 'other']

export interface SuggestionPayload {
  target: string
  kind: SuggestKind
  current: string
  proposed: string
  reason: string
  project: string | null
}

/** GET /kb/suggestions 或 GET /review/{id} 的一项。 */
export interface SuggestionItem {
  id: number
  kind: string
  status: 'pending' | 'approved' | 'rejected' | string
  title: string
  target: string
  source: { method?: string; user?: string | null; project?: string | null } | null
  note: string
  created_at: string | null
  decided_at: string | null
  payload?: Partial<SuggestionPayload> | null
}

export interface SuggestForm {
  target: string
  kind: SuggestKind
  current: string
  proposed: string
  reason: string
}

/** 提交前整理：去掉首尾空白；理由与对象必填，返回缺的字段。 */
export function buildPayload(f: SuggestForm, project: string | null): { body: SuggestionPayload | null; missing: ('target' | 'reason')[] } {
  const body: SuggestionPayload = {
    target: f.target.trim(),
    kind: f.kind,
    current: f.current.trim(),
    proposed: f.proposed.trim(),
    reason: f.reason.trim(),
    project: project || null,
  }
  const missing: ('target' | 'reason')[] = []
  if (!body.target) missing.push('target')
  if (!body.reason) missing.push('reason')
  return { body: missing.length ? null : body, missing }
}

/** 状态标记：样式类与文案键。 */
export function statusTag(status: string): { cls: string; key: string } {
  if (status === 'approved') return { cls: 't-teal', key: 'st.approved' }
  if (status === 'rejected') return { cls: 't-red', key: 'st.rejected' }
  return { cls: 't-amber', key: 'st.pending' }
}

/** 建议的改动前后（从 payload 取；空的一侧不显示）。 */
export function diffOf(it: SuggestionItem): { current: string; proposed: string } {
  const p = it.payload ?? {}
  return { current: String(p.current ?? '').trim(), proposed: String(p.proposed ?? '').trim() }
}

export function kindOf(it: SuggestionItem): SuggestKind {
  const k = it.payload?.kind
  return k && (SUGGEST_KINDS as string[]).includes(k) ? (k as SuggestKind) : 'other'
}

/** 只是“空”的当前值（— / - / 空）不当作改动前的内容显示。 */
export function meaningful(v: string): boolean {
  return !!v && !['—', '-', '–'].includes(v)
}

/** 采纳后去哪里修改：Profile 条目（目标写作 “profile:节点”）去 Profile 页，其他去 Schema 编辑。 */
export function editLink(target: string): { name: string; query: Record<string, string> } {
  const i = target.indexOf(':')
  if (i > 0) return { name: 'profiles', query: { profile: target.slice(0, i), node: target.slice(i + 1) } }
  return { name: 'schema-edit', query: { node: target } }
}

/** 驳回必须写原因（会显示给提出人）。 */
export function canReject(note: string): boolean {
  return note.trim().length > 0
}
