/**
 * 升级到 0.6.0（M6）后的说明页：每个账号第一次登录看到一次（记在浏览器本地）。
 * 只有确实有从旧数据迁移来的项目（默认项目 migrated_from.type = upgrade，或由配置检查项目转成的 check_project）时才显示。
 */

export const UPGRADE_SEEN_KEY = 'lmesh-upgrade-seen'

interface Migrated { migrated_from?: { type?: string } | null }

export function migratedProjects<T extends Migrated>(mine: T[]): T[] {
  return mine.filter((p) => p.migrated_from?.type === 'upgrade' || p.migrated_from?.type === 'check_project')
}

export function upgradeSeen(username: string, store: Pick<Storage, 'getItem'> | null = safeStorage()): boolean {
  try { return !!store?.getItem(`${UPGRADE_SEEN_KEY}:${username}`) } catch { return true }
}

export function markUpgradeSeen(username: string, store: Pick<Storage, 'setItem'> | null = safeStorage()): void {
  try { store?.setItem(`${UPGRADE_SEEN_KEY}:${username}`, '1') } catch { /* 忽略 */ }
}

/** 是否该显示升级说明：没看过，且我的项目里有迁移来的。浏览器存储不可用时不显示（免得每次都弹）。 */
export function shouldShowUpgrade(username: string | null | undefined, lists: { mine: Migrated[] } | null | undefined, store: Pick<Storage, 'getItem'> | null = safeStorage()): boolean {
  if (!username || !lists || !store) return false
  if (upgradeSeen(username, store)) return false
  return migratedProjects(lists.mine).length > 0
}

function safeStorage(): Storage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}
