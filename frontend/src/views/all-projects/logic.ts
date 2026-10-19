/** 所有项目页（管理员，预览 DevelopDocs/ui-preview/M6/all-projects.html）的纯逻辑：按属主分组、筛选、审计动作。 */
import type { ProjectRow } from '@/stores/project'

export type AllFilter = '' | 'disabled' | 'idle'
export const IDLE_DAYS = 90

/** 最近一次活动的时间：最近活动（写操作）或项目更新时间、创建时间。 */
export function lastActive(p: ProjectRow): number {
  const s = p.last_activity?.at ?? p.updated_at ?? p.created_at
  const t = s ? Date.parse(s) : NaN
  return Number.isNaN(t) ? 0 : t
}

export function isIdle(p: ProjectRow, now = Date.now(), days = IDLE_DAYS): boolean {
  return now - lastActive(p) > days * 24 * 3600 * 1000
}

export function matchAll(p: ProjectRow, q: string): boolean {
  const k = q.trim().toLowerCase()
  if (!k) return true
  return [p.name, p.slug, p.owner ?? '', ...(p.member_names ?? [])].join(' ').toLowerCase().includes(k)
}

export interface OwnerGroup { owner: string; disabled: boolean; projects: ProjectRow[] }

/** 按属主分组：自己排在最前，其余按账号名；没有属主的项目归入 ''（排在最后）。 */
export function groupByOwner(rows: ProjectRow[], me: string | null, q = '', f: AllFilter = '', now = Date.now()): OwnerGroup[] {
  const m = new Map<string, OwnerGroup>()
  for (const p of rows) {
    if (!matchAll(p, q)) continue
    if (f === 'disabled' && !p.owner_disabled) continue
    if (f === 'idle' && !isIdle(p, now)) continue
    const o = p.owner ?? ''
    const g = m.get(o) ?? { owner: o, disabled: !!p.owner_disabled, projects: [] }
    g.projects.push(p)
    m.set(o, g)
  }
  const rank = (o: string) => (o === me ? 0 : o === '' ? 2 : 1)
  return [...m.values()].sort((a, b) => rank(a.owner) - rank(b.owner) || a.owner.localeCompare(b.owner))
}

/** 导出清单（CSV，UTF-8 带 BOM 便于 Excel 打开）：项目、标识、属主、属主已停用、成员、设备（私有 / 引用）、脚本、最近活动。 */
export function projectsCsv(rows: ProjectRow[], head: string[]): string {
  const cell = (v: unknown) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [head.map(cell).join(',')]
  for (const p of rows) {
    lines.push([
      p.name, p.slug, p.owner ?? '', p.owner_disabled ? 'yes' : '', (p.member_names ?? []).join(' '),
      p.counts.devices, p.counts.private, p.counts.refs, p.counts.scripts, p.last_activity?.at ?? p.updated_at ?? '',
    ].map(cell).join(','))
  }
  return '﻿' + lines.join('\r\n') + '\r\n'
}

export interface AuditEvent { id: number; at: string; actor: string; project: string | null; project_id: number | null; action: string; detail: { method?: string; path?: string; [k: string]: unknown } | null }

/** 审计事件的动作：已知的 enter / write / transfer / delete，其他原样显示。 */
export function auditAction(a: string): 'enter' | 'write' | 'transfer' | 'delete' | null {
  return a === 'enter' || a === 'write' || a === 'transfer' || a === 'delete' ? a : null
}

/** 审计事件的说明：方法与路由（不含请求内容）。 */
export function auditDetail(d: AuditEvent['detail']): string {
  if (!d) return ''
  if (d.method) return `${d.method} ${d.path || '/'}`.trim()
  return Object.entries(d).map(([k, v]) => `${k}=${String(v)}`).join(' ')
}
