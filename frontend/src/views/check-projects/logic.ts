/** 配置检查项目（REQ-031）的纯逻辑：问题分组与行号槽标记、筛选、AI 结果合并、重排对照、差异行转换、项目列表筛选。 */
import type {
  AiInfo, Category, CheckResult, DiffRow, Issue, Kind, Move, Project, Revision, Severity, Summary,
} from './types'

export const SEVERITIES: Severity[] = ['error', 'warning', 'info']
export const SEV_RANK: Record<Severity, number> = { error: 3, warning: 2, info: 1 }
export const CATEGORIES: Category[] = ['parse', 'view', 'undo', 'override', 'side_effect', 'order', 'conflict', 'rule', 'ai']
/** 只对变更脚本有意义的类别（完整配置没有执行过程） */
export const CHANGE_ONLY: Category[] = ['undo', 'override', 'side_effect', 'order', 'conflict']
export const AI_REJECT_REASONS = ['rule_not_selected', 'line_invalid', 'not_in_graph', 'target_mismatch', 'code_disagrees', 'evidence_mismatch', 'bad_reply'] as const

/* ---------------------------------------------------------------- 问题 */

/** 按行号、级别（错误在前）排序。 */
export function sortIssues(list: Issue[]): Issue[] {
  return [...list].sort((a, b) => a.line - b.line || SEV_RANK[b.severity] - SEV_RANK[a.severity])
}

/** 每行的问题（级别高的在前）。 */
export function issuesByLine(list: Issue[]): Map<number, Issue[]> {
  const m = new Map<number, Issue[]>()
  for (const x of sortIssues(list)) {
    const arr = m.get(x.line)
    if (arr) arr.push(x)
    else m.set(x.line, [x])
  }
  return m
}

export interface GutterMark { sev: Severity; hollow: boolean; title: string }

/** 行号槽标记：每行取最高级别；这一行的问题全部来自 AI 时画空心点。title 是这一行全部问题的文字。 */
export function gutterMarks(list: Issue[]): Map<number, GutterMark> {
  const out = new Map<number, GutterMark>()
  for (const [line, xs] of issuesByLine(list)) {
    out.set(line, { sev: xs[0].severity, hollow: xs.every((x) => x.source === 'ai'), title: xs.map((x) => x.text).join('\n') })
  }
  return out
}

/** 波浪下划线：每行一条，级别取最高。 */
export function squiggles(list: Issue[]): { line: number; sev: Severity }[] {
  return [...gutterMarks(list).entries()].map(([line, m]) => ({ line, sev: m.sev }))
}

export function countBySev(list: Issue[]): Record<Severity, number> {
  const c: Record<Severity, number> = { error: 0, warning: 0, info: 0 }
  for (const x of list) c[x.severity]++
  return c
}

export function countByCat(list: Issue[]): Partial<Record<Category, number>> {
  const c: Partial<Record<Category, number>> = {}
  for (const x of list) c[x.category] = (c[x.category] ?? 0) + 1
  return c
}

/** 筛选：级别与类别各自为空集合时不限。 */
export function filterIssues(list: Issue[], sev: Set<Severity>, cat: Set<Category>): Issue[] {
  return list.filter((x) => (!sev.size || sev.has(x.severity)) && (!cat.size || cat.has(x.category)))
}

/** 类别筛选按钮：按脚本类型列出适用的类别；不适用但出现了的类别也列出。AI 类别只在 AI 一起校验开启时列出。 */
export function categoriesFor(kind: Kind, aiActive: boolean, counts: Partial<Record<Category, number>>): Category[] {
  return CATEGORIES.filter((c) => {
    if (counts[c]) return true
    if (c === 'ai') return aiActive
    return kind === 'change' || !CHANGE_ONLY.includes(c)
  })
}

/* ---------------------------------------------------------------- AI 一起校验 */

/** 最近一次带 AI 的检查结果：只对当时的内容有效。 */
export interface AiSnapshot { content: string; kind: Kind; issues: Issue[]; info: AiInfo }

export function takeAiSnapshot(res: CheckResult, content: string): AiSnapshot | null {
  if (!res.ai?.enabled) return null
  return { content, kind: res.kind, issues: res.issues.filter((x) => x.source === 'ai'), info: res.ai }
}

/**
 * 要显示的问题：本次结果中的代码问题 + AI 问题。本次没有调用 AI 时，沿用内容与类型都没变的上一次 AI 结果；
 * aiActive=false（未配置或项目关闭了 AI 一起校验）时不显示 AI 问题。
 */
export function mergeIssues(res: CheckResult | null, snap: AiSnapshot | null, content: string, kind: Kind, aiActive: boolean): Issue[] {
  if (!res) return []
  const own = res.issues.filter((x) => x.source !== 'ai')
  if (!aiActive) return own
  if (res.ai?.enabled) return [...own, ...res.issues.filter((x) => x.source === 'ai')]
  if (snap && snap.content === content && snap.kind === kind) return [...own, ...snap.issues]
  return own
}

