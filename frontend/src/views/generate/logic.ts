/** 批量生成页的纯逻辑：CSV 读写、参数表与列对齐、每行的验证阶段、单元格错误、报告。 */
import { msg, show } from '@/views/m3/texts'
import { findingText } from '@/views/templates/logic'
import type { BlockInfo, Finding, VarInfo } from '@/views/templates/types'

export interface GenError { stage: string; var?: string; value?: unknown; problem: string; instance?: number | null; [k: string]: unknown }
export interface GenRow {
  index: number
  device: string
  ok: boolean
  text: string | null
  params: Record<string, unknown>
  errors: GenError[]
  checks: {
    canon?: { uncovered: string[]; skipped_extras: string[] }
    parse?: { profile: string; unknown: number; unknown_lines: { line: number; text: string }[] }
    roundtrip?: boolean
    template?: { compliant: boolean; errors: number; findings: Finding[]; mismatched: { var: string; instance?: number; want: unknown; got: unknown }[] } | null
  }
  file: string
}
export interface GenResult {
  template: { id: string; version: number; profile: string }
  engine: string
  profile: string
  verify: boolean
  rows: GenRow[]
  summary: { total: number; ok: number; failed: number }
}

// ---------------- CSV ----------------

/** RFC 4180 CSV → 行（去掉 BOM 与全空行）。 */
export function parseCsv(text: string): string[][] {
  const s = text.replace(/^﻿/, '')
  const rows: string[][] = []
  let row: string[] = []
  let f = ''
  let q = false
  const push = () => {
    row.push(f)
    f = ''
  }
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (q) {
      if (ch === '"') {
        if (s[i + 1] === '"') {
          f += '"'
          i++
        } else q = false
      } else f += ch
    } else if (ch === '"') q = true
    else if (ch === ',') push()
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && s[i + 1] === '\n') i++
      push()
      if (row.some((x) => x !== '')) rows.push(row)
      row = []
    } else f += ch
  }
  push()
  if (row.some((x) => x !== '')) rows.push(row)
  return rows
}

