/** 公共设备库页（管理员，预览 DevelopDocs/ui-preview/M6/public-devices.html）的纯逻辑：统计、筛选、版本时间线。 */
import type { PubDevice, Version } from '../add-device/logic'

export type PubFilter = '' | 'fresh' | 'unused'
const DAY = 24 * 3600 * 1000

/** 最新版本是 24 小时内导入的。 */
export function isFresh(d: PubDevice, now = Date.now()): boolean {
  if (!d.collected_at) return false
  const t = Date.parse(d.collected_at)
  return !Number.isNaN(t) && now - t < DAY
}

export function filterPublic(list: PubDevice[], q: string, f: PubFilter, now = Date.now()): PubDevice[] {
  const k = q.trim().toLowerCase()
  return list.filter((d) => {
    if (f === 'fresh' && !isFresh(d, now)) return false
    if (f === 'unused' && d.refs.length) return false
    return !k || [d.name, d.profile, d.sw_version, d.vendor].join(' ').toLowerCase().includes(k)
  })
}

export interface PubStats { total: number; referenced: number; projects: number; fresh: number; pinnedOld: number }

export function publicStats(list: PubDevice[], now = Date.now()): PubStats {
  const projects = new Set<string>()
  let pinnedOld = 0
  for (const d of list) {
    for (const r of d.refs) {
      projects.add(r.project)
      if (r.policy === 'pin' && r.version_id !== d.latest_version_id) pinnedOld++
    }
  }
  return {
    total: list.length,
    referenced: list.filter((d) => d.refs.length).length,
    projects: projects.size,
    fresh: list.filter((d) => isFresh(d, now)).length,
    pinnedOld,
  }
}

export interface TimelineRow { id: number; seq: number; at: string | null; follow: number; pinned: number; latest: boolean }

/** 版本时间线（新的在前）：每个版本被几个项目固定；最新版本另计跟随最新的项目。 */
export function timeline(d: PubDevice, versions: Version[]): TimelineRow[] {
  const latestId = d.latest_version_id ?? Math.max(0, ...versions.map((v) => v.id))
  return [...versions]
    .sort((a, b) => b.id - a.id)
    .map((v) => ({
      id: v.id,
      seq: v.seq,
      at: v.collected_at,
      latest: v.id === latestId,
      pinned: d.refs.filter((r) => r.policy === 'pin' && r.version_id === v.id).length,
      follow: v.id === latestId ? d.refs.filter((r) => r.policy === 'follow').length : 0,
    }))
}
