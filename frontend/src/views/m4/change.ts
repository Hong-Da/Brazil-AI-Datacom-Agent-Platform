/**
 * 增量变更页（POST /api/v1/change）的数据结构与纯逻辑：脚本分块行、变更原因、依赖链、回滚配对、筛选、URL 参数。
 */

import type { Note } from '@/i18n/note'

export type Action = 'add' | 'modify' | 'delete' | 'side_effect' | 'mutex'
export type Risk = 'low' | 'medium' | 'high'
export const ACTIONS: Action[] = ['add', 'modify', 'delete', 'side_effect', 'mutex']

export interface After { seq: number; kind: string; node: string; label: string; note: Note }
export interface Op {
  seq: number
  action: Action
  text: string
  context: string[]
  view: string
  depth: number
  object: string
  label: string
  domain: string
  card: string | null
  target_nodes: string[]
  current_nodes: string[]
  fallback: boolean
  fallback_reason: string | null
  notes: string[]
  risk: Risk
  risk_reasons: string[]
  after: After[]
  lines: { current: number[]; target: number[] }
}
export interface Row { kind: 'frame' | 'enter' | 'cmd' | 'quit'; depth: number; text: string; seq: number | null }
export interface Verify {
  ok: boolean
  equal: boolean
  diffs: unknown[]
  diff_count: number
  new_dangling: unknown[]
  order_violations: unknown[]
  issues: { seq?: number; kind: string; text?: string }[]
  unknown: number
}
export interface Plan {
  ops: Op[]
  script: string
  script_plain: string
  script_rows?: Row[]
  risk: { level: Risk; counts: Record<Risk, number> }
  summary: { ops: number; by_action: Record<Action, number>; by_domain: Record<string, number>; fallbacks: number; side_effects: number; unsupported: number }
  unsupported: { node?: string; reason?: string; text?: string }[]
  warnings: { key?: string; kind?: string; params?: Record<string, unknown>; a?: number; b?: number }[]
  verify?: Verify
}
export interface SideInfo { label: string; device: string | null; profile: string | null; family: string | null; device_id?: number | null; version_id?: number | null; nodes?: number }
export interface ImpactSummary {
  seeds: { node: string; schema: string; domain: string; side: string }[]
  objects: { node: string; schema: string; domain: string; depth: number; business: string | null; side: string }[]
  business: { node: string; schema: string; domain: string; type: string; path: string[]; side: string }[]
  by_domain: Record<string, number>
  by_business: Record<string, string[]>
  summary: { seeds: number; objects: number; business: number }
}
export interface ChangeResult extends Plan {
  /** REQ-044：来源设备使用近似 Profile 时的下发前提示 */
  approx_profile?: { device: string; profile: string; source: string; rule_id: number | null } | null
  current: SideInfo
  target: SideInfo
  family: string
  equal: boolean
  rollback?: Plan
  impact?: ImpactSummary
}

/** 变更动作 → 预览中的原因样式（.rs add / del / mod / side / mutex）。 */
export const REASON: Record<Action, string> = { add: 'add', modify: 'mod', delete: 'del', side_effect: 'side', mutex: 'mutex' }

/** 依赖类型 → 边的颜色类别（与配置图的依赖边一致）。 */
export function edgeOf(kind: string): 'ref' | 'pre' | 'mutex' | 'side' | 'contains' {
  if (kind === 'contains') return 'contains'
  if (kind === 'prerequisite' || kind === 'rewrite') return 'pre'
  if (kind === 'mutex' || kind === 'replace' || kind === 'undo_first') return 'mutex'
  if (kind === 'side_effect' || kind === 'side_effect_cleanup') return 'side'
  return 'ref'
}
export const EDGE_VAR: Record<string, string> = { ref: 'var(--e-ref)', pre: 'var(--e-pre)', mutex: 'var(--e-mutex)', side: 'var(--e-side)', contains: 'var(--ink-3)' }

