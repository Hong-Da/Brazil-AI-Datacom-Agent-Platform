/**
 * REQ-033 内置 AI skill 页面的纯逻辑：校验状态的颜色映射、通过率格式化、提示词变量高亮切分、
 * 逐行差异的并排配对、每日调用柱、进化得分汇总、业务结果中的调用编号。
 */
import type {
  CaseRow, Counts, Definition, DiffLine, EvoCase, EvolutionDetail, RunStatus, SkillRunRef, Variable,
} from './types'

// ---------------------------------------------------------------- 校验状态：符号 + 文字 + 颜色
export const ST_ORDER: RunStatus[] = ['passed', 'corrected', 'rejected', 'unverifiable', 'error']
const ST_CLS: Record<RunStatus, string> = { passed: 'ok', corrected: 'fix', rejected: 'bad', unverifiable: 'na', error: 'err' }

/** 状态 → 样式类（.vs.ok / .sw-ok …）；未知状态按“无法校验”。 */
export function stCls(s: string | null | undefined): string {
  return ST_CLS[s as RunStatus] ?? 'na'
}

/** 每种结论的得分（与后端一致：通过 1、无法校验 0.5、其余 0）。 */
export function stScore(s: string): number {
  return s === 'passed' ? 1 : s === 'unverifiable' ? 0.5 : 0
}

// ---------------------------------------------------------------- 比例与格式
/** 比例 → 百分比文字；没有数据时为 —。 */
export function pct(r: number | null | undefined): string {
  return r === null || r === undefined || Number.isNaN(r) ? '—' : `${Math.round(r * 100)}%`
}

/** a / b 的百分比；b 为 0 时为 —。 */
export function pctOf(a: number, b: number): string {
  return b ? pct(a / b) : '—'
}

/** 通过率条的颜色：≥ 85% 青、≥ 70% 琥珀、其余红。 */
export function rateTone(r: number | null | undefined): '' | 'a' | 'r' {
  if (r === null || r === undefined) return ''
  return r >= 0.85 ? '' : r >= 0.7 ? 'a' : 'r'
}

/** 分数两位小数。 */
export function f2(x: number | null | undefined): string {
  return x === null || x === undefined ? '—' : x.toFixed(2)
}

/** 堆叠条的分段（宽度为百分比，跳过 0）。 */
export function stackSegs(c: Partial<Counts>): { k: RunStatus; cls: string; n: number; w: number }[] {
  const tot = ST_ORDER.reduce((s, k) => s + (c[k] ?? 0), 0)
  if (!tot) return []
  return ST_ORDER.filter((k) => (c[k] ?? 0) > 0).map((k) => ({ k, cls: stCls(k), n: c[k] ?? 0, w: ((c[k] ?? 0) / tot) * 100 }))
}

/** 多个 skill 的结论合计。 */
export function sumCounts(list: Partial<Counts>[]): Counts {
  const o: Counts = { calls: 0, passed: 0, corrected: 0, rejected: 0, unverifiable: 0, error: 0, up: 0, down: 0, corrections: 0 }
  for (const c of list) for (const k of Object.keys(o) as (keyof Counts)[]) o[k] += c[k] ?? 0
  return o
}

/** 版本号显示：builtin → null（调用方显示“内置”），其余 vN。 */
export function vname(v: string | null | undefined): string | null {
  if (v === null || v === undefined || v === '' || v === 'builtin') return null
  if (v === 'draft' || v === 'candidate') return v
  return `v${v}`
}

// ---------------------------------------------------------------- 提示词：{变量} 高亮
export interface HlPart { t: 'text' | 'var'; s: string; name?: string; known?: boolean }
// 与后端 core/skills._VAR 一致：{{ 与 }} 是字面花括号
const VAR_RE = /\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}/g

/** 把文本切成普通文字与变量（未登记的变量 known=false）；拼起来与原文逐字相同。 */
export function hlParts(text: string, known: Iterable<string>): HlPart[] {
  const k = new Set(known)
  const out: HlPart[] = []
  let last = 0
  for (const m of text.matchAll(VAR_RE)) {
    if (!m[1]) continue
    const i = m.index ?? 0
    if (i > last) out.push({ t: 'text', s: text.slice(last, i) })
    out.push({ t: 'var', s: m[0], name: m[1], known: k.has(m[1]) })
    last = i + m[0].length
  }
  if (last < text.length) out.push({ t: 'text', s: text.slice(last) })
  return out
}

/** 文本里用到的变量（去重，按出现顺序）。 */
export function varsIn(text: string): string[] {
  const out: string[] = []
  for (const m of text.matchAll(VAR_RE)) if (m[1] && !out.includes(m[1])) out.push(m[1])
  return out
}

/** 定义中所有可编辑文本字段：system、prompt、templates.<名称>。 */
export function textFields(d: Definition): [string, string][] {
  return [['system', d.system], ['prompt', d.prompt], ...Object.entries(d.templates ?? {}).map(([k, v]) => [`templates.${k}`, v] as [string, string])]
}

