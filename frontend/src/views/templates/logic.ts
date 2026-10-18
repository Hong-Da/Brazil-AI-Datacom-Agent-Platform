/** 配置模板页的纯逻辑：正文分行（变量与块）、变量约束摘要、校验发现的分类与说明、参数表的列与一行参数的展开。 */
import { msg, show } from '@/views/m3/texts'
import type { CodeLine, CodePart } from '@/views/m3/code'
import type { BlockInfo, Finding, Row, VarInfo } from './types'

// ---------------- 正文 ----------------

const BLOCK_START = /^\s*\{%\s*(repeat|optional)\s+([\w.-]+)\s*%\}\s*$/
const BLOCK_END = /^\s*\{%\s*end\s*%\}\s*$/

/** 占位符表达式的变量名：`svc.lan|mask` → `svc.lan`。 */
export function varOf(expr: string): string {
  return expr.split('|')[0].trim()
}

/** 一行正文 → 分段：普通文字与 {{表达式}}。 */
export function splitPlaceholders(line: string): { s: string; expr?: string }[] {
  const out: { s: string; expr?: string }[] = []
  const re = /\{\{\s*([^}]+?)\s*\}\}/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(line))) {
    if (m.index > last) out.push({ s: line.slice(last, m.index) })
    out.push({ s: m[1], expr: m[1] })
    last = m.index + m[0].length
  }
  if (last < line.length) out.push({ s: line.slice(last) })
  return out
}

export interface BodyLine { no: number; text: string; block: string | null; kind: 'repeat' | 'optional' | null; mark: 'start' | 'end' | null; first: boolean; last: boolean }

/** 正文分行：每行属于哪个块，块的开始 / 结束标记行，块内第一行与最后一行。行号从 1 起（与校验结果的 template_lines 一致）。 */
export function bodyLines(body: string): BodyLine[] {
  const raw = body.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n')
  const out: BodyLine[] = []
  let cur: { name: string; kind: 'repeat' | 'optional' } | null = null
  raw.forEach((text, i) => {
    const s = BLOCK_START.exec(text)
    if (s && !cur) {
      cur = { name: s[2], kind: s[1] as 'repeat' | 'optional' }
      out.push({ no: i + 1, text, block: cur.name, kind: cur.kind, mark: 'start', first: false, last: false })
      return
    }
    if (BLOCK_END.test(text) && cur) {
      out.push({ no: i + 1, text, block: cur.name, kind: cur.kind, mark: 'end', first: false, last: false })
      cur = null
      return
    }
    out.push({ no: i + 1, text, block: cur?.name ?? null, kind: cur?.kind ?? null, mark: null, first: false, last: false })
  })
  // 块内第一行与最后一行（画括号的端点）
  for (let i = 0; i < out.length; i++) {
    const l = out[i]
    if (!l.block || l.mark) continue
    const prev = out[i - 1]
    const next = out[i + 1]
    l.first = !prev || prev.mark === 'start' || prev.block !== l.block
    l.last = !next || next.mark === 'end' || next.block !== l.block
  }
  return out
}

/** 正文 → 代码面板的行：变量高亮（hot 为选中的变量）、块的竖线与括号。 */
export function bodyCode(body: string, hot: string | null, marks: Map<number, string> = new Map(), tag = (b: BodyLine) => `${b.kind} · ${b.block}`): CodeLine[] {
  return bodyLines(body).map((b) => {
    const cls: string[] = []
    if (b.kind) cls.push(b.kind === 'repeat' ? 'b-rep' : 'b-opt')
    if (b.mark) cls.push('b-mark')
    if (b.first) cls.push('b-start')
    if (b.last) cls.push('b-end')
    const m = marks.get(b.no)
    if (m) cls.push(m)
    const parts: CodePart[] = splitPlaceholders(b.text).map((p) =>
      p.expr ? { s: p.s, v: varOf(p.expr), cls: varOf(p.expr) === hot ? 'vx is-hot' : 'vx', title: `{{${p.expr}}}` } : { s: p.s },
    )
    if (b.mark === 'start') parts.push({ s: tag(b), cls: b.kind === 'repeat' ? 'blk-tag rep' : 'blk-tag' })
    return { no: b.no, text: b.text, cls: cls.join(' '), parts }
  })
}

/** 每个变量在正文中出现的次数（按变量名）。 */
export function varUses(body: string): Map<string, number> {
  const m = new Map<string, number>()
  for (const line of body.split(/\r?\n/)) {
    for (const p of splitPlaceholders(line)) if (p.expr) m.set(varOf(p.expr), (m.get(varOf(p.expr)) ?? 0) + 1)
  }
  return m
}

/** 变量的约束摘要（模板文件中的写法，便于对照 YAML）。 */
export function varConstraint(v: VarInfo): string {
  const parts: string[] = []
  if (v.derived && v.expr) parts.push(`= ${v.expr}`)
  if (v.within?.length) parts.push(`within ${v.within.join(', ')}`)
  if (v.length !== undefined) parts.push(`len ${Array.isArray(v.length) ? v.length.join('..') : v.length}`)
  if (v.network) parts.push('network')
  if (v.min !== undefined || v.max !== undefined) parts.push(`${v.min ?? ''}..${v.max ?? ''}`)
  if (v.choices?.length) parts.push(`{${v.choices.map(show).join(', ')}}`)
  if (v.pattern) parts.push(`pattern ${v.pattern}`)
  if (v.unique) parts.push('unique')
  return parts.join('; ')
}

