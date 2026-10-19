/** 首页的纯逻辑：样本往返结果的状态、筛选、差异行，Profile 覆盖与可信度。 */

import { vendorMark } from '@/vendor'

export interface RtDiff { line: number; original: string[]; rendered: string[] }
export interface RtResult {
  file: string
  gate: boolean
  passed?: boolean
  ok: boolean
  error?: string
  profile?: string
  lines?: number
  unknown?: number
  coverage?: number
  diffs?: RtDiff[]
}
export interface Regression { samples: number; failed: number; results: RtResult[]; kb_version: string; at?: string }

/** pass 一致；diff 文本不一致；unknown 文本一致但门槛样本有未识别行；missing 样本文件不存在。 */
export type RtState = 'pass' | 'diff' | 'unknown' | 'missing'

export function rtState(r: RtResult): RtState {
  if (r.error === 'missing') return 'missing'
  if (!r.ok) return 'diff'
  if (r.passed === false) return 'unknown'
  return 'pass'
}

export function filterRt(results: RtResult[], mode: '' | 'fail'): RtResult[] {
  return mode === 'fail' ? results.filter((r) => rtState(r) !== 'pass') : results
}

export function sampleName(file: string): string {
  return file.split('/').pop() || file
}

export interface DiffLine { kind: '' | 'del' | 'add'; no: number | null; ws: string; text: string }

/** 往返差异 → 逐行显示：原文行标 del（带原行号），渲染行标 add；前导空白单独拆出以便高亮。 */
export function diffLines(diffs: RtDiff[]): DiffLine[] {
  const out: DiffLine[] = []
  for (const d of diffs) {
    d.original.forEach((t, i) => out.push({ kind: 'del', no: d.line + i, ...splitWs(t) }))
    d.rendered.forEach((t) => out.push({ kind: 'add', no: null, ...splitWs(t) }))
  }
  return out
}

function splitWs(t: string): { ws: string; text: string } {
  const m = /^(\s*)(.*)$/s.exec(t)
  return { ws: m?.[1] ?? '', text: m?.[2] ?? t }
}

export interface ProfileRow {
  id: string
  vendor: string
  inherits: string | null
  own_entries: number
  entries: number
  coverage: number
  credibility: { draft: number; reviewed: number; verified: number }
}

export interface ProfileView {
  id: string
  vendor: 'hw' | 'cs' | 'nk' | ''
  inherits: string | null
  unfilled: boolean
  pct: number
  cred: { verified: number; reviewed: number; draft: number }
}

export function pct(x: number): number {
  return Math.round((x || 0) * 100)
}

export function vendorCode(v: string): 'hw' | 'cs' | 'nk' | '' {
  return vendorMark(v).cls
}

/** 可信度三段占比（按条目数），合计 100；没有条目时全为 0。 */
export function profileView(p: ProfileRow): ProfileView {
  const c = p.credibility ?? { draft: 0, reviewed: 0, verified: 0 }
  const total = c.draft + c.reviewed + c.verified
  const part = (n: number) => (total ? Math.round((n * 100) / total) : 0)
  const verified = part(c.verified)
  const reviewed = part(c.reviewed)
  return {
    id: p.id,
    vendor: vendorCode(p.vendor),
    inherits: p.inherits,
    unfilled: p.entries === 0 || (p.own_entries === 0 && !p.inherits),
    pct: pct(p.coverage),
    cred: { verified, reviewed, draft: total ? 100 - verified - reviewed : 0 },
  }
}
