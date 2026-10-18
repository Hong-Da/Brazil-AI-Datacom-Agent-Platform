/**
 * 审计表格导出页（REQ-022）的纯逻辑：列的选择与排序、请求体、预览行的分组与排序、等价的 CLI / API 写法。
 * 后端接口：GET /export/presets、GET /export/fields、POST /export/table（结构见 docs/api.md）。
 */

export type L3 = Record<string, string>
export interface PresetColumn { key: string; field: string | null; derive: string | null; schema: string | null; type: string; secret: boolean; label: L3; empty: L3 | null; off?: boolean }
export interface NamedFilter { id: string; label: L3; field: string; op: string; value?: unknown }
export interface Preset { id: string; aliases: string[]; object: string; title: L3; description: L3; columns: PresetColumn[]; where: string[]; filters: NamedFilter[] }
export interface FieldInfo { path: string; type: string; secret: boolean; semantic: Partial<L3> }
export interface Cell { value: unknown; origin: 'explicit' | 'default' | 'derived' | 'none' | 'unsupported'; nodes: string[]; lines: number[]; secret?: boolean }
export interface Row { device: string; device_id: number | null; version_id: number | null; profile: string; node: string; key: unknown; lines: number[]; cells: Cell[] }
export interface TableDevice { name: string; device_id: number | null; version_id: number | null; collected_at: string | null; profile: string; family: string; rows: number }
export interface TableResult {
  preset: string | null
  object: string
  title: L3 | null
  columns: PresetColumn[]
  filters: { id?: string; field: string; op: string; value?: unknown }[]
  devices: TableDevice[]
  rows: Row[]
  kb_version: string
  summary: { rows: number; devices: number; columns: number; default_cells: number; unsupported_cells: number; secret_columns: number }
}
export interface ColItem { key: string; label: L3 | null; secret: boolean; derived: boolean; on: boolean }
export interface AdHoc { field: string; op: string; value: string }

export const OPS = ['=', '!=', '~', '!~', '>', '<', '>=', '<=', 'exists', 'not_exists'] as const

/** 列清单：模板的列在前（模板标为 off 的默认不勾选），其余可用字段与派生列在后（不勾选）。 */
export function columnItems(preset: Preset | null, fields: FieldInfo[], derives: string[]): ColItem[] {
  const out: ColItem[] = []
  const seen = new Set<string>()
  for (const c of preset?.columns ?? []) {
    out.push({ key: c.key, label: c.label, secret: c.secret, derived: !!c.derive, on: !c.off })
    seen.add(c.key)
  }
  for (const f of fields) {
    if (seen.has(f.path)) continue
    seen.add(f.path)
    out.push({ key: f.path, label: null, secret: f.secret, derived: false, on: !preset && !f.secret && out.length < 6 })
  }
  for (const d of derives) {
    const k = `derive:${d}`
    if (seen.has(k)) continue
    seen.add(k)
    out.push({ key: k, label: null, secret: false, derived: true, on: false })
  }
  return out
}

/** 拖动排序：把 from 移到 to 的位置。 */
export function moveKey(list: ColItem[], from: string, to: string): ColItem[] {
  if (from === to) return list
  const out = [...list]
  const i = out.findIndex((c) => c.key === from)
  const j = out.findIndex((c) => c.key === to)
  if (i < 0 || j < 0) return list
  const [it] = out.splice(i, 1)
  out.splice(j, 0, it)
  return out
}

export interface Selection {
  preset: Preset | null
  object: string
  columns: ColItem[]
  where: string[]
  adhoc: AdHoc[]
  devices: string[]
  allDevices: boolean
  defaults: boolean
  canonical: boolean
  style: string
}

/** POST /export/table 的请求体（预览用 json；下载时另加 format / lang / sheets）。 */
export function tableBody(s: Selection): Record<string, unknown> {
  const body: Record<string, unknown> = {
    columns: s.columns.filter((c) => c.on).map((c) => c.key),
    where: s.where,
    filters: s.adhoc.filter((f) => f.field && f.op).map((f) => (f.op === 'exists' || f.op === 'not_exists' ? { field: f.field, op: f.op } : { field: f.field, op: f.op, value: f.value })),
    devices: s.allDevices ? 'all' : s.devices,
    defaults: s.defaults,
    canonical_names: s.canonical,
    style: s.style,
  }
  if (s.preset) body.preset = s.preset.id
  else body.object = s.object
  return body
}

/** 预览行排序：设备 → 配置顺序，或对象名 → 设备。 */
export function sortRows(rows: Row[], sort: 'dev' | 'key', devOrder: string[]): Row[] {
  const di = (r: Row) => { const i = devOrder.indexOf(r.device); return i < 0 ? 999 : i }
  const ln = (r: Row) => r.lines[0] ?? 0
  const key = (r: Row) => (Array.isArray(r.key) ? r.key.join(' ') : String(r.key ?? ''))
  const out = [...rows]
  if (sort === 'dev') out.sort((a, b) => di(a) - di(b) || ln(a) - ln(b))
  else out.sort((a, b) => key(a).localeCompare(key(b), undefined, { numeric: true }) || di(a) - di(b))
  return out
}

/** 一格的显示文字（敏感字段由调用方显示为“已配置 / 未配置”）。 */
export function cellText(c: Cell): string {
  const v = c.value
  if (v === null || v === undefined || v === '') return ''
  if (Array.isArray(v)) return v.map((x) => (x === null || x === undefined ? '' : String(x))).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export const sheetName = (s: string) => s.replace(/[\\/?*[\]:]/g, '_').slice(0, 31)

/** 等价的 CLI 写法（多行，复制时合成一行）。 */
export function cliText(s: Selection, fmt: string, sheets: string, lang: string): string {
  const a = ['lmesh export table']
  a.push(s.allDevices ? '--all' : s.devices.join(' '))
  if (s.preset) a.push(`--preset ${s.preset.id}`)
  else a.push(`--object ${s.object}`)
  const cols = s.columns.filter((c) => c.on).map((c) => c.key)
  const presetCols = (s.preset?.columns ?? []).filter((c) => !c.off).map((c) => c.key)
  if (!s.preset || cols.join(',') !== presetCols.join(',')) a.push(`--fields ${cols.join(',')}`)
  if (s.where.join(',') !== (s.preset?.where ?? []).join(',') && s.where.length) a.push(`--where ${s.where.join(',')}`)
  for (const f of s.adhoc.filter((x) => x.field)) a.push(`--filter '${f.field} ${f.op}${f.op.includes('exists') ? '' : ` ${f.value}`}'`)
  if (!s.defaults) a.push('--no-defaults')
  if (s.canonical) a.push('--canonical-names')
  if (s.style !== 'huawei') a.push(`--style ${s.style}`)
  a.push(`--format ${fmt}`)
  if (fmt === 'xlsx') a.push(`--sheets ${sheets}`)
  a.push(`--table-lang ${lang} -o table.${fmt}`)
  return a.join(' \\\n    ')
}

export function apiText(s: Selection, fmt: string, sheets: string, lang: string): string {
  const b: Record<string, unknown> = { ...tableBody(s), format: fmt, lang }
  if (fmt === 'xlsx') b.sheets = sheets
  return `POST /api/v1/export/table\n${JSON.stringify(b)}`
}
