/** 配置检查项目（REQ-031）接口的数据类型，字段含义见 src/lmesh/core/script_check.py、checkproj.py、textdiff.py 的模块说明。 */

export type Kind = 'change' | 'full'
export type Severity = 'error' | 'warning' | 'info'
export type Category = 'parse' | 'view' | 'undo' | 'override' | 'side_effect' | 'order' | 'conflict' | 'rule' | 'ai'

export interface DeviceRef { id: number; name: string; vendor: string; platform: string; profile: string }
export interface LastCheck { errors: number; warnings: number; checked: number; at: string | null }

export interface Project {
  id: number
  name: string
  description: string
  device: DeviceRef | null
  device_id: number | null
  /** null：跟随设备最新版本 */
  version_id: number | null
  profile: string | null
  default_kind: Kind
  order_check: boolean
  ai_check: boolean
  ai_rules: string[]
  owner: { id: number; username: string } | null
  scripts: number
  last_check: LastCheck
  created_at: string
  updated_at: string
  script_list?: ScriptInfo[]
}

export interface ScriptLastCheck { errors: number; warnings: number; infos: number; order: boolean; kind: Kind; at: string }

export interface ScriptInfo {
  id: number
  project_id: number
  name: string
  kind: Kind
  lines: number
  position: number
  revisions: number
  last_check: ScriptLastCheck | null
  created_at: string
  updated_at: string
  content?: string
}

export interface AiRule {
  id: string
  title: Record<string, string>
  severity: Severity
  target: string
  domain: string
  code: boolean
  file: string
}
export interface AiRules { configured: boolean; rules: AiRule[] }

export interface Issue {
  id: string
  line: number
  lines: number[]
  severity: Severity
  category: Category
  code: string
  source: 'code' | 'ai'
  /** AI 来源：passed 通过 / unverifiable 无法校验 */
  status?: 'passed' | 'unverifiable'
  text: string
  suggestion?: string
  rule?: string
  node?: string
  message: { key: string; params: Record<string, unknown> }
}

export interface MoveReason {
  dir: 'after' | 'before'
  line: number
  new_line: number
  kind: string
  node: string
  label: string
  note: string
  text: string
}
export interface Move { line: number; new_line: number; text: string; from_index?: number; to_index?: number; reasons: MoveReason[] }
export interface Mapping { line: number; new_line: number; moved: boolean }

export interface ReorderInfo { script: string; moves: Move[]; mapping: Mapping[]; changed: boolean; warnings: unknown[] }

export interface Summary {
  errors: number
  warnings: number
  infos: number
  by_category: Partial<Record<Category, number>>
  lines: number
  commands: number
  unknown: number
  ok: boolean
}

export interface RemovedLine { how: 'undo' | 'override' | 'side_effect'; by: number; text: string; base_line: number }
export interface Finding { rule: string; severity: Severity; node: string; domain: string; text: string; script_lines?: number[]; base_lines?: number[] }

export interface SemSide { node: string; value: unknown; origin: string; lines: number[] }
export interface SemDiff { kind: 'added' | 'removed' | 'changed' | 'renamed' | string; node: string; label?: string; a: SemSide | null; b: SemSide | null }
export interface SemCompare {
  equal: boolean
  summary: { total: number; by_kind: Record<string, number>; unknown?: { a: number; b: number } }
  diffs: SemDiff[]
}

export interface ChangeResult {
  final_lines: number
  lines_added: number
  lines_removed: number
  lines_overridden: number
  side_effect_removed: number
  removed: RemovedLine[]
  findings_new: Finding[]
  findings_fixed: Finding[]
  unknown: number
}
export interface FullResult { findings_total: number; unknown: number; raw: number; profile?: string; compare?: SemCompare | null }

export interface AiRejected { rule: string | null; line: number | null; reason: string }
export interface AiInfo {
  enabled: boolean
  configured?: boolean
  status?: string
  accepted?: number
  rejected?: AiRejected[]
  error?: string
  cached?: boolean
  rules?: string[]
}

export interface Baseline { device: string; device_id: number | null; version_id: number | null; profile: string; family: string; lines: number; label: string }

export interface CheckResult {
  kind: Kind
  baseline: Baseline | null
  line_kinds: string[]
  issues: Issue[]
  order: { enabled: boolean; applicable: boolean; violations: number; reorder?: ReorderInfo }
  result: Partial<ChangeResult & FullResult>
  ai: AiInfo
  summary: Summary
  ms: number
  script: { id: number; saved: boolean; kind: Kind }
}

export interface ReorderResult extends ReorderInfo {
  before: { summary: Summary; order_violations: number }
  after: { summary: Summary; order_violations: number }
  original: string
  applied: boolean
  revision?: Revision
  before_revision?: Revision | null
}

export type RevSource = 'create' | 'manual' | 'reorder' | 'restore'
export interface Revision {
  id: number
  script_id: number
  seq: number
  source: RevSource
  note: { moves?: Move[]; before_seq?: number | null; from_seq?: number; from_id?: number } | string | null
  summary: Summary | null
  author: string
  lines: number
  created_at: string
  content?: string
}

export type DiffRowType = 'equal' | 'change' | 'add' | 'del' | 'move_from' | 'move_to'
export interface DiffRow {
  t: DiffRowType
  a: number | null
  b: number | null
  at: string | null
  bt: string | null
  sa?: number[][]
  sb?: number[][]
  /** move_from：移到 b 的第几行 */
  to?: number
  /** move_to：来自 a 的第几行 */
  from?: number
}
export interface UnorderedItem { text: string; count: number; lines: number[] }
export interface DiffResult {
  stats: { equal: number; change: number; add: number; del: number; move: number; lines_a: number; lines_b: number }
  equal: boolean
  rows: DiffRow[]
  moves: { from: number; to: number; text: string }[]
  unified: string
  unordered?: { equal: boolean; only_a: UnorderedItem[]; only_b: UnorderedItem[] }
  a: { label: string; kind: string }
  b: { label: string; kind: string }
  semantic: SemCompare | null
}

export type DiffSide =
  | { type: 'revision'; revision_id: number }
  | { type: 'script'; script_id: number; text?: string }
  | { type: 'baseline'; project_id: number }
  | { type: 'text'; text: string; kind: Kind; project_id: number }
