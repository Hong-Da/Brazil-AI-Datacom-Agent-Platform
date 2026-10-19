/**
 * 模板与翻译规则集的归属（REQ-036）：共享（内置或维护员维护，全员可用）与我的（只属于自己的工作空间）。
 * 管理员还能看到别人的私有模板 / 规则集（scope = user），放在“我的”一侧并标出属主。
 */

export type AssetScope = 'shared' | 'mine' | 'user' | 'builtin'
export type AssetTab = 'mine' | 'shared'

export interface Owned { id: string; scope?: AssetScope; owner?: string | null; editable?: boolean }

/** 页签：我的（mine，管理员另有别人的 user）/ 共享（shared、builtin，没有归属信息的旧数据也算共享）。 */
export function tabOf(x: Owned): AssetTab {
  return x.scope === 'mine' || x.scope === 'user' ? 'mine' : 'shared'
}

export function splitByTab<T extends Owned>(rows: T[]): Record<AssetTab, T[]> {
  const out: Record<AssetTab, T[]> = { mine: [], shared: [] }
  for (const r of rows) out[tabOf(r)].push(r)
  return out
}

/** 没有 editable 字段的旧接口按可编辑处理（与 M6 以前的行为一致）。 */
export function canEdit(x: { editable?: boolean } | null | undefined): boolean {
  return !!x && x.editable !== false
}

/** 打开页面时选哪个页签：指定的条目在哪边就去哪边；否则有我的就看我的，没有就看共享的。 */
export function initialTab<T extends Owned>(rows: T[], selected: string | null): AssetTab {
  const hit = selected ? rows.find((r) => r.id === selected) : undefined
  if (hit) return tabOf(hit)
  return rows.some((r) => tabOf(r) === 'mine') ? 'mine' : 'shared'
}

/** 复制为我的：新编号建议 <原编号>-copy，已存在时加 -2、-3…（只做建议，用户可以改）。 */
export function copyId(id: string, existing: Iterable<string>): string {
  const taken = new Set(existing)
  const base = `${id}-copy`.slice(0, 80)
  if (!taken.has(base)) return base
  for (let i = 2; ; i++) {
    const c = `${base}-${i}`
    if (!taken.has(c)) return c
  }
}

/** 编号规则（与模板 / 规则集文件名一致）：字母数字开头，字母、数字、点、下划线、短横线，最长 80。 */
export function validAssetId(id: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(id.trim())
}