// ---------------- 校验发现 ----------------

/** 发现在界面上的类别：缺少、违反（取值不符、前后不一致、约束、个数、歧义）、模板外、提示。 */
export type FindClass = 'missing' | 'violation' | 'extra' | 'info'
export function findClass(f: Finding): FindClass {
  if (f.kind === 'extra') return 'extra'
  if (f.kind === 'missing') return 'missing'
  return f.severity === 'info' ? 'info' : 'violation'
}

export function findingText(f: Finding, lang: string): string {
  const problem = f.problem ? msg(f.problem, {}, lang) : ''
  return msg(`template.finding.${f.kind}`, {
    expected: f.expected ?? (f.kind === 'missing' ? f.node : null) ?? '', actual: f.actual ?? '', var: f.var ?? '', count: f.count ?? '', problem,
  }, lang)
}

export function kindCounts(fs: Finding[]): Record<FindClass, number> {
  const c: Record<FindClass, number> = { missing: 0, violation: 0, extra: 0, info: 0 }
  for (const f of fs) c[findClass(f)]++
  return c
}

/** 配置行的标记：违反 → c-viol，模板外 → c-extra（一行同时有两种时违反优先）。 */
export function lineMarks(fs: Finding[]): Map<number, string> {
  const m = new Map<number, string>()
  for (const f of fs) {
    const c = findClass(f)
    if (c === 'violation') for (const l of f.lines) m.set(l, 'c-viol')
  }
  for (const f of fs) if (findClass(f) === 'extra') for (const l of f.lines) if (!m.has(l)) m.set(l, 'c-extra')
  return m
}

/** 违反约束或前后不一致的变量（提取的变量表中标红）。 */
export function badVars(fs: Finding[]): Set<string> {
  return new Set(fs.filter((f) => (f.kind === 'constraint' || f.kind === 'inconsistent') && f.var).map((f) => String(f.var)))
}

// ---------------- 参数表 ----------------

/**
 * 参数表的列（与后端 CSV 约定一致）：device、基础变量（不含派生）、可选块名（true / false）、块名.变量。
 */
export function paramColumns(vars: VarInfo[], blocks: BlockInfo[]): string[] {
  const cols = ['device']
  for (const v of vars) if (!v.block && !v.derived) cols.push(v.name)
  for (const b of blocks) {
    if (b.kind === 'optional') cols.push(b.name)
    for (const v of vars) if (v.block === b.name && !v.derived) cols.push(v.name)
  }
  return cols
}

/** 结构化的一行参数（校验提取的 row）→ 参数表的一行（重复块的取值用分号连接）。 */
export function flattenRow(row: Row, cols: string[], blocks: BlockInfo[]): Record<string, string> {
  const out: Record<string, string> = {}
  const kinds = new Map(blocks.map((b) => [b.name, b.kind]))
  for (const c of cols) {
    const dot = c.indexOf('.')
    if (dot > 0 && kinds.has(c.slice(0, dot))) {
      const b = c.slice(0, dot)
      const k = c.slice(dot + 1)
      const val = row[b]
      if (Array.isArray(val)) out[c] = val.map((x) => cell((x as Row)?.[k])).join(';')
      else if (val && typeof val === 'object') out[c] = cell((val as Row)[k])
      else out[c] = ''
    } else if (kinds.get(c) === 'optional') {
      const val = row[c]
      out[c] = val === undefined || val === null ? '' : val ? 'true' : 'false'
    } else out[c] = cell(row[c])
  }
  return out
}

function cell(v: unknown): string {
  return v === null || v === undefined ? '' : String(v)
}

/** 块实例（校验结果的 blocks）→ 表格行：块名、序号、变量取值、行号。 */
export function instanceRows(blocks: Record<string, unknown>): { block: string; i: number; vals: [string, unknown][]; lines: number[] }[] {
  const out: { block: string; i: number; vals: [string, unknown][]; lines: number[] }[] = []
  for (const [b, v] of Object.entries(blocks ?? {})) {
    const list = Array.isArray(v) ? v : v && typeof v === 'object' ? [v] : []
    list.forEach((inst, i) => {
      const r = inst as Row
      out.push({ block: b, i: i + 1, vals: Object.entries(r).filter(([k]) => !k.startsWith('_')), lines: (r._lines as number[]) ?? [] })
    })
  }
  return out
}

/** 新模板的 YAML 骨架。 */
export function skeleton(id: string, profile: string, family = ''): string {
  const cmd = family.startsWith('huawei') ? 'sysname' : 'hostname'
  return [
    `id: ${id}`,
    'version: 1',
    `title: {zh-CN: ${id}, en: ${id}, pt-BR: ${id}}`,
    `profile: ${profile}`,
    'match: {extra: allow, extra_scope: matched}',
    'vars:',
    '  hostname: {type: word, example: R1}',
    'body: |',
    `  ${cmd} {{hostname}}`,
    '',
  ].join('\n')
}
