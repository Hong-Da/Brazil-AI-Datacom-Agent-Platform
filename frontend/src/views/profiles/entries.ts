import type { Entry, Scalar } from './types'

/**
 * 条目相对当前 Profile 的来源：
 * own 本 Profile 自有（父 Profile 没有这个条目）、override 覆盖了父 Profile 的条目、inherited 继承、unfilled 未填写。
 */
export type EntryOrigin = 'own' | 'override' | 'inherited' | 'unfilled'

export function entryOrigin(e: Entry, parent?: Map<string, Entry>): EntryOrigin {
  if (e.state === 'unfilled') return 'unfilled'
  if (e.inherited) return 'inherited'
  const p = parent?.get(e.node)
  return p && p.state !== 'unfilled' ? 'override' : 'own'
}

export interface EntryFilter {
  q: string
  domain: string
  /** '' 全部、own 本 Profile（自有或覆盖）、inherited 继承、unfilled 未填写 */
  origin: '' | 'own' | 'inherited' | 'unfilled'
  cred: '' | 'draft' | 'reviewed' | 'verified'
  showDeprecated: boolean
}

/** formOf：条目在当前显示风格下的命令写法（REQ-026），给出时搜索也匹配它。 */
export function filterEntries(list: Entry[], f: EntryFilter, parent?: Map<string, Entry>, formOf?: (e: Entry) => string): Entry[] {
  const q = f.q.trim().toLowerCase()
  return list.filter((e) => {
    if (e.deprecated && !f.showDeprecated) return false
    if (q && !e.node.toLowerCase().includes(q) && !(formOf?.(e) ?? '').toLowerCase().includes(q)) return false
    if (f.domain && e.domain !== f.domain) return false
    const o = entryOrigin(e, parent)
    if (f.origin === 'own' && o !== 'own' && o !== 'override') return false
    if (f.origin === 'inherited' && o !== 'inherited') return false
    if (f.origin === 'unfilled' && o !== 'unfilled') return false
    if (f.cred && e.credibility !== f.cred) return false
    return true
  })
}

/** 条目有 Profile 缺省值（REQ-028：配置中没写时由它补成隐藏的默认节点）。 */
export function hasDefault(e: Entry): boolean {
  return e.state !== 'unfilled' && e.default !== null && e.default !== undefined && e.default !== ''
}

export function domainsOf(list: { domain: string }[]): string[] {
  return [...new Set(list.map((e) => e.domain))].sort()
}

/** 编辑表单：PUT /kb/profiles/{id}/entries/{node} 的请求体。 */
export interface EntryForm {
  supported: boolean
  default: string
  show_rule: string
  source: string
  verified: string
}

export function formFromEntry(e: Entry | undefined): EntryForm {
  return {
    supported: e ? e.state !== 'unsupported' : true,
    default: e?.default === null || e?.default === undefined ? '' : String(e.default),
    show_rule: e?.show_rule || 'hide_when_default',
    source: e?.source || '',
    verified: e?.verified || 'doc',
  }
}

/**
 * 请求体：Profile 条目在继承展开时整条替换父条目，所以覆盖继承条目时要把所有字段一起写入。
 * 默认值用 parse 转成 YAML 标量（空表示删除默认值）。
 */
export function entryBody(form: EntryForm, parse: (t: string) => Scalar): Record<string, Scalar> {
  return {
    supported: form.supported,
    default: form.supported ? parse(form.default) : null,
    show_rule: form.show_rule,
    source: form.source.trim(),
    verified: form.verified,
  }
}

export function formDirty(a: EntryForm, b: EntryForm): boolean {
  return (Object.keys(a) as (keyof EntryForm)[]).some((k) => a[k] !== b[k])
}
