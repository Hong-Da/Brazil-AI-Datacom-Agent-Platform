/**
 * 翻译自定义规则（REQ-032）：规则集的类型、编辑用的纯函数、试运行结果的整理。
 * 匹配与改名都由后端计算（POST /translate-rules/match、/translate-rules/test），这里不复刻匹配逻辑（D-0140）。
 */

export type Texts = Partial<Record<'zh-CN' | 'en' | 'pt-BR', string>>

export interface NameRule { type: string; match: 'exact' | 'wildcard' | 'regex'; from: string; to: string; ignore_case: boolean; enabled: boolean; note?: string }
export interface NamingRule {
  type: string; pattern: string; fix: boolean; case: 'keep' | 'upper' | 'lower'; prefix: string; suffix: string
  replace: { from: string; to: string }[]; truncate: boolean; max_length: number | null; enabled: boolean; note?: string
}
export interface PortRule { match: 'exact' | 'pattern' | 'type'; from: string; to: string; range: [number, number] | null; speed: number | null; enabled: boolean; note?: string }
export interface Rules {
  id: string; title: Texts; description: Texts; from: string | null; to: string | null
  names: NameRule[]; naming: NamingRule[]; ports: PortRule[]
}
export interface RuleSetInfo {
  id: string; title?: Texts; description?: Texts; from?: string | null; to?: string | null; builtin: boolean; file: string
  counts?: { names: number; naming: number; ports: number }; valid?: boolean; issues?: Issue[]; updated?: number
  /** 归属（M6）：builtin 内置 / shared 共享 / mine 我的 / user 别人的（管理员可见）；editable 是否可修改 */
  scope?: 'builtin' | 'shared' | 'mine' | 'user'; owner?: string | null; editable?: boolean
}
export interface RuleSetDetail extends RuleSetInfo { rules: Rules; source: string }
export interface TypeInfo { id: string; domain: string; title: Texts }
export interface Issue { where: string; key: string; args: Record<string, unknown> }

export interface RuleRef { section: 'names' | 'naming' | 'ports'; index: number }
export interface Rename {
  type: string; node: string; new_node: string | null; from: string; to: string; mapped: string; rule: RuleRef | null
  naming_rule: number | null; fixes: string[]; refs: number; ref_nodes: { node: string; schema: string; lines: number[] }[]
  applied: boolean; conflict: string | null; lines: number[]
}
export interface PortRow { from: string; to: string; rule: RuleRef; subinterfaces: number; applied: boolean; lines: number[] }
export interface Conflict { kind: 'many_to_one' | 'exists' | 'target_exists' | 'port_many_to_one' | 'port_exists'; type: string; to: string; from: string[] }
export interface NamingWarn { type: string; name: string; source: string; node: string; problem: 'pattern' | 'length'; pattern?: string; length?: number; max_length?: number; fixed: boolean; rule: RuleRef }
export interface TextRef { node: string; name: string; to: string; line: number; text: string }
export interface Gap { kind: 'name_limit_unknown'; type: string; family: string | null }
export interface NamingReport {
  rule_set: string; family: string | null; renames: Rename[]; ports: PortRow[]; conflicts: Conflict[]; naming: NamingWarn[]
  text_refs: TextRef[]; gaps: Gap[]
  summary: { renamed: number; refs: number; ports: number; subinterfaces: number; conflicts: number; naming: number; text_refs: number; gaps: number }
  source?: { device: string; profile: string }
}
export interface MatchResult {
  kind: 'name' | 'port'; from: string; result: string; rule: number | null; changed: boolean
  mapped?: string; naming_rule?: number | null; fixes?: string[]; problems?: { problem: 'pattern' | 'length'; pattern?: string; length?: number; max_length?: number }[]
  max_length?: number | null; limit_source?: 'rule' | 'knowledge' | null
}

export const SECTIONS = ['names', 'naming', 'ports'] as const
export type Section = (typeof SECTIONS)[number]

