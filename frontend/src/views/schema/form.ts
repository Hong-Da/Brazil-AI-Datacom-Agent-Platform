/** Schema 管理的节点表单：节点 ↔ 表单、表单校验、提交体、删除前检查的分组。 */
import type { SchemaNode } from './model'
import { fieldsFor, TYPE_FIELD_ORDER, type TypeField } from './typefields'

export const NODE_ID = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/
export const STATUSES = ['draft', 'reviewed', 'verified'] as const
export const SEM_LANGS = ['zh-CN', 'en', 'pt-BR'] as const

export interface NodeForm {
  id: string
  parent: string
  type: string
  key: string
  semantic: Record<string, string>
  /** integer 的取值范围两端（输入框文字）；两端都空表示不限 */
  rangeMin: string
  rangeMax: string
  /** enum 的可选值（标签式输入，保持顺序） */
  choices: string[]
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

/** 取值范围两端：都空 → null；必须都是整数且最小值不大于最大值。 */
export function rangeOf(min: string, max: string): { ok: boolean; value: number[] | null; error?: 'err.rangeNum' | 'err.rangeBoth' | 'err.range' } {
  const a = min.trim(), b = max.trim()
  if (!a && !b) return { ok: true, value: null }
  if (!a || !b) return { ok: false, value: null, error: 'err.rangeBoth' }
  if (!/^-?\d+$/.test(a) || !/^-?\d+$/.test(b)) return { ok: false, value: null, error: 'err.rangeNum' }
  if (Number(a) > Number(b)) return { ok: false, value: null, error: 'err.range' }
  return { ok: true, value: [Number(a), Number(b)] }
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
    rangeMin: n.range && n.range.length === 2 ? String(n.range[0]) : '',
    rangeMax: n.range && n.range.length === 2 ? String(n.range[1]) : '',
    choices: [...(n.choices ?? [])],
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
    rangeMin: '',
    rangeMax: '',
    choices: [],
    ordered: false,
    ref: '',
    deprecated: false,
    replaced_by: '',
    status: 'draft',
  }
}

/** 类型不适用、但表单里还有内容的设置项（换类型后提示，保存时清掉）。 */
export function staleFields(f: NodeForm): TypeField[] {
  const keep = fieldsFor(f.type)
  const filled: Record<TypeField, boolean> = {
    range: !!(f.rangeMin.trim() || f.rangeMax.trim()),
    choices: f.choices.length > 0,
    key: splitList(f.key).length > 0,
    ordered: f.ordered,
    ref: !!f.ref,
  }
  return TYPE_FIELD_ORDER.filter((k) => !keep.includes(k) && filled[k])
}

/** 提交体只带当前类型适用的设置项：integer → range；enum → choices；object → key、ordered；ref → ref。 */
export function formToBody(f: NodeForm): NodeBody {
  const semantic: Record<string, string> = {}
  for (const [k, v] of Object.entries(f.semantic)) if (v && v.trim()) semantic[k] = v.trim()
  const use = fieldsFor(f.type)
  const choices = [...new Set(f.choices.map((c) => c.trim()).filter(Boolean))]
  return {
    parent: f.parent || null,
    type: f.type,
    key: use.includes('key') ? splitList(f.key) : [],
    semantic,
    range: use.includes('range') ? rangeOf(f.rangeMin, f.rangeMax).value : null,
    choices: use.includes('choices') && choices.length ? choices : null,
    ordered: use.includes('ordered') ? f.ordered : false,
    ref: use.includes('ref') && f.ref ? f.ref : null,
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
  if (!SEM_LANGS.some((l) => (f.semantic[l] ?? '').trim())) err.semantic = 'err.semantic'
  // 按类型的设置项（M6-9）：只校验当前类型适用的项
  const use = fieldsFor(f.type)
  if (use.includes('range')) {
    const r = rangeOf(f.rangeMin, f.rangeMax)
    if (!r.ok) err.range = r.error ?? 'err.range'
  }
  if (use.includes('choices')) {
    const vals = f.choices.map((c) => c.trim()).filter(Boolean)
    if (!vals.length) err.choices = 'err.choicesEmpty'
    else if (new Set(vals).size !== vals.length) err.choices = 'err.choicesDup'
  }
  if (use.includes('ref')) {
    const target = nodes.find((n) => n.id === f.ref)
    if (!f.ref) err.ref = 'err.refRequired'
    else if (!target) err.ref = 'err.refMissing'
    else if (target.type !== 'object') err.ref = 'err.refNotObject'
  }
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