/** 脚本行：后端给出 script_rows 时直接用；旧版本后端只有 script_plain 时按缩进推出层级（命令与序号无法对应）。 */
export function rowsOf(plan: Plan | null | undefined, indent = 1): Row[] {
  if (!plan) return []
  if (plan.script_rows) return plan.script_rows
  const all = plan.script_plain.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n')
  return all.map((l, i) => {
    const depth = Math.floor((l.length - l.trimStart().length) / Math.max(1, indent))
    const edge = i === 0 || i >= all.length - 2
    return { kind: edge && depth === 0 ? 'frame' : 'cmd', depth, text: l.trim(), seq: null }
  })
}

/** 第 i 行（下标）的显示行号（与 script_plain 的行号一致）。 */
export const lineNo = (i: number) => i + 1

/** 序号 → 命令。 */
export function opMap(ops: Op[]): Map<number, Op> {
  return new Map(ops.map((o) => [o.seq, o]))
}

/** 依赖它的命令（after 中引用了它）。 */
export function dependents(ops: Op[], seq: number): { op: Op; kind: string }[] {
  const out: { op: Op; kind: string }[] = []
  for (const o of ops) {
    const a = o.after.find((x) => x.seq === seq)
    if (a) out.push({ op: o, kind: a.kind })
  }
  return out
}

/** 完整依赖链：从 seq 出发沿 after 深度优先，每个前置只出现一次；level 从 1 起。 */
export function chainOf(ops: Op[], seq: number): { seq: number; level: number; kind: string }[] {
  const by = opMap(ops)
  const seen = new Set<number>([seq])
  const out: { seq: number; level: number; kind: string }[] = []
  const walk = (s: number, level: number) => {
    for (const a of by.get(s)?.after ?? []) {
      if (seen.has(a.seq)) continue
      seen.add(a.seq)
      out.push({ seq: a.seq, level, kind: a.kind })
      walk(a.seq, level + 1)
    }
  }
  walk(seq, 1)
  return out
}

const under = (a: string, b: string) => !!a && !!b && a.startsWith(`${b}/`)

/**
 * 回滚命令与下发命令的对应：回滚是目标 → 当前的独立计算，按对象对应——同一对象及其下级（删除父对象会连带撤销子配置）；
 * 都没有时取上级对象的命令。返回两个方向的映射。
 */
export function pairRollback(fwd: Op[], rb: Op[]): { byRb: Map<number, number[]>; byFwd: Map<number, number[]> } {
  const byRb = new Map<number, number[]>()
  const byFwd = new Map<number, number[]>()
  for (const r of rb) {
    // 同一对象或它的下级（撤销父对象连带撤销子配置）；都没有时取上级
    let hit = fwd.filter((f) => !!f.object && (f.object === r.object || under(f.object, r.object)))
    if (!hit.length) hit = fwd.filter((f) => under(r.object, f.object))
    if (!hit.length) continue
    byRb.set(r.seq, hit.map((f) => f.seq))
    for (const f of hit) byFwd.set(f.seq, [...(byFwd.get(f.seq) ?? []), r.seq])
  }
  return { byRb, byFwd }
}

export type Filter = '' | Action | 'risk'

export function matches(op: Op, f: Filter): boolean {
  if (!f) return true
  if (f === 'risk') return op.risk === 'high'
  return op.action === f
}

/** 风险提示：高风险在前，再按序号。 */
export function riskOps(ops: Op[]): Op[] {
  const rank = { high: 0, medium: 1, low: 2 }
  return ops.filter((o) => o.risk !== 'low').sort((a, b) => rank[a.risk] - rank[b.risk] || a.seq - b.seq)
}

/** 进入 / 退出视图的行数（不含首尾的 system-view / commit 等）。 */
export function viewLines(rows: Row[]): number {
  return rows.filter((r) => r.kind === 'enter' || r.kind === 'quit').length
}

/** 命令所在的视图（缩进写法），用于详情里显示上下文。 */
export function contextBlock(op: Op, indent = 1): string {
  const pad = (n: number) => ' '.repeat(n * indent)
  return [...op.context.map((c, i) => pad(i) + c), pad(op.context.length) + op.text].join('\n')
}

