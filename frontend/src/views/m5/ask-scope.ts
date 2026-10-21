/** AI 查询的范围（REQ-051）：按设备名与厂商筛选。纯逻辑，AskView 使用。 */
import type { Device } from '@/views/devices/logic'

const VENDOR_ORDER = ['huawei', 'cisco', 'nokia']

/** 能参与查询的设备里出现过的厂商（固定顺序：华为、Cisco、Nokia，其他按字母）。 */
export function scopeVendors(list: Pick<Device, 'vendor'>[]): string[] {
  const seen = [...new Set(list.map((d) => d.vendor).filter(Boolean))]
  const rank = (v: string) => (VENDOR_ORDER.includes(v) ? VENDOR_ORDER.indexOf(v) : VENDOR_ORDER.length)
  return seen.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

/** 按设备名（不区分大小写，包含即可）与厂商筛选；只存原文的设备（没有 Profile）只在不按厂商筛选时出现。 */
export function scopeList<T extends Pick<Device, 'name' | 'vendor' | 'profile'>>(list: T[], q: string, vendor: string): T[] {
  const k = q.trim().toLowerCase()
  return list.filter((d) => (!k || d.name.toLowerCase().includes(k)) && (!vendor || (d.vendor === vendor && !!d.profile)))
}

/** 厂商的显示名（首字母大写）。 */
export function vendorLabel(v: string): string {
  return v ? v.charAt(0).toUpperCase() + v.slice(1) : v
}

export type BulkOp = 'all' | 'none' | 'invert'

/** 全选 / 清空 / 反选（REQ-051 评审）：只作用于 targets（筛出来的可查询设备），其他已选的保持不变。 */
export function applyBulk(scope: string[], targets: string[], op: BulkOp): string[] {
  const t = new Set(targets)
  const kept = scope.filter((n) => !t.has(n))
  if (op === 'none') return kept
  if (op === 'all') return [...kept, ...targets]
  const cur = new Set(scope)
  return [...kept, ...targets.filter((n) => !cur.has(n))]
}
