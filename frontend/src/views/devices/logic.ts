/** 设备与导入页的纯逻辑：设备状态与筛选、导入文件筛选、脱敏结果汇总、时间格式。 */

import { vendorMark } from '@/vendor'

export interface Device {
  id: number
  name: string
  vendor: string
  sw_version: string
  profile: string
  versions: number
  latest_version_id: number | null
  source_name: string
  collected_at: string | null
  lines?: number
  parsed?: boolean
  unknown?: number
  coverage?: number
  roundtrip?: boolean
  kb_version?: string
  stale?: boolean
  // REQ-044：Profile 来源与近似标记
  profile_source?: string
  approx?: boolean
  unsupported?: boolean
  unknown_ratio?: number | null
}

export type DevState = '' | 'fail' | 'stale' | 'err' | 'unknown' | 'approx' | 'unsupported'
export interface DevFilter { q: string; vendor: string; state: DevState }

export function filterDevices(list: Device[], f: DevFilter): Device[] {
  const q = f.q.trim().toLowerCase()
  return list.filter((d) => {
    if (q && ![d.name, d.profile, d.sw_version, d.source_name].join(' ').toLowerCase().includes(q)) return false
    if (f.vendor && (d.vendor || '') !== f.vendor) return false
    if (f.state === 'fail' && !(d.parsed && d.roundtrip === false)) return false
    if (f.state === 'stale' && !d.stale) return false
    if (f.state === 'err' && d.parsed !== false) return false
    if (f.state === 'unknown' && !(d.unknown && d.unknown > 0)) return false
    if (f.state === 'approx' && !d.approx) return false
    if (f.state === 'unsupported' && !d.unsupported) return false
    return true
  })
}

/** 每个厂商的设备数，按数量从多到少；厂商为空的计为 ''。 */
export function vendorCounts(list: Device[]): [string, number][] {
  const m = new Map<string, number>()
  for (const d of list) m.set(d.vendor || '', (m.get(d.vendor || '') ?? 0) + 1)
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

export function vendorLabel(v: string): string {
  const m = vendorMark(v)
  return m.key && m.key === (v || '').toLowerCase() ? m.name : v
}

/** 与后端 importer.CONFIG_SUFFIXES 一致：无扩展名、.txt .cfg .conf .config .log .zip。 */
const SUFFIXES = new Set(['', '.txt', '.cfg', '.conf', '.config', '.log', '.zip'])
export const MAX_FILE_BYTES = 20 * 1024 * 1024

export function acceptFile(name: string): boolean {
  const base = name.split(/[\\/]/).pop() ?? name
  if (!base || base.startsWith('.')) return false
  const i = base.lastIndexOf('.')
  return SUFFIXES.has(i > 0 ? base.slice(i).toLowerCase() : '')
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** ISO 时间 → "MM-DD HH:mm"（本地时区）；无效时原样返回。 */
export function fmtTime(iso: string | null | undefined, withYear = false): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  const md = `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  return withYear ? `${d.getFullYear()}-${md}` : md
}

export interface ImportFileResult {
  source: string
  ok: boolean
  device: string
  vendor: string
  version: string
  profile: string
  lines: number
  version_id: number | null
  sanitized: Record<string, number>
  unknown: number
  coverage: number | null
  error: string
}

/** 脱敏类别顺序与后端 sanitize.CATEGORIES 一致。 */
export const SANITIZE_CATEGORIES = ['secret', 'community', 'key_block', 'ip', 'hostname', 'description', 'user', 'identifier', 'custom'] as const

export function sanitizedEntries(s: Record<string, number> | null | undefined): [string, number][] {
  const e = Object.entries(s ?? {}).filter(([, n]) => n > 0)
  const order = (k: string) => {
    const i = (SANITIZE_CATEGORIES as readonly string[]).indexOf(k)
    return i < 0 ? 99 : i
  }
  return e.sort((a, b) => order(a[0]) - order(b[0]))
}

export function sanitizedTotal(s: Record<string, number> | null | undefined): number {
  return Object.values(s ?? {}).reduce((a, b) => a + b, 0)
}

export interface ImportTotals { files: number; ok: number; failed: number; replacements: number; unknown: number }

export function importTotals(rs: ImportFileResult[]): ImportTotals {
  return {
    files: rs.length,
    ok: rs.filter((r) => r.ok).length,
    failed: rs.filter((r) => !r.ok).length,
    replacements: rs.reduce((a, r) => a + sanitizedTotal(r.sanitized), 0),
    unknown: rs.reduce((a, r) => a + (r.unknown || 0), 0),
  }
}
