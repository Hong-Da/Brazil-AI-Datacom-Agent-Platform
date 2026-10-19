/** 设备页在项目里的纯逻辑（REQ-035）：来源筛选、统计、引用的版本序号、有新版本的引用、行菜单项。 */
import type { Device } from './logic'

export interface ProjectDevice extends Device {
  source?: 'private' | 'public'
  origin?: string | null
  origin_note?: string | null
  policy?: 'follow' | 'pin'
  pinned_version_id?: number | null
  pinned_seq?: number | null
  public_latest_version_id?: number | null
  newer_available?: boolean
}

export type SrcFilter = '' | 'private' | 'public'

export const isPublic = (d: ProjectDevice): boolean => d.source === 'public'

export function bySource(list: ProjectDevice[], f: SrcFilter): ProjectDevice[] {
  if (!f) return list
  return list.filter((d) => (f === 'public' ? isPublic(d) : !isPublic(d)))
}

export function stats(list: ProjectDevice[]): { total: number; private: number; refs: number; newer: number } {
  const refs = list.filter(isPublic)
  return { total: list.length, private: list.length - refs.length, refs: refs.length, newer: refs.filter((d) => d.newer_available).length }
}

/** 当前使用的版本序号（vN）：私有与跟随最新的是版本数；固定的是固定版本的序号（后端 pinned_seq）。 */
export function currentSeq(d: ProjectDevice): number | null {
  if (isPublic(d) && d.policy === 'pin') return d.pinned_seq ?? null
  return d.versions || null
}

/** 固定在旧版本、公共库已有更新版本的引用（页面顶部提示）。 */
export const newerRefs = (list: ProjectDevice[]): ProjectDevice[] => list.filter((d) => isPublic(d) && d.policy === 'pin' && d.newer_available)

export type RowAction = 'follow' | 'pinLatest' | 'copyPrivate' | 'unlink' | 'rebuild' | 'history' | 'copyTo' | 'delete'

/**
 * 行尾菜单：引用的公共设备可以改版本策略、复制为私有、解除引用；私有设备可以重新解析、看版本、复制到其他项目、删除。
 * canWrite 为假（只读成员、只读令牌）时只留查看类与“复制到我的其他项目”（只需能查看本项目）。
 */
export function rowActions(d: ProjectDevice, canWrite: boolean): RowAction[] {
  if (isPublic(d)) {
    if (!canWrite) return ['history', 'copyTo']
    const out: RowAction[] = []
    if (d.policy === 'pin') out.push('follow')
    if (d.policy !== 'pin' || d.newer_available) out.push('pinLatest')
    out.push('copyPrivate', 'history', 'copyTo', 'unlink')
    return out
  }
  return canWrite ? ['rebuild', 'history', 'copyTo', 'delete'] : ['history', 'copyTo']
}
