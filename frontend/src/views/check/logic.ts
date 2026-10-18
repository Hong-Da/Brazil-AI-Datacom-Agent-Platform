/** 配置检查页的纯逻辑：文案渲染、筛选、计数、级联分组、原文窗口、涉及节点。 */
import { pickLang } from '@/i18n'
import { localizeParams } from '@/i18n/note'
import type { Finding, LangMap, Rule, Severity, TextRef } from './types'
import { SEVERITIES } from './types'

/** 一条发现的唯一键（忽略接口也按 rule + node 识别）。 */
export const findingKey = (f: Pick<Finding, 'rule' | 'node'>): string => `${f.rule}|${f.node}`

/** 把 {param} 换成参数值；没有的参数原样保留。 */
export function format(tpl: string, params: Record<string, unknown>): string {
  return tpl.replace(/\{(\w+)\}/g, (m, k: string) => (k in params && params[k] != null ? String(params[k]) : m))
}

/**
 * 发现的说明 / 建议按当前语言渲染：规则文件的文案在结果的 texts 里；
 * 内置检查的文案键是 check.<规则>.message|suggestion，取 /kb/rules 中该规则的三语模板。
 * pt-BR 有就用，没有回退英文（pickLang）。
 */
export function renderText(ref: TextRef, lang: string, texts: Record<string, LangMap>, rules: Map<string, Rule>): string {
  let m: LangMap | undefined = texts[ref.key]
  if (!m) {
    const hit = /^check\.(.+)\.(message|suggestion|title)$/.exec(ref.key)
    const r = hit ? rules.get(hit[1]) : undefined
    m = r ? r[hit![2] as 'message' | 'suggestion' | 'title'] : undefined
  }
  const tpl = pickLang(m, lang)
  return tpl ? format(tpl, localizeParams(ref.params, lang)) : ref.key
}

export function ruleTitle(rule: string, lang: string, rules: Map<string, Rule>): string {
  return pickLang(rules.get(rule)?.title, lang) || rule
}

/** 规则列表的说明：说明模板里的参数换成省略号。 */
export function ruleDesc(r: Rule, lang: string): string {
  return pickLang(r.message, lang).replace(/\{\w+\}/g, '…')
}

export function ruleSource(r: Rule): string {
  return r.source || (r.builtin ? 'builtin' : r.file || '')
}

// ---------- 筛选 ----------

export interface FindingFilter {
  sev: Severity[] // 空 = 全部
  rules: string[] // 空 = 全部
  domains: string[] // 空 = 全部
  q: string
  showIgnored: boolean
}

export const emptyFilter = (): FindingFilter => ({ sev: [], rules: [], domains: [], q: '', showIgnored: false })

export function matches(f: Finding, flt: FindingFilter, title = ''): boolean {
  if (f.ignored && !flt.showIgnored) return false
  if (flt.sev.length && !flt.sev.includes(f.severity)) return false
  if (flt.rules.length && !flt.rules.includes(f.rule)) return false
  if (flt.domains.length && !flt.domains.includes(f.domain || '-')) return false
  const q = flt.q.trim().toLowerCase()
  if (q) {
    const hay = [title, f.rule, f.domain, ...f.nodes].join(' ').toLowerCase()
    if (!hay.includes(q)) return false
  }
  return true
}

/** 未忽略的发现按某个字段计数（严重度统计不含被忽略的，与后端 summary 一致）。 */
export function countBy(findings: Finding[], pick: (f: Finding) => string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of findings) {
    if (f.ignored) continue
    const k = pick(f)
    out[k] = (out[k] ?? 0) + 1
  }
  return out
}

export function severityCounts(findings: Finding[]): Record<Severity, number> {
  const c = countBy(findings, (f) => f.severity)
  return { error: c.error ?? 0, warning: c.warning ?? 0, info: c.info ?? 0 }
}

/** 点严重度条：选中某一级只看它；再点同一级（或点“全部”）恢复全部。 */
export function toggleSevOnly(cur: Severity[], s: Severity | ''): Severity[] {
  if (!s) return []
  return cur.length === 1 && cur[0] === s ? [] : [s]
}

export const sevOnly = (cur: Severity[]): Severity | '' => (cur.length === 1 ? cur[0] : '')

export function toggleIn<T>(list: T[], v: T, on: boolean): T[] {
  const rest = list.filter((x) => x !== v)
  return on ? [...rest, v] : rest
}

// ---------- 级联分组 ----------

export interface ListRow { f: Finding; key: string; depth: number; cascade: boolean }

