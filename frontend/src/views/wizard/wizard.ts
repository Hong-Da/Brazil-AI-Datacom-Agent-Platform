/** 首次运行向导的纯逻辑：字段定义来自 GET /setup（后端 core/setup.py 的 wizard_schema）。 */

export interface WField {
  key: string
  kind: string // str / int / bool / choice / host / port / dburl / token / secret / path（bool 的 choices 是 true / false）
  default: string | number
  choices: string[]
  min: number | null
  max: number | null
  secret: boolean
  desc: string
}
export interface WGroup { id: string; title: string; fields: WField[] }
export type Values = Record<string, string | number>

/** 一组字段在页面上的排布：监听地址与端口并排、数据库选卡、AI 开关，其余逐项显示。 */
export type Block =
  | { type: 'hostport'; host: WField; port: WField | null }
  | { type: 'dburl'; field: WField }
  | { type: 'ai'; field: WField }
  | { type: 'field'; field: WField; needsAi: boolean }

/** 界面语言在第一步单独选，不在分组里重复出现。 */
export function visibleGroups(groups: WGroup[]): WGroup[] {
  return groups
    .map((g) => ({ ...g, fields: g.fields.filter((f) => f.key !== 'ui.language') }))
    .filter((g) => g.fields.length > 0)
}

export function blocksOf(group: WGroup): Block[] {
  const host = group.fields.find((f) => f.kind === 'host') ?? null
  const port = host ? group.fields.find((f) => f.kind === 'port') ?? null : null
  const hasAi = group.fields.some((f) => f.key === 'ai.provider')
  const out: Block[] = []
  for (const f of group.fields) {
    if (f === host) out.push({ type: 'hostport', host: f, port })
    else if (f === port) continue
    else if (f.kind === 'dburl') out.push({ type: 'dburl', field: f })
    else if (f.key === 'ai.provider') out.push({ type: 'ai', field: f })
    else out.push({ type: 'field', field: f, needsAi: hasAi && f.key.startsWith('ai.') })
  }
  return out
}

export function initialValues(groups: WGroup[], keep: Values): Values {
  const out: Values = {}
  for (const g of groups) for (const f of g.fields) out[f.key] = keep[f.key] ?? f.default
  return out
}

export function isChanged(f: WField, v: string | number | undefined): boolean {
  return String(v ?? '') !== String(f.default ?? '')
}

/** 汇总里的显示值；null 表示未填写（由页面按字段给出说明，例如“使用 SQLite”）。 */
export function displayValue(f: WField, v: string | number | undefined): string | null {
  const s = v === undefined || v === null ? '' : String(v)
  if (s === '') return null
  return f.secret ? maskSecret(f, s) : s
}

/** 数据库地址只遮住密码；其他敏感值全部遮住。 */
export function maskSecret(f: WField, s: string): string {
  if (f.kind === 'dburl') return s.replace(/(:\/\/[^:/@]*:)[^@]*@/, '$1••••••@')
  return '••••••'
}

/** 后端返回的错误里属于这些字段的部分。 */
export function pickErrors(errors: Record<string, string>, keys: string[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(errors)) if (keys.includes(k)) out[k] = v
  return out
}

/** 输入框里的文字转成后端要的类型：整数与端口转成数字（无法转换时原样交给后端报错）。 */
export function coerce(f: WField, raw: string): string | number {
  if ((f.kind === 'int' || f.kind === 'port') && /^\s*-?\d+\s*$/.test(raw)) return Number(raw)
  return raw
}

export function labelKey(key: string): string {
  return `wizard.lbl.${key.replace(/\./g, '_')}`
}

/** 示例里的访问地址：0.0.0.0 换成本机地址。 */
export function displayHost(host: string): string {
  return host === '0.0.0.0' || host === '::' || host === '' ? '127.0.0.1' : host
}

/** 语言卡片的说明用各自的语言写，不随界面语言变化。 */
export const LANG_NOTES: Record<string, string> = {
  'zh-CN': '界面、报告默认语言，可随时切换',
  en: 'Interface and default report language',
  'pt-BR': 'Idioma da interface e dos relatórios',
}

/* ---------- 确认页（M6-9）：按组汇总、突出改动、统一校验、需重启的项 ---------- */

/** 当前运行实例的监听地址（GET /setup 的 running）；与新取值不同的项需要重启才生效。 */
export type Running = Record<string, string | number>

export interface ConfirmRow {
  field: WField
  changed: boolean
  /** 敏感值只显示“已设置 / 未设置”（数据库地址除外：它显示遮住密码的地址） */
  secretState: 'set' | 'unset' | null
  restart: boolean
  error: string
}

export interface ConfirmStats { changed: number; unchanged: number; restart: string[]; errors: number }

export function needsRestart(key: string, v: string | number | undefined, running: Running): boolean {
  return key in running && String(v ?? '') !== String(running[key] ?? '')
}

export function confirmRow(f: WField, values: Values, errors: Record<string, string>, running: Running): ConfirmRow {
  const v = values[f.key]
  const opaque = f.secret && f.kind !== 'dburl'
  return {
    field: f,
    changed: isChanged(f, v),
    secretState: opaque ? (String(v ?? '') ? 'set' : 'unset') : null,
    restart: needsRestart(f.key, v, running),
    error: errors[f.key] ?? '',
  }
}

/** AI 分组在没有选接口时只显示“未配置”，不列其余字段。 */
export function confirmFields(g: WGroup, values: Values): WField[] {
  if (g.fields.some((f) => f.key === 'ai.provider') && !values['ai.provider']) return []
  return g.fields
}

export function confirmRows(g: WGroup, values: Values, errors: Record<string, string>, running: Running, onlyChanged = false): ConfirmRow[] {
  return confirmFields(g, values)
    .map((f) => confirmRow(f, values, errors, running))
    .filter((r) => !onlyChanged || r.changed || r.error)
}

/** 全部分组的汇总：改了几项、保持默认几项、需要重启的字段、问题数（含管理员一步的 admin.* 错误）。 */
export function confirmStats(groups: WGroup[], values: Values, errors: Record<string, string>, running: Running): ConfirmStats {
  let changed = 0, unchanged = 0
  const restart: string[] = []
  for (const g of groups) {
    for (const r of confirmRows(g, values, errors, running)) {
      if (r.changed) changed++
      else unchanged++
      if (r.restart) restart.push(r.field.key)
    }
  }
  const keys = new Set(groups.flatMap((g) => g.fields.map((f) => f.key)))
  const errorCount = Object.keys(errors).filter((k) => errors[k] && (keys.has(k) || k.startsWith('admin.'))).length
  return { changed, unchanged, restart, errors: errorCount }
}

/** 某一组里的问题数。 */
export function groupErrors(g: WGroup, errors: Record<string, string>): number {
  return g.fields.filter((f) => errors[f.key]).length
}
