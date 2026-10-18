/**
 * 割接迁移页（POST /api/v1/migrate）的数据结构与纯逻辑：接口映射表的编辑与 CSV（与 CLI 的 interface-map.csv 同列）、
 * 告警分组、割接步骤（执行 / 回退）、步骤状态、割接包文件（与 CLI 输出目录相同）。
 */

export interface MapItem {
  source: string
  target: string | null
  kind: string
  source_speed: number | null
  target_speed: number | null
  basis: string
  confidence: number
  subinterfaces: string[]
  configured: boolean
  node?: string
  lines?: number[]
}
export interface Unmapped { source?: string; name?: string; reason: string; kind?: string; subinterfaces?: string[] }
export interface Item { kind: string; key: string; node: string | null; schema: string | null; lines: number[]; params: Record<string, unknown> }
export interface Step { no: number; phase: string; device: 'old' | 'new' | 'site'; key: string; params: Record<string, unknown>; commands: string[] }
export interface MigrateResult {
  source: { device: string | null; profile: string; family: string }
  target: { profile: string; family: string; model: string | null; existing: boolean }
  inventory: { source: string; model: string | null; ports: number; verified: boolean | null }
  interface_map: MapItem[]
  unmapped: Unmapped[]
  text: string
  delta: string
  warnings: Item[]
  unsupported: Item[]
  defaults: Item[]
  merge: { added: number; changed: number; same: number; conflicts: number; kept: number } | null
  verify: { checked: boolean; equal?: boolean; diffs?: number; unexplained?: number; target_existing?: number }
  script: { available: boolean; reason?: string; script?: string; rollback?: string; items?: unknown[]; verify?: { ok: boolean } }
  steps: Step[]
  stats: { interfaces: number; mapped: number; unmapped: number; lines: number; delta_lines: number; warnings: number; by_level: Record<string, number>; translate: Record<string, number> }
  /** 选用了翻译规则集时（REQ-032） */
  naming?: import('@/views/translate-rules/logic').NamingReport
}

/** 映射表的一行：auto 是后端建议，edited 是用户改过的目标（null 表示没改）。 */
export interface MapRow { item: MapItem; edited: string | null }

export const rowTarget = (r: MapRow) => (r.edited ?? r.item.target ?? '')

/** 用户改过的行 → interface_map（不迁移写成 -）。 */
export function overrides(rows: MapRow[], keep: Record<string, string> = {}): Record<string, string> {
  const m: Record<string, string> = { ...keep }
  for (const r of rows) {
    if (r.edited === null) continue
    const t = r.edited.trim()
    m[r.item.source] = t === '' ? '-' : t
  }
  return m
}

/** 映射表行的状态：skip 不迁移、low 置信度低（< 0.5）需要确认、ok。 */
export function rowState(r: MapRow): 'skip' | 'low' | 'ok' | 'manual' {
  if (!rowTarget(r) || rowTarget(r) === '-') return 'skip'
  if (r.edited !== null || r.item.basis === 'user') return 'manual'
  return r.item.confidence < 0.5 ? 'low' : 'ok'
}

/** interface-map.csv（列与 CLI 相同）。 */
export function mapCsvRows(items: MapItem[], unmapped: Unmapped[]): (string | number | boolean)[][] {
  const rows: (string | number | boolean)[][] = [['source', 'target', 'kind', 'source_speed', 'target_speed', 'basis', 'confidence', 'subinterfaces', 'configured']]
  for (const m of items) rows.push([m.source, m.target ?? '', m.kind, m.source_speed ?? '', m.target_speed ?? '', m.basis, m.confidence, m.subinterfaces.join(' '), m.configured])
  for (const u of unmapped) rows.push([u.source ?? u.name ?? '', '', u.kind ?? '', '', '', u.reason, 0, (u.subinterfaces ?? []).join(' '), ''])
  return rows
}

/** 读 CSV（逗号分隔，支持引号）。 */
export function parseCsv(text: string): string[][] {
  const out: string[][] = []
  let row: string[] = []
  let cell = ''
  let q = false
  const s = text.replace(/^﻿/, '')
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (q) {
      if (c === '"' && s[i + 1] === '"') { cell += '"'; i++ } else if (c === '"') q = false
      else cell += c
    } else if (c === '"') q = true
    else if (c === ',') { row.push(cell); cell = '' } else if (c === '\n' || c === '\r') {
      if (c === '\r' && s[i + 1] === '\n') i++
      row.push(cell); cell = ''
      if (row.some((x) => x !== '')) out.push(row)
      row = []
    } else cell += c
  }
  row.push(cell)
  if (row.some((x) => x !== '')) out.push(row)
  return out
}

