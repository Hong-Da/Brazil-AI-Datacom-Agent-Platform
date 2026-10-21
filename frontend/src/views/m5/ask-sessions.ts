/** AI 查询会话（REQ-052～054）：类型与纯逻辑，AskView 与会话组件使用。 */
import type { AskResult } from './ask'

export type SessionWhich = 'active' | 'archived' | 'shared'

export interface SessionBrief {
  id: number
  title: string
  owner: string
  mine: boolean
  network: string | null
  devices: string[] | null
  archived: boolean
  shared: boolean
  turns: number
  attachments: number
  created_at: string | null
  updated_at: string | null
}

export interface TurnVersion { question: string; result: AskResult; context: number; attachments: number[]; at: string }
export interface SessionTurn { id: number; position: number; current: number; versions: TurnVersion[] }
export interface Attachment {
  id: number
  name: string
  kind: 'config' | 'doc' | 'image'
  size: number
  meta: { vendor?: string; profile?: string; device?: string; chars?: number; truncated?: boolean; format?: string; sheets?: number; rows?: number; pages?: number; tables?: number; mime?: string }
}
export interface SessionFull extends SessionBrief { turn_list: SessionTurn[]; attachment_list: Attachment[] }
export interface SessionList { sessions: SessionBrief[]; counts: Record<SessionWhich, number> }
export interface ReportSeg { text: string; ok: boolean }
export interface ReportBlock { type: 'h' | 'p' | 'li'; level: number; segments: ReportSeg[] }
export interface AiReport { markdown: string; blocks: ReportBlock[]; verified: number; unverified: number; lang: string; filename: string }

export type DayGroup = 'today' | 'week' | 'earlier'

/** 会话列表按最近更新分组：今天 / 最近 7 天 / 更早。 */
export function dayGroup(iso: string | null, now: Date = new Date()): DayGroup {
  if (!iso) return 'earlier'
  const t = new Date(iso)
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (t >= start) return 'today'
  return now.getTime() - t.getTime() < 7 * 86400000 ? 'week' : 'earlier'
}

/** 列表里显示的时间：今天显示时:分，其他显示月-日。 */
export function shortWhen(iso: string | null, now: Date = new Date()): string {
  if (!iso) return ''
  const t = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return dayGroup(iso, now) === 'today' ? `${p(t.getHours())}:${p(t.getMinutes())}` : `${p(t.getMonth() + 1)}-${p(t.getDate())}`
}

/** 附件的说明（类型之后的一小段）：配置 → 厂商 · 设备；文档 → 表 / 行 / 页 / 字；图片 → 不经脱敏。 */
export function attachDetail(a: Attachment, t: (k: string, p?: Record<string, unknown>) => string): string {
  const m = a.meta || {}
  if (a.kind === 'config') return [m.vendor ? m.vendor.charAt(0).toUpperCase() + m.vendor.slice(1) : '', m.device || ''].filter(Boolean).join(' · ')
  if (a.kind === 'image') return t('ask.att.notSanitized')
  const bits: string[] = []
  if (m.format === 'xlsx') bits.push(t('ask.att.sheets', { n: m.sheets ?? 0, rows: m.rows ?? 0 }))
  else if (m.format === 'pdf') bits.push(t('ask.att.pages', { n: m.pages ?? 0 }))
  else if (m.format === 'csv') bits.push(t('ask.att.rows', { n: m.rows ?? 0 }))
  else if (m.format === 'docx' && m.tables) bits.push(t('ask.att.tables', { n: m.tables }))
  bits.push(t('ask.att.chars', { n: (m.chars ?? 0).toLocaleString() }) + (m.truncated ? t('ask.att.truncated') : ''))
  return bits.join(' · ')
}

/** 会话里各轮当前版本的结果（AskView 的 turns 用）。 */
export function currentOf(turn: SessionTurn): TurnVersion {
  return turn.versions[Math.min(turn.current, turn.versions.length - 1)]
}
