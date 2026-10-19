/** 模板接口（GET /templates、GET /templates/{id}、POST /templates/check|draft）的返回结构。见 docs/project-spec.md“参数化模板与批量生成”。 */

export type LangMap = Record<string, string>

export interface TemplateInfo {
  id: string
  version: number
  title: LangMap
  description?: LangMap
  profile: string
  profiles: string[]
  family: string
  file: string
  vars: number
  blocks: number
  valid: boolean
  issues: TemplateIssue[]
  /** 归属（M6）：shared 共享 / mine 我的 / user 别人的（管理员才看得到）/ builtin 内置 */
  scope?: TemplateScope
  owner?: string | null
  editable?: boolean
}

export type TemplateScope = 'shared' | 'mine' | 'user' | 'builtin'

export interface TemplateIssue { where?: string; key: string; args?: Record<string, unknown> }

export interface VarInfo {
  name: string
  type: string
  block: string | null
  derived: boolean
  expr?: string
  example?: unknown
  default?: unknown
  min?: number
  max?: number
  choices?: unknown[]
  pattern?: string
  length?: number | number[]
  within?: string[]
  network?: boolean
  unique?: boolean
  title?: LangMap
}

export interface BlockInfo { name: string; kind: 'repeat' | 'optional'; min?: number; max?: number | null; title?: LangMap; anchor?: string }

export interface TemplateDetail {
  id: string
  version: number
  title: LangMap
  description?: LangMap
  profile: string
  profiles: string[]
  family: string
  match: { extra: string; extra_scope: string }
  vars: VarInfo[]
  blocks: BlockInfo[]
  file: string
  digest: string
  body: string
  source: string
  scope?: TemplateScope
  editable?: boolean
}

export interface Finding {
  kind: 'missing' | 'value' | 'inconsistent' | 'constraint' | 'count' | 'ambiguous' | 'extra'
  severity: 'error' | 'warning' | 'info'
  block: string | null
  instance: number | null
  node: string | null
  node_kind: string | null
  schema: string | null
  domain: string | null
  actual_node: string | null
  expected: unknown
  actual: unknown
  actual_origin: string | null
  var: string | null
  problem?: string | null
  count: number | null
  parent: string | null
  lines: number[]
  template_lines: number[]
}

export type Row = Record<string, unknown>

export interface CheckResult {
  template: { id: string; version: number; title: LangMap; profile: string; digest: string }
  device: string
  profile: string
  family: string
  compliant: boolean
  options: { extra: string; extra_scope: string }
  variables: Record<string, unknown>
  blocks: Record<string, unknown>
  row: Row
  unresolved: string[]
  findings: Finding[]
  notes: { key: string; [k: string]: unknown }[]
  warnings: { key: string; [k: string]: unknown }[]
  summary: { patterns: number; matched: number; by_kind: Record<string, number>; by_severity: Record<string, number>; instances: Record<string, number>; extra: number }
}

export interface DraftVar { name: string; type: string; values: unknown[]; reason: string; positions: { line: number; schema: string | null; node: string | null }[] }
export interface DraftResult {
  template_id: string
  profile: string
  family: string
  configs: string[]
  source: string
  vars: DraftVar[]
  params: Row[]
  optional_candidates: { node: string; schema: string; lines: number[]; missing_in: string[] }[]
  repeat_candidates: { parent: string; schema: string; nodes: string[]; count: number }[]
  notes: { key: string; line?: number; text?: string; [k: string]: unknown }[]
  verify: { device: string; compliant: boolean; errors: number; mismatched: unknown[] }[]
  valid: boolean
  issues: TemplateIssue[]
}