export function blankRules(id = ''): Rules {
  return { id, title: {}, description: {}, from: null, to: null, names: [], naming: [], ports: [] }
}
export const newNameRule = (): NameRule => ({ type: '*', match: 'exact', from: '', to: '', ignore_case: false, enabled: true })
export const newNamingRule = (type = '*'): NamingRule => ({
  type, pattern: '', fix: false, case: 'keep', prefix: '', suffix: '', replace: [], truncate: true, max_length: null, enabled: true,
})
export const newPortRule = (): PortRule => ({ match: 'exact', from: '', to: '', range: null, speed: null, enabled: true })

/** 后端返回的规则集补齐字段（旧文件可能省略默认值）。 */
export function normalize(r: Partial<Rules>): Rules {
  return {
    ...blankRules(r.id ?? ''),
    ...r,
    title: r.title ?? {},
    description: r.description ?? {},
    names: (r.names ?? []).map((x) => ({ ...newNameRule(), ...x })),
    naming: (r.naming ?? []).map((x) => ({ ...newNamingRule(), ...x, replace: [...(x.replace ?? [])] })),
    ports: (r.ports ?? []).map((x) => ({ ...newPortRule(), ...x })),
  }
}

/** 列表中移动一项（上移 -1 / 下移 +1），越界时不动；返回新数组。 */
export function move<T>(list: T[], i: number, d: -1 | 1): T[] {
  const j = i + d
  if (i < 0 || i >= list.length || j < 0 || j >= list.length) return list
  const out = [...list]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

/** 编号规则与后端一致：字母数字开头，可含 _ . -，最长 64。 */
export const validId = (id: string): boolean => /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(id)

/** 另存为的建议编号：原编号加 -copy，已存在时加序号。 */
export function copyId(id: string, taken: string[]): string {
  const base = `${id}-copy`
  if (!taken.includes(base)) return base
  for (let i = 2; ; i++) if (!taken.includes(`${base}-${i}`)) return `${base}-${i}`
}

/** 保存用的内容（去掉编辑时的空行：from 与 to 都空的规则不保存）。 */
export function toSave(r: Rules): Omit<Rules, 'id'> {
  const { id: _id, ...rest } = r
  void _id
  return {
    ...rest,
    names: r.names.filter((x) => x.from || x.to),
    naming: r.naming.map((x) => ({ ...x, replace: x.replace.filter((p) => p.from) })),
    ports: r.ports.filter((x) => x.from || x.to),
  }
}

/** 问题定位：where = "names[0].from" → {section: 'names', index: 0, field: 'from'} */
export function issueAt(where: string): { section: string; index: number | null; field: string } {
  const m = /^(\w+)(?:\[(\d+)\])?(?:\.(.+))?$/.exec(where)
  if (!m) return { section: '', index: null, field: '' }
  return { section: m[1], index: m[2] !== undefined ? Number(m[2]) : null, field: m[3] ?? '' }
}

/** 译文中出现的新名称（已执行的改名）：按整词找行下标，用于高亮。 */
export function renamedLines(lines: string[], rep: NamingReport | null | undefined): Set<number> {
  const out = new Set<number>()
  const names = (rep?.renames ?? []).filter((r) => r.applied).map((r) => r.to)
  if (!names.length) return out
  const esc = names.sort((a, b) => b.length - a.length).map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(^|[^\\w.-])(${esc.join('|')})(?=$|[^\\w.-])`)
  lines.forEach((l, i) => { if (re.test(l)) out.add(i) })
  return out
}

/** 试运行结果按状态分组计数（界面摘要条用）。 */
export function reportCounts(rep: NamingReport): { renamed: number; skipped: number; refs: number; ports: number; conflicts: number; naming: number } {
  return {
    renamed: rep.renames.filter((r) => r.applied).length,
    skipped: rep.renames.filter((r) => !r.applied).length,
    refs: rep.summary.refs,
    ports: rep.summary.ports,
    conflicts: rep.conflicts.length,
    naming: rep.naming.length,
  }
}

/** 规则集显示名：当前语言的标题，没有时用编号。 */
export function titleOf(info: { id: string; title?: Texts }, lang: string): string {
  const t = info.title ?? {}
  return (t as Record<string, string | undefined>)[lang] || t['zh-CN'] || t.en || info.id
}
