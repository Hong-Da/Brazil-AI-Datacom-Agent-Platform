/**
 * M8-5 规范与合规、报告摘要几处 AI 接入的纯逻辑（预览 DevelopDocs/ui-preview/M8/compliance.html、report.html）：
 * 规范条款切分（与后端 ai_suggest_kb.split_clauses 一致）、条款状态、步骤条、已送审列表、例外说明的可复制文字。
 */
import { bodyText, type Suggestion } from '@/components/ai-suggest/logic'

/** 规范转规则的范围（后端 _rule_build 固定为 rules:standard）。 */
export const RULE_SCOPE = 'rules:standard'
export const MAX_CLAUSES = 80
export const MAX_STANDARD = 60_000
export const MAX_UPLOAD = 5 * 1024 * 1024
export const DOC_TYPES = /\.(txt|md|markdown|text|docx)$/i

const CLAUSE_NO = /^\s*(?:§\s*)?((?:\d+(?:\.\d+){0,4})|(?:第[一二三四五六七八九十百零〇\d]+条)|(?:[A-Z]{1,4}-\d{1,4}))[\s.、:：)）]/

export interface Clause { id: string; no: string; text: string }

/** 规范文字 → 条款（编号 s1…，与后端切分一致）：有编号的行开始一条新条款，没有编号时按空行分段；一句话描述排在最后。 */
export function splitClauses(text: string, sentence = ''): Clause[] {
  const out: { no: string; lines: string[] }[] = []
  let blank = true
  for (const raw of text.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trim().replace(/^#+/, '').trim()
    if (!line) { blank = true; continue }
    const m = CLAUSE_NO.exec(line)
    if (m || blank || !out.length) out.push({ no: m ? m[1] : '', lines: [line] })
    else out[out.length - 1].lines.push(line)
    blank = false
  }
  const list = text.trim() ? out.slice(0, MAX_CLAUSES).map((c, i) => ({ no: c.no || `¶${i + 1}`, text: c.lines.join(' ') })) : []
  if (sentence.trim()) list.push({ no: '*', text: sentence.trim() })
  return list.map((c, i) => ({ id: `s${i + 1}`, ...c }))
}

export type ClauseState = 'sent' | 'draft' | 'failed' | ''
const RANK: Record<ClauseState, number> = { '': 0, failed: 1, draft: 2, sent: 3 }

/** 条款状态（只看这一批）：有采纳的草稿 → 已送审；有待处理且未被拒绝的草稿 → 有草稿；只有被拒绝的 → 未通过。 */
export function clauseStates(items: Suggestion[], batchId: number | null): Record<string, ClauseState> {
  const out: Record<string, ClauseState> = {}
  if (batchId == null) return out
  for (const it of items) {
    if (it.batch_id !== batchId) continue
    let s: ClauseState = ''
    if (it.status === 'adopted') s = 'sent'
    else if (it.status === 'pending' || it.status === 'reverted') s = it.check_status === 'reject' ? 'failed' : 'draft'
    if (!s) continue
    for (const r of it.refs ?? []) {
      if (!r.id || !/^s\d+$/.test(r.id)) continue
      if (RANK[s] > RANK[out[r.id] ?? '']) out[r.id] = s
    }
  }
  return out
}

/** 步骤条：上传规范 → 规则草稿（AI）→ 样本试跑（代码）→ 进审核队列。 */
export function stepClasses(hasText: boolean, running: boolean, ran: boolean, anySent: boolean): ('done' | 'cur' | '')[] {
  return [
    hasText || ran ? 'done' : 'cur',
    ran && !running ? 'done' : hasText || running ? 'cur' : '',
    ran && !running ? (anySent ? 'done' : 'cur') : '',
    anySent ? 'cur' : '',
  ]
}

export interface ReviewRow { sid: number; reviewId: number; title: string; status: string }

/** 采纳（送审）过的规则草稿 → 审核队列条目；审核状态取自 /review（取不到时按 pending）。 */
export function reviewRows(items: Suggestion[], status: Record<number, string>): ReviewRow[] {
  const out: ReviewRow[] = []
  for (const it of items) {
    if (it.status !== 'adopted') continue
    const rid = Number((it.adopt_info ?? {}).review_item_id)
    if (!Number.isFinite(rid) || rid <= 0) continue
    out.push({ sid: it.id, reviewId: rid, title: it.check?.title_display || it.title || `#${it.id}`, status: status[rid] ?? 'pending' })
  }
  return out
}

/** 例外说明的两段文字（kind reason 例外理由、compensating 补偿措施）：已采纳的优先，否则取最新的未拒绝、未忽略的一条。 */
export function waiverTexts(items: Suggestion[]): { reason: string; compensating: string } {
  const pickOne = (kind: string): string => {
    const list = items.filter((x) => x.kind === kind && x.status !== 'dismissed' && x.check_status !== 'reject')
    const best = list.find((x) => x.status === 'adopted') ?? [...list].sort((a, b) => b.id - a.id)[0]
    return best ? (best.check?.display || bodyText(best) || '').trim() : ''
  }
  return { reason: pickOne('reason'), compensating: pickOne('compensating') }
}

/** 基线例外说明的范围（后端 _waiver_build：waiver:<设备>:<基线>:<规则>）。 */
export const waiverScope = (deviceId: number, baseline: string, rule: string) => `waiver:${deviceId}:${baseline}:${rule}`