/** 定义里用到但没有登记的变量：[字段, 变量名]。 */
export function unknownVars(d: Definition, vars: Variable[]): [string, string][] {
  const known = new Set(vars.map((v) => v.name))
  const out: [string, string][] = []
  for (const [f, text] of textFields(d)) for (const n of varsIn(text)) if (!known.has(n)) out.push([f, n])
  return out
}

/** 每个登记的变量出现在哪些字段。 */
export function varWhere(d: Definition, name: string): string[] {
  return textFields(d).filter(([, text]) => varsIn(text).includes(name)).map(([f]) => f)
}

// ---------------------------------------------------------------- 定义草稿
export function cloneDef(d: Definition): Definition {
  return JSON.parse(JSON.stringify(d)) as Definition
}

/** 规范化后比较（示例去掉空说明、工具排序），判断草稿是否有修改。 */
export function sameDef(a: Definition, b: Definition): boolean {
  const norm = (d: Definition) => ({
    system: d.system,
    prompt: d.prompt,
    templates: Object.fromEntries(Object.entries(d.templates ?? {}).sort(([x], [y]) => x.localeCompare(y))),
    examples: (d.examples ?? []).map((e) => ({ input: e.input, output: e.output, note: (e.note ?? '').trim() })),
    tools: [...(d.tools ?? [])].sort(),
    output: { format: d.output?.format ?? '', schema: d.output?.schema ?? '' },
  })
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b))
}

/** 保存时提交的定义：示例的空说明去掉。 */
export function saveBody(d: Definition, note: string): Record<string, unknown> {
  return {
    system: d.system,
    prompt: d.prompt,
    templates: d.templates,
    examples: d.examples.map((e) => (e.note?.trim() ? { input: e.input, output: e.output, note: e.note.trim() } : { input: e.input, output: e.output })),
    tools: d.tools,
    output: { format: d.output?.format ?? '', schema: d.output?.schema ?? '' },
    note,
  }
}

