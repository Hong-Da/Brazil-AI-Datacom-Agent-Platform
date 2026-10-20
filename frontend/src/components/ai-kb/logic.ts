/**
 * 知识库构建与脱敏复核页面的 AI 接入（M8-5）的纯逻辑：各 skill 的 scope（必须与后端 scope_key 完全一致）、
 * 未识别行表格的“AI 归因”标记、映射建议表、运行前的本地模型检查结果。
 */
import type { Suggestion } from '@/components/ai-suggest/logic'

// ---------- scope（后端 ai_suggest_kb.py 的 Context.scope_key）
export const UNKNOWN_SCOPE = 'unknown-lines'
export const cardScope = (cardId: string) => `card:${cardId}`
export const mappingScope = (family: string) => `mapping:${family}`
export const sanitizeScope = (deviceId: number) => `device:${deviceId}`

/** 文档原文上限（后端 MAX_DOC）。 */
export const MAX_DOC = 20000

// ---------- 未识别行归因
export type TriageState = 'pending' | 'sent' | 'fail' | 'dismissed'
export interface TriageMark { cause: string; state: TriageState; id: number }

function payloadOf(it: Suggestion): Record<string, unknown> {
  const c = (it.content ?? {}) as Record<string, unknown>
  return (c.payload && typeof c.payload === 'object' ? c.payload : {}) as Record<string, unknown>
}

/** 建议对应的未识别行写法：payload.group（u1…）在 refs 里的 label；没有时取第一个 unknown 引用。 */
export function triagePattern(it: Suggestion): string | null {
  const gid = String(payloadOf(it).group ?? '')
  const r = it.refs.find((x) => x.found && x.id === gid && x.label) ?? it.refs.find((x) => x.found && x.type === 'unknown' && x.label)
  return r?.label ?? null
}

export function triageState(it: Suggestion): TriageState {
  if (it.status === 'adopted') return 'sent'
  if (it.check_status === 'reject') return 'fail'
  if (it.status === 'dismissed') return 'dismissed'
  return 'pending'
}

const RANK: Record<TriageState, number> = { sent: 3, pending: 2, fail: 1, dismissed: 0 }

/** 按写法汇总归因：同一写法有多条时取最有用的一条（已送审 > 待处理 > 未通过 > 已忽略），同级取最新。 */
export function triageMarks(items: Suggestion[]): Record<string, TriageMark> {
  const out: Record<string, TriageMark> = {}
  for (const it of items) {
    if (it.skill !== 'unknown-triage') continue
    const p = triagePattern(it)
    if (!p) continue
    const m: TriageMark = { cause: String(payloadOf(it).cause ?? it.kind ?? 'missing'), state: triageState(it), id: it.id }
    const old = out[p]
    if (!old || RANK[m.state] > RANK[old.state] || (RANK[m.state] === RANK[old.state] && m.id > old.id)) out[p] = m
  }
  return out
}

// ---------- 映射建议
export interface MapRow { id: number; card: string; nodes: string[]; state: TriageState }

/** 映射建议 → 表格行：命令卡（target）与建议映射到的 Schema 节点；同一张卡取最新一条。 */
export function mapRows(items: Suggestion[]): MapRow[] {
  const by = new Map<string, MapRow>()
  for (const it of items) {
    if (it.skill !== 'mapping-suggest') continue
    const c = (it.content ?? {}) as Record<string, unknown>
    const card = String(c.target ?? '') || (it.refs.find((r) => r.type === 'card')?.label ?? '')
    if (!card) continue
    const maps = payloadOf(it).maps
    const nodes = maps && typeof maps === 'object' && !Array.isArray(maps) ? Object.keys(maps as object) : []
    const row: MapRow = { id: it.id, card, nodes, state: triageState(it) }
    const old = by.get(card)
    if (!old || row.id > old.id) by.set(card, row)
  }
  return [...by.values()].sort((a, b) => a.card.localeCompare(b.card))
}

// ---------- 只允许本地模型的 skill
export interface Gate { skill: string; allowed: boolean; local_only: boolean; provider: string | null; connection?: string | null; reason: string | null }

/** 运行前检查：只有明确 allowed 为 false 时拦住（取不到检查结果时交给后端在运行时拦）。 */
export function gateBlocked(g: Gate | null): boolean {
  return !!g && g.local_only && !g.allowed
}