/** AI 结果是否与当前内容对应（内容改过后要重新点“AI 校验”）。 */
export function aiFresh(snap: AiSnapshot | null, content: string, kind: Kind): boolean {
  return !!snap && snap.content === content && snap.kind === kind
}

export interface AiStats { proposed: number; shown: number; passed: number; unverifiable: number; rejected: number }

export function aiStats(info: AiInfo | null | undefined, shown: Issue[]): AiStats {
  const ai = shown.filter((x) => x.source === 'ai')
  const passed = ai.filter((x) => x.status === 'passed').length
  const rejected = info?.rejected?.length ?? 0
  return { proposed: (info?.accepted ?? ai.length) + rejected, shown: ai.length, passed, unverifiable: ai.length - passed, rejected }
}

/* ---------------------------------------------------------------- 顺序与重排 */

/** 编辑器“移动”槽：顺序核查开启且有重排建议时，原第几行 → 重排后第几行。 */
export function moveMarks(res: CheckResult | null): Map<number, number> {
  const m = new Map<number, number>()
  const re = res?.order?.enabled ? res.order.reorder : undefined
  if (!re?.changed) return m
  for (const mv of re.moves) m.set(mv.line, mv.new_line)
  return m
}

/** 文本 → 行（统一换行符；去掉结尾的一个换行，与编辑器 / 后端的行号一致）。 */
export function splitLines(text: string | null | undefined): string[] {
  if (!text) return []
  const t = text.replace(/\r\n?/g, '\n')
  return (t.endsWith('\n') ? t.slice(0, -1) : t).split('\n')
}

export interface ReorderLine { no: number; text: string; moveIdx: number | null; tag: string | null }

/** 重排前后两栏：被移动的行标出另一侧的行号（重排前“→ 新行号”，重排后“← 原行号”）。 */
export function reorderColumns(original: string, script: string, moves: Move[]): { before: ReorderLine[]; after: ReorderLine[] } {
  const byFrom = new Map<number, number>()
  const byTo = new Map<number, number>()
  moves.forEach((m, i) => { byFrom.set(m.line, i); byTo.set(m.new_line, i) })
  const before = splitLines(original).map((text, i) => {
    const k = byFrom.get(i + 1) ?? null
    return { no: i + 1, text, moveIdx: k, tag: k === null ? null : `→ ${moves[k].new_line}` }
  })
  const after = splitLines(script).map((text, i) => {
    const k = byTo.get(i + 1) ?? null
    return { no: i + 1, text, moveIdx: k, tag: k === null ? null : `← ${moves[k].line}` }
  })
  return { before, after }
}

/** 连线：从左栏第 a 行的中点到右栏第 b 行的中点（三次贝塞尔）。rowH 行高，top 表头高。 */
export function wirePath(a: number, b: number, width: number, rowH: number, top = 0): { d: string; y1: number; y2: number } {
  const y1 = top + (a - 0.5) * rowH
  const y2 = top + (b - 0.5) * rowH
  return { d: `M0 ${y1} C ${width * 0.55} ${y1}, ${width * 0.45} ${y2}, ${width} ${y2}`, y1, y2 }
}

/* ---------------------------------------------------------------- 文本差异 */

/** 行内字符标记：按区间 [起, 止) 切成片段。 */
export function charSegments(text: string | null | undefined, spans: number[][] | undefined): { t: string; hit: boolean }[] {
  const s = text ?? ''
  if (!spans?.length) return [{ t: s, hit: false }]
  const out: { t: string; hit: boolean }[] = []
  let pos = 0
  for (const [a, b] of [...spans].sort((x, y) => x[0] - y[0])) {
    const from = Math.max(a, pos)
    const to = Math.min(b, s.length)
    if (to <= from) continue
    if (from > pos) out.push({ t: s.slice(pos, from), hit: false })
    out.push({ t: s.slice(from, to), hit: true })
    pos = to
  }
  if (pos < s.length) out.push({ t: s.slice(pos), hit: false })
  return out
}

export type UniKind = 'equal' | 'del' | 'add' | 'mod-del' | 'mod-add' | 'move-ghost' | 'move'
export interface UniRow { k: UniKind; a: number | null; b: number | null; text: string; spans?: number[][]; to?: number; from?: number }

/**
 * 并排行 → 上下（统一）视图的行：修改拆成删 / 增两行（各带字符区间）；移走的行在原位置留一行虚线提示，
 * 移入的行在新位置显示并标出来自第几行。
 */