/** 参数表 → CSV 文本（不带 BOM，交给后端）。 */
export function toCsvText(cols: string[], rows: string[][]): string {
  const cell = (v: string) => (/[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  return [cols, ...rows].map((r) => r.map((x) => cell(x ?? '')).join(',')).join('\n') + '\n'
}

/** 读入的 CSV 按表头对齐到模板的列；返回行、模板中没有的列（忽略）与缺少的列。 */
export function alignCsv(table: string[][], cols: string[]): { rows: string[][]; ignored: string[]; missing: string[] } {
  if (!table.length) return { rows: [], ignored: [], missing: cols }
  const head = table[0].map((h) => h.trim())
  const idx = cols.map((c) => head.indexOf(c))
  return {
    rows: table.slice(1).map((r) => idx.map((k) => (k >= 0 ? (r[k] ?? '').trim() : ''))),
    ignored: head.filter((h) => h && !cols.includes(h)),
    missing: cols.filter((_, i) => idx[i] < 0),
  }
}

/** 示例行：每列用变量的示例值或默认值（重复块写一个实例，可选块写 true）。 */
export function exampleRow(cols: string[], vars: VarInfo[], blocks: BlockInfo[]): string[] {
  const vm = new Map(vars.map((v) => [v.name, v]))
  const opt = new Set(blocks.filter((b) => b.kind === 'optional').map((b) => b.name))
  return cols.map((c) => {
    if (c === 'device') return show(vm.get('hostname')?.example ?? '')
    if (opt.has(c)) return 'true'
    const v = vm.get(c)
    return v ? show(v.example ?? v.default ?? '') : ''
  })
}

// ---------------- 结果 ----------------

/** 错误说明（当前语言）：约束类问题的文案键在 problem。 */
export function errorText(e: GenError, lang: string): string {
  const base = msg(e.problem, e as Record<string, unknown>, lang)
  const where = e.instance !== undefined && e.instance !== null ? ` #${Number(e.instance) + 1}` : ''
  const val = e.value !== undefined && e.value !== null && e.value !== '' ? ` (${show(e.value)})` : ''
  return e.var ? `${e.var}${where}${val}：${base}` : base
}

/** 单元格错误：列名 → 说明（块级问题标在块的每一列上）。 */
export function cellErrors(row: GenRow | undefined, cols: string[], lang: string): Map<string, string[]> {
  const m = new Map<string, string[]>()
  if (!row) return m
  for (const e of row.errors) {
    if (e.stage !== 'params' || !e.var) continue
    const targets = cols.includes(e.var) ? [e.var] : cols.filter((c) => c.startsWith(`${e.var}.`))
    for (const c of targets) {
      const a = m.get(c) ?? []
      a.push(errorText(e, lang))
      m.set(c, a)
    }
  }
  return m
}

export type StageState = 'ok' | 'bad' | 'skip'
export interface Stage { key: 'params' | 'render' | 'parse' | 'roundtrip' | 'template'; state: StageState; items: string[]; note?: string }

/** 一行的验证阶段：参数 → 生成 → 再解析 → 往返 → 按模板校验。前面失败时后面不执行（skip）。 */
export function stages(r: GenRow, lang: string): Stage[] {
  const errs = (s: string) => r.errors.filter((e) => e.stage === s)
  const out: Stage[] = []
  const p = errs('params')
  out.push({ key: 'params', state: p.length ? 'bad' : 'ok', items: p.map((e) => errorText(e, lang)) })
  const g = errs('render')
  const rendered = r.text !== null && r.text !== undefined
  out.push({ key: 'render', state: p.length ? 'skip' : g.length ? 'bad' : 'ok', items: g.map((e) => errorText(e, lang)) })
  const parse = r.checks.parse
  out.push({
    key: 'parse',
    state: !parse ? 'skip' : parse.unknown ? 'bad' : 'ok',
    items: (parse?.unknown_lines ?? []).map((u) => `L${u.line}: ${u.text}`),
  })
  out.push({ key: 'roundtrip', state: r.checks.roundtrip === undefined ? 'skip' : r.checks.roundtrip ? 'ok' : 'bad', items: [] })
  const tpl = r.checks.template
  out.push({
    key: 'template',
    state: !rendered || tpl === undefined || tpl === null ? 'skip' : tpl.compliant && !tpl.mismatched.length ? 'ok' : 'bad',
    items: tpl ? [
      ...tpl.findings.map((f) => findingText(f, lang)),
      ...tpl.mismatched.map((m) => `${m.var}${m.instance !== undefined ? ` #${m.instance + 1}` : ''}: ${show(m.want)} → ${show(m.got)}`),
    ] : [],
    note: tpl === null && rendered ? 'cross' : undefined,
  })
  return out
}

// ---------------- 下载 ----------------

export function resultCsvRows(cols: string[], rows: string[][], res: GenResult | null, lang: string): string[][] {
  return [
    [...cols, 'result', 'file', 'errors'],
    ...rows.map((r, i) => {
      const g = res?.rows[i]
      return [...r, g ? (g.ok ? 'passed' : 'failed') : '', g?.ok ? g.file : '', g ? g.errors.map((e) => errorText(e, lang)).join(' | ') : '']
    }),
  ]
}

/** 生成报告（Markdown，中文或英文）。 */
export function reportMd(res: GenResult, lang: 'zh-CN' | 'en', when: string): string {
  const zh = lang === 'zh-CN'
  const t = (a: string, b: string) => (zh ? a : b)
  const md = [
    `# ${t('批量生成报告', 'Batch generation report')}`,
    '',
    `- ${t('模板', 'Template')}: ${res.template.id} v${res.template.version}`,
    `- Profile: ${res.profile}`,
    `- ${t('生成方式', 'Engine')}: ${res.engine}`,
    `- ${t('时间', 'Time')}: ${when}`,
    `- ${t('行数', 'Rows')}: ${res.summary.total}, ${t('通过', 'passed')}: ${res.summary.ok}, ${t('失败', 'failed')}: ${res.summary.failed}`,
    '',
    `| # | ${t('设备', 'Device')} | ${t('文件', 'File')} | ${t('结果', 'Result')} |`,
    '|---|---|---|---|',
  ]
  for (const r of res.rows) {
    const why = r.errors.map((e) => errorText(e, lang)).join('; ').replace(/\|/g, '\\|')
    md.push(`| ${r.index + 1} | ${r.device} | ${r.ok ? r.file : '-'} | ${r.ok ? t('通过', 'passed') : `${t('失败', 'failed')}: ${why}`} |`)
  }
  md.push('', t('> 每行验证：参数类型与约束、生成、再解析无未识别行、往返逐字一致、按模板校验并提取出相同的变量。', '> Each row is verified: parameter types and constraints, generation, re-parse without unknown lines, identical round trip, and a template check that extracts the same variables.'), '')
  return md.join('\n')
}
