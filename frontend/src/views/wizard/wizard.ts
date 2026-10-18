/** 首次运行向导的纯逻辑：字段定义来自 GET /setup（后端 core/setup.py 的 wizard_schema）。 */

export interface WField {
  key: string
  kind: string // str / int / choice / host / port / dburl / token / secret / path
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
