/** 配置检查与冗余清理接口的数据形状（见 docs/project-spec.md“配置检查与冗余清理（M2-4 结果）”）。 */

export type Severity = 'error' | 'warning' | 'info'
export const SEVERITIES: Severity[] = ['error', 'warning', 'info']

export type LangMap = Record<string, string>

export interface TextRef { key: string; params: Record<string, unknown> }

export interface Finding {
  rule: string
  severity: Severity
  domain: string
  node: string
  schema?: string | null
  nodes: string[]
  lines: number[]
  message: TextRef
  suggestion: TextRef
  /** M2-5：被忽略的发现 */
  ignored?: boolean
  ignore_reason?: string
  ignore_id?: number | string
}

export interface CheckSummary {
  total: number
  unfiltered: number
  has_errors: boolean
  by_severity: Record<Severity, number>
  by_rule: Record<string, number>
  by_domain: Record<string, number>
  ignored?: number
}

export interface CheckResult {
  device: string | null
  profile: string | null
  kb_version: string | null
  rules_loaded: number
  summary: CheckSummary
  findings: Finding[]
  texts: Record<string, LangMap>
}

export interface Rule {
  id: string
  builtin: boolean
  target: string | null
  domain: string | null
  severity: Severity
  enabled: boolean
  title: LangMap
  message: LangMap
  suggestion: LangMap
  file?: string
  source?: string
}

export interface CleanupObject {
  node: string
  schema: string | null
  key: string
  reason: 'orphan' | 'cascade'
  via: string[]
  lines: number[]
}

export interface CleanupCommand {
  seq: number
  text: string
  context: string[]
  object: string
  lines: number[]
  card: string | null
  fallback: boolean
}

export interface CleanupVerify {
  ok: boolean
  dangling_before: number
  dangling_after: number
  new_dangling: { referrer: string; target_type: string; value: string }[]
  remaining_objects: string[]
  new_orphans: string[]
}

export interface CleanupResult {
  device: string | null
  profile: string | null
  family: string
  objects: CleanupObject[]
  commands: CleanupCommand[]
  skipped: { node: string; reason: string; lines: number[] }[]
  fallbacks: number
  script: string
  verify?: CleanupVerify
}

export interface GraphNodeLite { id: string; kind: string; schema?: string | null }