/** 第 i 个示例与相邻的交换（dir = -1 上移，1 下移）；越界时不变。 */
export function moveItem<T>(list: T[], i: number, dir: -1 | 1): T[] {
  const j = i + dir
  if (i < 0 || j < 0 || i >= list.length || j >= list.length) return list
  const out = [...list]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

// ---------------------------------------------------------------- 逐行差异
export function diffCounts(lines: DiffLine[] | undefined): { add: number; del: number } {
  let add = 0
  let del = 0
  for (const l of lines ?? []) {
    if (l.op === 'add') add++
    else if (l.op === 'del') del++
  }
  return { add, del }
}

export interface SbsCell { n: number | null; text: string; op: 'same' | 'del' | 'add' }
/** 并排视图：相同的行两侧对齐，连续的删除与新增逐行配对，缺的一侧为 null（显示斜纹空行）。 */
export function sbsRows(lines: DiffLine[]): { left: SbsCell | null; right: SbsCell | null }[] {
  const rows: { left: SbsCell | null; right: SbsCell | null }[] = []
  let dq: DiffLine[] = []
  let iq: DiffLine[] = []
  const flush = () => {
    const n = Math.max(dq.length, iq.length)
    for (let i = 0; i < n; i++) {
      rows.push({
        left: dq[i] ? { n: dq[i].a, text: dq[i].text, op: 'del' } : null,
        right: iq[i] ? { n: iq[i].b, text: iq[i].text, op: 'add' } : null,
      })
    }
    dq = []
    iq = []
  }
  for (const l of lines) {
    if (l.op === 'same') {
      flush()
      rows.push({ left: { n: l.a, text: l.text, op: 'same' }, right: { n: l.b, text: l.text, op: 'same' } })
    } else if (l.op === 'del') dq.push(l)
    else iq.push(l)
  }
  flush()
  return rows
}

/** 版本对比的两个版本按时间排序（builtin 最早，其余按版本号）；swap 时交换 A / B。 */
export function orderPair(picks: string[], swap = false): [string, string] | null {
  if (picks.length < 2) return null
  const rank = (v: string) => (v === 'builtin' ? -1 : Number(v))
  const p = [...picks].slice(-2).sort((x, y) => rank(x) - rank(y)) as [string, string]
  return swap ? [p[1], p[0]] : p
}

// ---------------------------------------------------------------- 每日调用柱
export interface DayCol { date: string; label: string; total: number; segs: { k: RunStatus; cls: string; n: number; h: number }[] }
/** 每日调用柱：纵轴上限取 5 的倍数；横轴每 5 天和最后一天标日期（MM-DD）。 */
export function dayCols(daily: (Partial<Counts> & { date: string })[]): { top: number; cols: DayCol[] } {
  const totals = daily.map((d) => ST_ORDER.reduce((s, k) => s + (d[k] ?? 0), 0))
  const max = Math.max(0, ...totals)
  const top = Math.ceil(max / 5) * 5 || 5
  const cols = daily.map((d, i) => ({
    date: d.date,
    label: i % 5 === 0 || i === daily.length - 1 ? d.date.slice(5) : '',
    total: totals[i],
    segs: ST_ORDER.filter((k) => (d[k] ?? 0) > 0).map((k) => ({ k, cls: stCls(k), n: d[k] ?? 0, h: ((d[k] ?? 0) / top) * 100 })),
  }))
  return { top, cols }
}

// ---------------------------------------------------------------- 进化
/** 进化回归集逐条：变化的条数与平均分（后端已给 summary 时以它为准）。 */
export function evoSummary(cases: EvoCase[]): { old: number; new: number; better: number; worse: number; same: number } {
  if (!cases.length) return { old: 0, new: 0, better: 0, worse: 0, same: 0 }
  let o = 0
  let n = 0
  let better = 0
  let worse = 0
  let same = 0
  for (const c of cases) {
    o += c.old.score
    n += c.new.score
    if (c.new.score > c.old.score) better++
    else if (c.new.score < c.old.score) worse++
    else same++
  }
  return { old: o / cases.length, new: n / cases.length, better, worse, same }
}

/** 候选是否保留了旧定义里的全部变量：返回 [保留的, 丢掉的]。 */
export function keptVars(base: Definition, cand: Definition): [string[], string[]] {
  const all = (d: Definition) => textFields(d).flatMap(([, t]) => varsIn(t))
  const b = [...new Set(all(base))]
  const c = new Set(all(cand))
  return [b.filter((v) => c.has(v)), b.filter((v) => !c.has(v))]
}

/** 不能发起进化的原因（文案键，空串表示可以）。 */
export function evolveBlock(o: {
  configured: boolean
  sid: string
  enabled: boolean
  regression: number
  pending: EvolutionDetail | { id: number } | null
  running: boolean
}): string {
  if (!o.configured) return 'evo.whyNoAi'
  if (o.sid === 'skill-evolve') return 'evo.whySelf'
  if (o.running) return 'evo.whyRunning'
  if (!o.regression) return 'evo.whyNoCases'
  if (o.pending) return 'evo.whyPending'
  return ''
}

// ---------------------------------------------------------------- 调用记录与案例
/** 输入的简短说明：问题、需求或第一个文本字段；否则为 JSON 节选。 */
export function inputSummary(input: unknown, max = 160): string {
  const cut = (s: string) => (s.length > max ? `${s.slice(0, max)}…` : s)
  if (input === null || input === undefined) return ''
  if (typeof input === 'string') return cut(input)
  if (typeof input === 'object' && !Array.isArray(input)) {
    const o = input as Record<string, unknown>
    for (const k of ['question', 'request', 'text', 'syntax', 'script']) if (typeof o[k] === 'string' && o[k]) return cut(o[k] as string)
    const first = Object.values(o).find((v) => typeof v === 'string' && v)
    if (typeof first === 'string') return cut(first)
  }
  return cut(JSON.stringify(input))
}

/** 案例最近一次的校验结论（记在 detail.summary.status）。 */
export function caseStatus(c: CaseRow): string {
  const s = (c.detail?.summary as { status?: string } | undefined)?.status
  return s || 'unverifiable'
}

/** 入集原因 → 标签颜色。 */
export function reasonTone(r: string): string {
  return ({ rejected: 't-red', corrected: 't-amber', down: 't-red dashed', correction: 't-amber', manual: '', up: 't-teal' } as Record<string, string>)[r] ?? ''
}

// ---------------------------------------------------------------- 业务结果中的调用编号（反馈用）
/** AI 查询：反馈记在 step=answer 那一条；没有回答时用最后一条。 */
export function askRunId(res: { skill_runs?: SkillRunRef[] | null } | null | undefined): number | null {
  const runs = (res?.skill_runs ?? []).filter((r) => r.run_id)
  if (!runs.length) return null
  const ans = runs.find((r) => r.step === 'answer')
  return (ans ?? runs[runs.length - 1]).run_id
}

/** 一次结果对应的 skill 编号（与 askRunId 选同一条）。 */
export function askRunSkill(res: { skill_runs?: SkillRunRef[] | null } | null | undefined): string {
  const runs = (res?.skill_runs ?? []).filter((r) => r.run_id)
  const ans = runs.find((r) => r.step === 'answer') ?? runs[runs.length - 1]
  return ans?.skill ?? ''
}

/** AI 生成：反馈记在最终轮。 */
export function genRunId(res: {
  skill_runs?: SkillRunRef[] | null
  rounds?: { round: number; skill_run?: number | null }[]
  final?: { round: number }
} | null | undefined): number | null {
  if (!res) return null
  const fin = res.rounds?.find((r) => r.round === res.final?.round)?.skill_run
  if (fin) return fin
  const runs = (res.skill_runs ?? []).filter((r) => r.run_id)
  return runs.length ? runs[runs.length - 1].run_id : null
}

/** 后端校验问题的文案键 skills.issue.xxx → 页面文案键 issue.xxx。 */
export function issueKey(key: string): string {
  return key.replace(/^skills\./, '')
}

/** 变量名加上花括号（模板里不能直接写 `{${n}}`，会与插值的 }} 冲突）。 */
export function br(n: string): string {
  return '{' + n + '}'
}
