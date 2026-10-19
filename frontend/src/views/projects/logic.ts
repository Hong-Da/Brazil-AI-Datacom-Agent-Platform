/** 我的项目 / 项目切换器的纯逻辑：搜索、标识生成与校验、最近活动的说明。 */
import { activityKey } from '@/project/scope'

export interface Searchable { name: string; slug: string; owner?: string | null }

/** 按名称、标识、属主搜索（不区分大小写）。 */
export function matchProject(p: Searchable, q: string): boolean {
  const k = q.trim().toLowerCase()
  if (!k) return true
  return `${p.name} ${p.slug} ${p.owner ?? ''}`.toLowerCase().includes(k)
}

/** 与后端（core/projects.py 的 SLUG_RE）一致：2–64 个小写字母、数字、短横线，不以短横线开头。 */
export const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,63}$/

export function validSlug(s: string): boolean {
  return SLUG_RE.test(s)
}

/** 由名称生成标识的建议（中文等非 ASCII 名称生成不出时返回空，让用户自己填，后端也会自动生成）。 */
export function suggestSlug(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-')
    .slice(0, 64)
    .replace(/-+$/, '')
}

export type SortKey = 'act' | 'name'

/** 项目排序：按最近活动（没有活动时按更新时间）新的在前，或按名称。不修改原数组。 */
export function sortProjects<T extends { name: string; updated_at: string | null; last_activity: { at: string } | null }>(rows: T[], by: SortKey): T[] {
  const out = rows.slice()
  if (by === 'name') return out.sort((a, b) => a.name.localeCompare(b.name))
  const t = (p: T) => Date.parse(p.last_activity?.at ?? p.updated_at ?? '') || 0
  return out.sort((a, b) => t(b) - t(a))
}

/** 项目里我能做什么（卡片菜单与设置页按它显示按钮）。role 为 GET /projects 的 role。 */
export function projectAbilities(role: string | null | undefined, readOnlyToken = false): { edit: boolean; manage: boolean; leave: boolean } {
  const edit = !readOnlyToken && (role === 'owner' || role === 'edit' || role === 'admin')
  const manage = !readOnlyToken && (role === 'owner' || role === 'admin')
  return { edit, manage, leave: !readOnlyToken && (role === 'edit' || role === 'read') }
}

/** 删除确认：输入的标识与项目标识一致（去掉首尾空白）。 */
export function confirmMatches(input: string, slug: string): boolean {
  return input.trim() === slug
}

/** 新建 / 复制项目的请求体：空标识不传（后端由名称生成），名称去空白。 */
export function projectBody(name: string, slug: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  const body: Record<string, unknown> = { name: name.trim(), ...extra }
  const s = slug.trim().toLowerCase()
  if (s) body.slug = s
  return body
}

/** 名称首字母头像（属主在前，最多 max 个）。 */
export function avatars(owner: string | null | undefined, names: string[] | undefined, max = 5): string[] {
  const all = [...(owner ? [owner] : []), ...(names ?? []).filter((n) => n !== owner)]
  return all.slice(0, max)
}

/** 最近活动：{actor, action, at} → 文案键与参数；映射不到时 key 为 null，显示原文。 */
export function activity(a: { actor?: string | null; action: string; at: string } | null | undefined): { key: string | null; raw: string; actor: string; at: string } | null {
  if (!a) return null
  return { key: activityKey(a.action), raw: a.action, actor: a.actor ?? '', at: a.at }
}