/**
 * 级联孤儿（ref.orphan_cascade）的 nodes[1..] 是引用它的孤儿；父发现可见时把它排在父发现之后、缩进一级，
 * 父发现不可见时按原顺序平铺（仍标“级联”）。其余发现保持后端顺序（级别、行号）。
 */
export function orderWithCascade(list: Finding[]): ListRow[] {
  const isOrphanRule = (r: string) => r === 'ref.orphan' || r === 'ref.orphan_cascade'
  const byNode = new Map<string, Finding>()
  for (const f of list) if (isOrphanRule(f.rule)) byNode.set(f.node, f)
  const parentOf = new Map<string, string>() // 子发现键 → 父发现键
  for (const f of list) {
    if (f.rule !== 'ref.orphan_cascade') continue
    const p = f.nodes.slice(1).map((n) => byNode.get(n)).find((x) => x && x !== f)
    if (p) parentOf.set(findingKey(f), findingKey(p))
  }
  const kids = new Map<string, Finding[]>()
  for (const f of list) {
    const p = parentOf.get(findingKey(f))
    if (p) kids.set(p, [...(kids.get(p) ?? []), f])
  }
  const out: ListRow[] = []
  const seen = new Set<string>()
  const visit = (f: Finding, depth: number) => {
    const k = findingKey(f)
    if (seen.has(k)) return
    seen.add(k)
    out.push({ f, key: k, depth, cascade: f.rule === 'ref.orphan_cascade' })
    for (const c of kids.get(k) ?? []) visit(c, Math.min(depth + 1, 3))
  }
  for (const f of list) if (!parentOf.has(findingKey(f))) visit(f, 0)
  for (const f of list) visit(f, 0) // 环（理论上不会有）兜底
  return out
}

// ---------- 涉及节点 ----------

export type ChipKind = 'object' | 'attr' | 'missing' | 'node'
/** origin：节点在图里的来源（default / derived 用隐藏配置样式，REQ-028） */
export interface NodeChip { id: string; kind: ChipKind; origin?: string }

/** 涉及节点；悬空引用补一个不存在的目标（目标类型[名称]），界面画成红色虚线。 */
export function nodeChips(f: Finding, kinds: Map<string, string>, origins?: Map<string, string>): NodeChip[] {
  const out: NodeChip[] = f.nodes.map((id) => {
    // 没有图（粘贴的配置）时按编号判断：最后一段带键（[...]）的是对象，否则是属性
    const k = kinds.get(id) ?? (/\]$/.test(id) ? 'object' : id.includes('/') ? 'attr' : '')
    const chip: NodeChip = { id, kind: k === 'object' || k === 'attr' ? k : 'node' }
    const o = origins?.get(id)
    if (o && o !== 'explicit') chip.origin = o
    return chip
  })
  if (f.rule === 'ref.dangling' || f.rule === 'ref.dangling_unsure') {
    const p = f.message.params ?? {}
    if (p.target_type && p.value != null) out.push({ id: `${p.target_type}[${p.value}]`, kind: 'missing' })
  }
  return out
}

// ---------- 原文窗口 ----------

export type CodeRow = { type: 'line'; no: number; text: string; hl: boolean } | { type: 'gap'; n: number }

/** 相关行前后各带 ctx 行上下文，相邻窗口合并，中间省略的行数用 gap 表示。 */
export function codeWindows(lines: string[], hits: number[], ctx = 3): CodeRow[] {
  const valid = [...new Set(hits)].filter((n) => n >= 1 && n <= lines.length).sort((a, b) => a - b)
  const ranges: [number, number][] = []
  for (const n of valid) {
    const s = Math.max(1, n - ctx)
    const e = Math.min(lines.length, n + ctx)
    const last = ranges[ranges.length - 1]
    if (last && s <= last[1] + 2) last[1] = Math.max(last[1], e)
    else ranges.push([s, e])
  }
  const hs = new Set(valid)
  const out: CodeRow[] = []
  ranges.forEach(([s, e], i) => {
    if (i) out.push({ type: 'gap', n: s - ranges[i - 1][1] - 1 })
    for (let n = s; n <= e; n++) out.push({ type: 'line', no: n, text: lines[n - 1], hl: hs.has(n) })
  })
  return out
}

export const splitLines = (text: string): string[] => text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n')

export const isComment = (t: string): boolean => /^\s*[#!]/.test(t)

/** 发现可以去冗余清理处理（清理脚本只删孤儿与级联孤儿）。 */
export const cleanable = (f: Finding): boolean => f.rule === 'ref.orphan' || f.rule === 'ref.orphan_cascade'

export const sevIcon = (s: Severity): string => ({ error: 'err', warning: 'warn', info: 'info' })[s]

export { SEVERITIES }