export function unifiedRows(rows: DiffRow[]): UniRow[] {
  const out: UniRow[] = []
  for (const r of rows) {
    switch (r.t) {
      case 'equal': out.push({ k: 'equal', a: r.a, b: r.b, text: r.bt ?? r.at ?? '' }); break
      case 'change':
        out.push({ k: 'mod-del', a: r.a, b: null, text: r.at ?? '', spans: r.sa })
        out.push({ k: 'mod-add', a: null, b: r.b, text: r.bt ?? '', spans: r.sb })
        break
      case 'del': out.push({ k: 'del', a: r.a, b: null, text: r.at ?? '' }); break
      case 'add': out.push({ k: 'add', a: null, b: r.b, text: r.bt ?? '' }); break
      case 'move_from': out.push({ k: 'move-ghost', a: r.a, b: null, text: (r.at ?? '').trim(), to: r.to }); break
      case 'move_to': out.push({ k: 'move', a: r.from ?? null, b: r.b, text: r.bt ?? '', from: r.from }); break
    }
  }
  return out
}

/** 并排视图只保留改动附近的上下文（相同的行连续超过 ctx*2 时折叠）；返回 null 表示折叠占位（含折叠行数）。 */
export function foldEqual<T extends { t?: string; k?: string }>(rows: T[], ctx = 3): (T | { fold: number })[] {
  const isEq = (r: T) => (r.t ?? r.k) === 'equal'
  const out: (T | { fold: number })[] = []
  let i = 0
  while (i < rows.length) {
    if (!isEq(rows[i])) { out.push(rows[i]); i++; continue }
    let j = i
    while (j < rows.length && isEq(rows[j])) j++
    const n = j - i
    const head = i === 0 ? 0 : ctx
    const tail = j === rows.length ? 0 : ctx
    if (n > head + tail + 1) {
      out.push(...rows.slice(i, i + head), { fold: n - head - tail }, ...rows.slice(j - tail, j))
    } else out.push(...rows.slice(i, j))
    i = j
  }
  return out
}

/** 界面语言 → 报告语言（报告只有中、英两种；巴西葡萄牙语用英文）。 */
export function reportLang(lang: string): 'zh-CN' | 'en' {
  return lang === 'zh-CN' ? 'zh-CN' : 'en'
}

/* ---------------------------------------------------------------- 修订 */

/** 两条对比：最多选两条，再选第三条时挤掉最早选的。 */
export function togglePick(picks: number[], id: number): number[] {
  if (picks.includes(id)) return picks.filter((x) => x !== id)
  const next = [...picks, id]
  return next.length > 2 ? next.slice(next.length - 2) : next
}

/** 已选两条按时间排序：旧的作 A、新的作 B。 */
export function orderPicks(picks: number[], revs: Revision[]): [Revision, Revision] | null {
  if (picks.length !== 2) return null
  const rs = picks.map((id) => revs.find((r) => r.id === id)).filter((r): r is Revision => !!r)
  if (rs.length !== 2) return null
  rs.sort((x, y) => x.seq - y.seq)
  return [rs[0], rs[1]]
}

export function revMoves(r: Revision): number {
  return r.note && typeof r.note === 'object' && Array.isArray(r.note.moves) ? r.note.moves.length : 0
}
export function revFrom(r: Revision): number | null {
  if (r.note && typeof r.note === 'object') {
    if (typeof r.note.from_seq === 'number') return r.note.from_seq
    if (typeof r.note.before_seq === 'number') return r.note.before_seq
  }
  return null
}

export function summaryCounts(s: Summary | null | undefined): { e: number; w: number; i: number } | null {
  return s ? { e: s.errors, w: s.warnings, i: s.infos } : null
}

/* ---------------------------------------------------------------- 项目列表 */

export interface ProjectFilter { scope: 'all' | 'mine'; q: string; vendor: string; me: string | null }

export function vendorOf(p: Project): string {
  const s = (p.device?.vendor || p.device?.profile || p.profile || '').toLowerCase()
  return s.startsWith('cisco') ? 'cisco' : s.startsWith('huawei') ? 'huawei' : ''
}

export function filterProjects(list: Project[], f: ProjectFilter): Project[] {
  const q = f.q.trim().toLowerCase()
  return list.filter((p) => {
    if (f.scope === 'mine' && (p.owner?.username ?? null) !== f.me) return false
    if (f.vendor && vendorOf(p) !== f.vendor) return false
    if (q && ![p.name, p.description, p.device?.name ?? ''].join(' ').toLowerCase().includes(q)) return false
    return true
  })
}

export function projectStats(list: Project[], me: string | null): { total: number; mine: number; withErrors: number; scripts: number; latest: number } {
  return {
    total: list.length,
    mine: list.filter((p) => me !== null && p.owner?.username === me).length,
    withErrors: list.filter((p) => p.last_check?.errors > 0).length,
    scripts: list.reduce((n, p) => n + (p.scripts || 0), 0),
    latest: list.filter((p) => p.device_id !== null && p.version_id === null).length,
  }
}

/** ISO 时间 → 本地 yyyy-mm-dd hh:mm。 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 语义差异的取值显示。 */
export function semValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'boolean' || typeof v === 'number') return String(v)
  return JSON.stringify(v)
}

/** 防抖序号：每次发请求取一个新号，结果回来时只有最新号的才采用。 */
export class Latest {
  private n = 0
  next(): number { return ++this.n }
  isLatest(k: number): boolean { return k === this.n }
}
