/** 厂商识别：从厂商名、平台族或 Profile 编号得到厂商与界面标记（华为 / Cisco / Nokia），各页面共用。 */

export type VendorKey = 'huawei' | 'cisco' | 'nokia' | ''

export interface VendorMark {
  key: VendorKey
  /** 样式类：.vendor i.hw / .cs / .nk，未知为空 */
  cls: 'hw' | 'cs' | 'nk' | ''
  /** 两字母标记 */
  abbr: string
  /** 单字母标记 */
  letter: string
  /** 显示名 */
  name: string
}

const MARKS: Record<Exclude<VendorKey, ''>, Omit<VendorMark, 'key'>> = {
  huawei: { cls: 'hw', abbr: 'HW', letter: 'H', name: 'Huawei' },
  cisco: { cls: 'cs', abbr: 'CS', letter: 'C', name: 'Cisco' },
  nokia: { cls: 'nk', abbr: 'NK', letter: 'N', name: 'Nokia' },
}

/** 厂商 / 平台族 / Profile 编号 → 厂商键（按前缀，不区分大小写）。 */
export function vendorKey(s: string | null | undefined): VendorKey {
  const v = (s ?? '').trim().toLowerCase()
  for (const k of Object.keys(MARKS) as Exclude<VendorKey, ''>[]) if (v.startsWith(k)) return k
  return ''
}

/** 界面标记；不认识的厂商 cls 为空、abbr 取前两个字母（没有时为 ?）。 */
export function vendorMark(s: string | null | undefined): VendorMark {
  const key = vendorKey(s)
  if (key) return { key, ...MARKS[key] }
  const raw = (s ?? '').trim()
  return { key, cls: '', abbr: raw ? raw.slice(0, 2).toUpperCase() : '?', letter: raw ? raw[0].toUpperCase() : '?', name: raw }
}

/** 显示名：认识的厂商用品牌名，否则原样返回。 */
export function vendorName(s: string | null | undefined): string {
  return vendorMark(s).name
}

/** Nokia 是否用 MD-CLI（平台族 / Profile 含 sros-md）；任何一个提示命中即可。 */
export function isNokiaMd(...hints: (string | null | undefined)[]): boolean {
  return hints.some((h) => /(^|-)sros-md(-|$)/i.test(h ?? ''))
}

/** Profile 编号去掉开头的厂商名，用于窄处显示。 */
export function stripVendor(id: string): string {
  return id.replace(/^(huawei|cisco|nokia)-/, '')
}

/**
 * 空配置脚本骨架：按厂商给出进入 / 提交配置的框架。hints 是厂商、平台族、Profile 等（任意顺序），
 * 第一个能识别出厂商的为准；Nokia 有 MD-CLI 线索时用 MD-CLI，否则用 Classic CLI；都不认识时用华为。
 */
export function starterScript(...hints: (string | null | undefined)[]): string {
  const key = hints.map(vendorKey).find((k) => k) ?? ''
  if (key === 'cisco') return 'configure terminal\n\nend\n'
  if (key === 'nokia') return isNokiaMd(...hints) ? 'edit-config private\n\ncommit\nquit-config\n' : 'exit all\nconfigure\n\nexit all\n'
  return 'system-view\n\ncommit\n'
}

/** 修复命令里注释行的前缀：Cisco 用 !，华为与 Nokia 用 #。 */
export function commentPrefix(s: string | null | undefined): string {
  return vendorKey(s) === 'cisco' ? '!' : '#'
}
