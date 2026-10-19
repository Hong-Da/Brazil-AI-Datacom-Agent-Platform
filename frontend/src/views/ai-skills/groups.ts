/** AI skill 按功能分组（REQ-033 评审修改）：分组、按组筛选、跨组搜索。组的顺序与名称来自 GET /ai/skills 的 groups。 */

import type { L3 } from './types'

export interface SkillGroup { id: string; title: L3; count: number }
/** 分组需要的 skill 字段（与 SkillInfo 兼容）。 */
export interface Groupable { id: string; title: L3; description: L3; group?: string; used_by?: string }
export interface GroupBlock<S> { group: SkillGroup; skills: S[]; total: number }
export interface GroupFilter { group?: string; q?: string; use?: string; showEmpty?: boolean }

const OTHER = 'other'

/** 搜索：编号、标题、说明（三种语言都算），不区分大小写。 */
export function matches(s: Groupable, q: string): boolean {
  const k = q.trim().toLowerCase()
  if (!k) return true
  return [s.id, ...Object.values(s.title ?? {}), ...Object.values(s.description ?? {})].some((v) => String(v).toLowerCase().includes(k))
}

/** 按组排好：组的顺序同 groups；skill 的组不在列表里的归入 other（没有 other 时补一个）。
 *  筛选后只保留有匹配的组；showEmpty 时（不搜索、不筛使用者时）也列出本来就没有 skill 的组。total 是组内全部 skill 数。 */
export function groupSkills<S extends Groupable>(groups: SkillGroup[], skills: S[], f: GroupFilter = {}): GroupBlock<S>[] {
  const list = groups.some((g) => g.id === OTHER) ? [...groups] : [...groups, { id: OTHER, title: {}, count: 0 }]
  const known = new Set(list.map((g) => g.id))
  const all = new Map<string, S[]>(list.map((g) => [g.id, []]))
  for (const s of skills) all.get(s.group && known.has(s.group) ? s.group : OTHER)!.push(s)
  const filtering = !!(f.q?.trim() || f.use)
  const out: GroupBlock<S>[] = []
  for (const g of list) {
    if (f.group && g.id !== f.group) continue
    const inGroup = all.get(g.id) ?? []
    const shown = inGroup.filter((s) => (!f.use || s.used_by === f.use) && matches(s, f.q ?? ''))
    if (shown.length || (f.showEmpty && !filtering && !inGroup.length && g.id !== OTHER)) out.push({ group: g, skills: shown, total: inGroup.length })
  }
  return out
}

/** 组筛选的选项：有 skill 的组（含个数），顺序同 groups。 */
export function groupChips<S extends Groupable>(groups: SkillGroup[], skills: S[]): { id: string; title: L3; n: number }[] {
  return groupSkills(groups, skills).map((b) => ({ id: b.group.id, title: b.group.title, n: b.total }))
}
