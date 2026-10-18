import type { Cred, ProfileRow, Scalar } from './types'

/** 默认值显示：null → 空串（界面显示占位），布尔与数字转成文字。 */
export function formatDefault(v: Scalar | undefined): string {
  if (v === null || v === undefined) return ''
  return String(v)
}

/**
 * 输入框里的默认值转回 YAML 标量：空 → null（删除默认值）、true / false → 布尔、整数 → 数字，其余保持字符串。
 * 原值是字符串时（例如 "100"）保持字符串，避免把字符串默认值改成数字。
 */
export function parseDefault(text: string, previous?: Scalar): Scalar {
  const t = text.trim()
  if (t === '') return null
  if (typeof previous === 'string') return t
  if (t === 'true') return true
  if (t === 'false') return false
  if (/^-?\d+$/.test(t)) return Number(t)
  return t
}

/** 厂商徽标：华为 HW、思科 CS，其他取前两个字母。 */
export function vendorBadge(vendor: string): { cls: string; text: string } {
  const v = vendor.toLowerCase()
  if (v === 'huawei') return { cls: 'hw', text: 'HW' }
  if (v === 'cisco') return { cls: 'cs', text: 'CS' }
  return { cls: '', text: vendor.slice(0, 2).toUpperCase() }
}

export function vendorName(vendor: string): string {
  const v = vendor.toLowerCase()
  if (v === 'huawei') return 'Huawei'
  if (v === 'cisco') return 'Cisco'
  return vendor
}

/** 可信度分布换算成占 Schema 节点总数的百分比（未填写的部分留空）。 */
export function credPercents(p: Pick<ProfileRow, 'credibility' | 'entries' | 'unfilled'>): Record<Cred, number> {
  const total = p.entries + p.unfilled || 1
  const pct = (n: number) => Math.round((n / total) * 1000) / 10
  return { verified: pct(p.credibility.verified), reviewed: pct(p.credibility.reviewed), draft: pct(p.credibility.draft) }
}

/** 列头等窄处显示的简称：去掉开头的厂商名。 */
export function shortId(id: string): string {
  return id.replace(/^(huawei|cisco)-/, '')
}

export function pct(ratio: number): number {
  return Math.round(ratio * 1000) / 10
}

/** 列表按继承树排列：父 Profile 在前，子 Profile 紧跟其后；父不在列表中的按根处理。 */
export function treeOrder<T extends { id: string; inherits: string | null }>(list: T[]): T[] {
  const ids = new Set(list.map((p) => p.id))
  const kids = new Map<string, T[]>()
  for (const p of list) {
    const k = p.inherits && ids.has(p.inherits) ? p.inherits : ''
    kids.set(k, [...(kids.get(k) ?? []), p])
  }
  const out: T[] = []
  const seen = new Set<string>()
  const walk = (k: string) => {
    for (const p of (kids.get(k) ?? []).sort((a, b) => a.id.localeCompare(b.id))) {
      if (seen.has(p.id)) continue
      seen.add(p.id)
      out.push(p)
      walk(p.id)
    }
  }
  walk('')
  return out.concat(list.filter((p) => !seen.has(p.id)))
}
