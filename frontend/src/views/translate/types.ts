/** POST /translate 与 POST /render（canonical、with_defaults）的返回结构。字段说明见 docs/project-spec.md“配置翻译与规范渲染”。 */

export interface TrItem {
  kind: string
  key: string
  node: string | null
  schema: string | null
  /** 源配置行号（1 起） */
  lines: number[]
  params: Record<string, unknown>
}

export interface OutLine {
  no: number
  text: string
  kind: string
  origin: string
  nodes: string[]
  card: string | null
}

export interface TranslateStats {
  facts: number
  rendered: number
  lines: number
  unsupported: number
  not_translated: number
  defaults_omitted: number
  default_differs: number
  default_unknown: number
  defaults_same: number
  warnings: number
}

export interface VerifyInfo { checked: boolean; equal?: boolean; diffs?: number; unexplained?: number }

export interface TranslateResult {
  /** REQ-044：来源设备使用近似 Profile 时的下发前提示 */
  approx_profile?: { device: string; profile: string; source: string; rule_id: number | null } | null
  source: { device: string | null; profile: string; family: string }
  target: { profile: string; family: string }
  interface_map: Record<string, string>
  text: string
  lines: OutLine[]
  warnings: TrItem[]
  unsupported: TrItem[]
  defaults: TrItem[]
  stats: TranslateStats
  verify: VerifyInfo
  /** 选用了翻译规则集时（REQ-032）：改名清单、端口映射、冲突、命名规范告警 */
  naming?: import('@/views/translate-rules/logic').NamingReport
  /** M8-4：译文中来自采纳的 AI 写法的行号（翻译未支持项） */
  ai_lines?: number[]
}

export interface RenderResult {
  text: string
  profile: string
  family: string
  mode: string
  with_defaults: boolean
  default_lines: number[]
  uncovered: string[]
  lines: OutLine[]
}

/** 告警分组：默认值、目标不支持、未翻译的原文、推导值与其他。 */
export type Group = 'default' | 'unsup' | 'raw' | 'infer'
export const GROUPS: Group[] = ['default', 'unsup', 'raw', 'infer']
export type Level = 'error' | 'warning' | 'info'

export interface Warn {
  id: string
  group: Group
  level: Level
  /** 来自 warnings / unsupported / defaults 哪个列表 */
  from: 'warnings' | 'unsupported' | 'defaults'
  item: TrItem
}

export interface GraphNodeLite { id: string; kind: string; lines?: number[]; origin?: string }