/** 导入的 interface-map.csv → {旧接口: 新接口}（需要 source、target 两列；target 为空表示不迁移）。 */
export function mapFromCsv(text: string): Record<string, string> | null {
  const rows = parseCsv(text)
  if (!rows.length) return null
  const h = rows[0].map((x) => x.trim().toLowerCase())
  const si = h.indexOf('source')
  const ti = h.indexOf('target')
  if (si < 0 || ti < 0) return null
  const m: Record<string, string> = {}
  for (const r of rows.slice(1)) {
    const s = (r[si] ?? '').trim()
    if (s) m[s] = (r[ti] ?? '').trim() || '-'
  }
  return m
}

export type WarnGroup = 'map' | 'default' | 'unsup' | 'raw' | 'verify'

/** 告警分组：接口映射（migrate.warn.*）、默认值差异、目标不支持、未翻译的原文、校验。 */
export function warnGroup(i: Item): WarnGroup {
  if (i.key.startsWith('migrate.warn.verify')) return 'verify'
  if (i.key.startsWith('migrate.warn.')) return 'map'
  if (i.key.startsWith('translate.unsupported.raw') || i.key.startsWith('translate.unsupported.ext')) return 'raw'
  if (i.key.startsWith('translate.unsupported.')) return 'unsup'
  return 'default'
}

export function allItems(r: MigrateResult): Item[] {
  return [...r.warnings, ...r.unsupported, ...r.defaults]
}

export function groupCount(items: Item[]): Record<WarnGroup, number> {
  const c: Record<WarnGroup, number> = { map: 0, default: 0, unsup: 0, raw: 0, verify: 0 }
  for (const i of items) c[warnGroup(i)]++
  return c
}

/** 割接步骤分为执行与回退。 */
export function splitSteps(steps: Step[]): { run: Step[]; rollback: Step[] } {
  return { run: steps.filter((s) => s.phase !== 'rollback'), rollback: steps.filter((s) => s.phase === 'rollback') }
}

/** 步骤会不会断业务：关旧设备端口、迁线缆为 cut；隔离 BGP、启用端口为 care。 */
export function stepRisk(s: Step): '' | 'cut' | 'care' {
  if (s.key.endsWith('shutdown_old') || s.key.endsWith('move_cables')) return 'cut'
  if (s.key.endsWith('drain_bgp') || s.key.endsWith('enable_core') || s.key.endsWith('enable_access') || s.key.endsWith('restore_bgp')) return 'care'
  return ''
}

/** 校验是否通过（没有未解释的差异）。 */
export function verifyOk(r: MigrateResult): boolean {
  return !r.verify.checked || (r.verify.unexplained ?? 0) === 0
}

/** 步骤条的状态：done 完成、warn 有需要确认的、block 被阻塞。 */
export function railStates(r: MigrateResult, rows: MapRow[], dirty: boolean): ('done' | 'warn' | 'block')[] {
  const items = allItems(r)
  const low = rows.filter((x) => rowState(x) === 'low').length
  return [
    items.some((i) => warnGroup(i) === 'unsup') ? 'warn' : 'done',
    dirty || low || r.unmapped.length ? 'warn' : 'done',
    dirty ? 'warn' : 'done',
    r.script.available ? 'done' : 'warn',
    verifyOk(r) && !dirty ? 'done' : dirty ? 'block' : 'warn',
  ]
}

/** steps.txt：每步一段（序号、阶段、设备、说明、命令）。 */
export function stepsText(steps: Step[], text: (s: Step) => string, dev: (d: string) => string): string {
  return steps.map((s) => [`### ${s.no}. [${s.phase}] ${dev(s.device)}  ${text(s)}`, ...s.commands].join('\n')).join('\n\n') + '\n'
}

/** 割接包里的文件（与 CLI 的输出目录相同）。 */
export function packageFiles(r: MigrateResult, csv: string, warnCsv: string, steps: string): { name: string; text: string }[] {
  const files = [{ name: 'new-config.cfg', text: r.text }]
  if (r.target.existing) files.push({ name: 'delta.cfg', text: r.delta })
  files.push({ name: 'interface-map.csv', text: csv }, { name: 'warnings.csv', text: warnCsv }, { name: 'steps.txt', text: steps })
  files.push({ name: 'migration.json', text: JSON.stringify(r, null, 2) })
  if (r.script.available) {
    files.push({ name: 'script.txt', text: r.script.script ?? '' }, { name: 'rollback.txt', text: r.script.rollback ?? '' })
  }
  return files
}