/** 验证结果的检查项（复检列表用）：ok 表示通过。 */
export function verifyChecks(v: Verify | undefined, ops: number): { k: string; ok: boolean; n?: number }[] {
  if (!v) return []
  return [
    { k: 'equal', ok: v.equal, n: v.diff_count },
    { k: 'dangling', ok: !v.new_dangling.length, n: v.new_dangling.length },
    { k: 'order', ok: !v.order_violations.length, n: ops - v.order_violations.length },
    { k: 'issues', ok: !v.issues.length, n: v.issues.length },
    { k: 'unknown', ok: !v.unknown, n: v.unknown },
  ]
}

// ---------------------------------------------------------------- 选择当前 / 目标

export interface ChangeSetup {
  device: number | null
  /** 当前配置的版本；null = 最新版本 */
  cv: number | null
  tmode: 'version' | 'paste'
  /** 目标配置的设备（同一平台族的任意设备）；null 时与当前设备相同 */
  tdevice: number | null
  tv: number | null
  text: string
  profile: string
  rollback: boolean
  verify: boolean
}

export const emptySetup = (): ChangeSetup => ({ device: null, cv: null, tmode: 'version', tdevice: null, tv: null, text: '', profile: '', rollback: true, verify: true })

type Query = Record<string, string | null | (string | null)[] | undefined>
const q1 = (q: Query, k: string) => { const v = q[k]; return (Array.isArray(v) ? v[0] : v) ?? '' }
const num = (s: string) => (/^\d+$/.test(s) ? Number(s) : null)

/** URL 参数：device、cv（当前版本）、tdevice、tv（目标版本）、mode=paste。 */
export function fromQuery(q: Query): ChangeSetup {
  const s = emptySetup()
  s.device = num(q1(q, 'device'))
  s.cv = num(q1(q, 'cv'))
  s.tdevice = num(q1(q, 'tdevice'))
  s.tv = num(q1(q, 'tv'))
  if (q1(q, 'mode') === 'paste') s.tmode = 'paste'
  return s
}

export function toQuery(s: ChangeSetup): Record<string, string> {
  const q: Record<string, string> = {}
  if (s.device !== null) q.device = String(s.device)
  if (s.cv !== null) q.cv = String(s.cv)
  if (s.tmode === 'paste') q.mode = 'paste'
  else {
    if (s.tdevice !== null && s.tdevice !== s.device) q.tdevice = String(s.tdevice)
    if (s.tv !== null) q.tv = String(s.tv)
  }
  return q
}

export function ready(s: ChangeSetup): boolean {
  if (s.device === null) return false
  if (s.tmode === 'paste') return !!s.text.trim()
  const td = s.tdevice ?? s.device
  // 同一设备同一版本没有可比的
  return !(td === s.device && (s.tv ?? -1) === (s.cv ?? -1))
}

/** POST /change 的请求体（报告导出复用，另加 report_lang / format）。 */
export function changeBody(s: ChangeSetup, style: string, lang: string): Record<string, unknown> {
  const current: Record<string, unknown> = { device_id: s.device }
  if (s.cv !== null) current.version_id = s.cv
  let target: Record<string, unknown>
  if (s.tmode === 'paste') {
    target = { text: s.text }
    if (s.profile) target.profile = s.profile
  } else {
    target = { device_id: s.tdevice ?? s.device }
    if (s.tv !== null) target.version_id = s.tv
  }
  return { current, target, rollback: s.rollback, verify: s.verify, impact: true, style, lang }
}

/** 下载文件名：<设备>_change_<日期>.txt 等。 */
export function fileName(device: string | null | undefined, kind: 'change' | 'rollback' | 'annotated', day: string): string {
  const d = (device ?? 'config').replace(/[^\w.@-]+/g, '_') || 'config'
  return `${d}_${kind}_${day}.txt`
}
