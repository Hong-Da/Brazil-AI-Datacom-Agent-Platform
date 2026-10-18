/** Schema 管理的节点表单：节点 ↔ 表单、表单校验、提交体、删除前检查的分组。 */
import type { SchemaNode } from './model'

export const NODE_ID = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/
export const STATUSES = ['draft', 'reviewed', 'verified'] as const
export const SEM_LANGS = ['zh-CN', 'en', 'pt-BR'] as const

export interface NodeForm {
  id: string
  parent: string
  type: string
  key: string
  semantic: Record<string, string>
  range: string
  choices: string
  ordered: boolean
  ref: string
  deprecated: boolean
  replaced_by: string
  status: string
}

/** PUT /kb/schema/nodes/{id} 的请求体（后端整体替换节点，所以每个字段都要带上）。 */
export interface NodeBody {
  parent: string | null
  type: string
  key: string[]
  semantic: Record<string, string>
  range: number[] | null
  choices: string[] | null
  ordered: boolean
  ref: string | null
  deprecated: boolean
  replaced_by: string | null
  status: string
}

export function formatRange(r: number[] | null | undefined): string {
  return r && r.length === 2 ? `[${r[0]}, ${r[1]}]` : ''
}

/** 解析取值范围：空 → null；"[a, b]"、"a, b"、"a..b" → [a, b]；a 不能大于 b。 */
export function parseRange(text: string): { ok: boolean; value: number[] | null } {
  const s = text.trim()
  if (!s) return { ok: true, value: null }
  const m = /^\[?\s*(-?\d+)\s*(?:,|\.\.)\s*(-?\d+)\s*\]?$/.exec(s)
  if (!m) return { ok: false, value: null }
  const a = Number(m[1]), b = Number(m[2])
  if (a > b) return { ok: false, value: null }
  return { ok: true, value: [a, b] }
}

/** 列表输入：逗号、竖线或换行分隔，去空白与空项，保持顺序去重。 */
export function splitList(text: string): string[] {
  const out: string[] = []
  for (const p of text.split(/[,|\n]/)) {
    const v = p.trim()
    if (v && !out.includes(v)) out.push(v)
  }
  return out
}

export function nodeToForm(n: SchemaNode): NodeForm {
  return {
    id: n.id,
    parent: n.parent ?? '',
    type: n.type,
    key: (n.key ?? []).join(', '),
    semantic: { ...n.semantic },
    range: formatRange(n.range),
    choices: (n.choices ?? []).join(' | '),
    ordered: !!n.ordered,
    ref: n.ref ?? '',
    deprecated: !!n.deprecated,
    replaced_by: n.replaced_by ?? '',
    status: n.status || 'draft',
  }
}

/** 新建子节点的初始表单：id 以父节点 id 加点开头，状态为 draft。 */
export function newForm(parent: SchemaNode | null): NodeForm {
  return {
    id: parent ? parent.id + '.' : '',
    parent: parent?.id ?? '',
    type: 'string',
    key: '',
    semantic: {},
    range: '',
    choices: '',
    ordered: false,
    ref: '',
    deprecated: false,
    replaced_by: '',
    status: 'draft',
  }
}

export function formToBody(f: NodeForm): NodeBody {
  const semantic: Record<string, string> = {}
  for (const [k, v] of Object.entries(f.semantic)) if (v && v.trim()) semantic[k] = v.trim()
  const choices = splitList(f.choices)
  return {
    parent: f.parent || null,
    type: f.type,
    key: splitList(f.key),
    semantic,
    range: parseRange(f.range).value,
    choices: choices.length ? choices : null,
    ordered: f.ordered,
    ref: f.type === 'ref' && f.ref ? f.ref : null,
    deprecated: f.deprecated,
    replaced_by: f.deprecated && f.replaced_by ? f.replaced_by : null,
    status: f.status,
  }
}

/** 表单与原节点相比是否有修改（按提交体比较，忽略空白与格式差异）。 */
export function isDirty(f: NodeForm, n: SchemaNode | null): boolean {
  if (!n) return true
  return JSON.stringify(formToBody(f)) !== JSON.stringify(formToBody(nodeToForm(n)))
}

/** id 及其所有后代（按 parent 字段），用于排除会成环的父节点。 */
export function descendants(nodes: SchemaNode[], id: string): Set<string> {
  const kids = new Map<string, string[]>()
  for (const n of nodes) if (n.parent) (kids.get(n.parent) ?? kids.set(n.parent, []).get(n.parent)!).push(n.id)
  const out = new Set<string>([id])
  const stack = [id]
  while (stack.length) for (const c of kids.get(stack.pop()!) ?? []) if (!out.has(c)) { out.add(c); stack.push(c) }
  return out
}

/** 校验表单；返回 字段 → 文案键（schema-edit.err.*）。creating 为新建节点。 */
export function validateForm(f: NodeForm, nodes: SchemaNode[], types: string[], creating: boolean): Record<string, string> {
  const err: Record<string, string> = {}
  const ids = new Set(nodes.map((n) => n.id))
  if (creating) {
    if (!NODE_ID.test(f.id)) err.id = 'err.id'
    else if (ids.has(f.id)) err.id = 'err.idExists'
  }
  if (f.parent) {
    if (!ids.has(f.parent)) err.parent = 'err.parentMissing'
    else if (!creating && descendants(nodes, f.id).has(f.parent)) err.parent = 'err.parentCycle'
  }
  if (!types.includes(f.type)) err.type = 'err.type'
  if (!parseRange(f.range).ok) err.range = 'err.range'
  if (!SEM_LANGS.some((l) => (f.semantic[l] ?? '').trim())) err.semantic = 'err.semantic'
  if (f.type === 'ref' && f.ref && !ids.has(f.ref)) err.ref = 'err.refMissing'
  if (f.deprecated && f.replaced_by) {
    if (f.replaced_by === f.id) err.replaced_by = 'err.replacedSelf'
    else if (!ids.has(f.replaced_by)) err.replaced_by = 'err.refMissing'
  }
  return err
}

export interface NodeUsage {
  node: string
  children: string[]
  referenced_by: string[]
  deps: string[]
  profiles: string[]
  manual_entries: string[]
  cards: string[]
  blocking: boolean
}

export const USAGE_KEYS = ['children', 'referenced_by', 'deps', 'profiles', 'manual_entries', 'cards'] as const
export type UsageKey = (typeof USAGE_KEYS)[number]

/** 删除前检查的阻塞原因：只列出非空的类别。 */
export function usageGroups(u: NodeUsage | null | undefined): { key: UsageKey; items: string[] }[] {
  if (!u) return []
  return USAGE_KEYS.map((key) => ({ key, items: u[key] ?? [] })).filter((g) => g.items.length > 0)
}

/** 后端的出错附加信息（kb.edit_invalid 时是校验错误列表）整理成文字列表。 */
export function errorDetails(data: unknown): string[] {
  if (Array.isArray(data)) return data.map((x) => (typeof x === 'string' ? x : JSON.stringify(x)))
  if (typeof data === 'string' && data) return [data]
  return []
}
