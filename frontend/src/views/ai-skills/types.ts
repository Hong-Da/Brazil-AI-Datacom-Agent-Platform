/** REQ-033 内置 AI skill：接口数据类型（/api/v1/ai/skills…，见 docs/api.md）。 */

export type L3 = Record<string, string>
export type RunStatus = 'passed' | 'corrected' | 'rejected' | 'unverifiable' | 'error'
export type Source = 'builtin' | 'edit' | 'example' | 'evolution'

export interface AiState { configured: boolean; provider: string | null; status: string }

export interface Counts {
  calls: number
  passed: number
  corrected: number
  rejected: number
  unverifiable: number
  error: number
  up: number
  down: number
  corrections: number
}

export interface Stats extends Counts {
  pass_rate: number | null
  reject_rate: number | null
  regression_cases: number
  candidates: number
  pending_evolutions: number
  days: number
}

export interface SkillInfo {
  id: string
  title: L3
  description: L3
  task: string
  used_by: string
  model_key: string | null
  model: string | null
  enabled: boolean
  active: string
  builtin_version: number
  versions: number
  modified: boolean
  tools: string[]
  checks: string[]
  examples: number
  stats: Stats
}

export interface Example { input: string; output: string; note?: string }
export interface Definition {
  system: string
  prompt: string
  templates: Record<string, string>
  examples: Example[]
  tools: string[]
  output: { format?: string; schema?: string }
}

export interface Variable { name: string; in: string; desc: L3 }
export interface Sample { index: number; title: L3; input: Record<string, unknown>; reply: string }

export interface SkillDetail extends SkillInfo {
  definition: Definition
  builtin: Definition
  variables: Variable[]
  samples: Sample[]
  tool_choices: { id: string; title: L3 }[]
  check_titles: Record<string, L3>
  output_formats: string[]
  ai: AiState
}

export interface ListResult { ai: AiState; days: number; skills: SkillInfo[] }

export interface Issue { field: string; key: string; params?: Record<string, unknown> }

export interface VersionRow {
  version: string
  label: string
  source: Source
  saved_at: string | null
  author: string
  note: string
  based_on: string | null
  evolution?: number | null
  active: boolean
}

export interface DiffLine { op: 'same' | 'del' | 'add'; a: number | null; b: number | null; text: string }
export interface DiffField { field: string; changed: boolean; lines?: DiffLine[]; a?: unknown; b?: unknown }
export interface DiffResult { skill: string; a: string; b: string; fields: DiffField[]; changed: number }

export interface CheckItem { ok: boolean; reason?: string; text?: string; line?: number | null }
export interface CheckResult { status: RunStatus; score: number; items: CheckItem[] }
export interface SentStep { step: string; system: string; prompt: string; reply?: string }
export interface TestResult {
  mode: 'ai' | 'replay'
  skill: string
  version: string
  sent: SentStep[]
  reply: string
  check: CheckResult
  ai: { model: string; tokens_in: number; tokens_out: number; ms: number; calls: number }
  run_id: number | null
}

export interface RunRow {
  id: number
  skill: string
  version: string
  source: string
  status: RunStatus
  actor: string
  model: string
  tokens_in: number
  tokens_out: number
  ms: number
  rating: 'up' | 'down' | null
  correction: string
  feedback_by: string
  feedback_at: string | null
  created_at: string | null
  summary: Record<string, unknown> | null
}
export interface RunDetail extends RunRow { input: unknown; reply: string; detail: Record<string, unknown> | null }

export interface StatsDetail {
  skill: string
  days: number
  totals: Stats
  daily: (Counts & { date: string })[]
  runs: RunRow[]
  by_version: (Counts & { version: string; pass_rate: number | null; reject_rate: number | null })[]
}

export interface CaseRow {
  id: number
  skill: string
  kind: 'regression' | 'candidate'
  reason: string
  run_id: number | null
  input: unknown
  reply: string
  detail: Record<string, unknown> | null
  expect: string
  note: string
  created_by: string
  created_at: string | null
}
export interface CasesResult { skill: string; regression: CaseRow[]; candidates: CaseRow[] }

export interface EvoSide { status: RunStatus; score: number; items: CheckItem[]; reply: string }
export interface EvoCase { case_id: number; reason: string; old: EvoSide; new: EvoSide; delta: 'better' | 'worse' | 'same' }
export interface EvoSummary { old: number; new: number; cases: number; better: number; worse: number; same: number }
export interface Evolution {
  id: number
  skill: string
  status: 'pending' | 'approved' | 'rejected' | 'failed'
  base_version: string
  rationale: string
  created_by: string
  created_at: string | null
  decided_by: string
  decided_at: string | null
  published_version: string | null
  error: { issues?: Issue[]; reply?: string; check?: string } | null
  summary: EvoSummary | null
}
export interface EvolutionDetail extends Evolution {
  candidate: Definition | null
  scores: { summary: EvoSummary; cases: EvoCase[] } | null
  diff: DiffField[]
}

/** 业务结果里的 skill 调用（POST /ask、/generate 的 skill_runs）。 */
export interface SkillRunRef { step: string; skill: string; version: string; run_id: number | null; status: string }
