/** 文档与知识库包页面的纯逻辑：表单校验、任务阶段、结果统计、导入计划。 */

export const DOMAINS = ['interface', 'vrf', 'static-route', 'bgp', 'routing-policy'] as const

export interface Extractor { name: string; family: string; title: string; patches: boolean }

export interface IngestForm {
  doc_dir: string
  rules: string
  domains: string[]
  version: string
  use_ai: boolean
}

/** POST /kb/ingest 任务的结果（lmesh.core.ingest.service.ingest 的返回值）。 */
export interface IngestResult {
  files?: number
  commands?: number
  cards?: number
  per_domain?: Record<string, number>
  patched?: number
  skipped?: Record<string, number>
  errors?: string[]
  rules?: string
  family?: string
  merge?: { new?: number; updated_draft?: number; changed_reviewed?: number; unchanged?: number }
  review_items?: number
  commit?: string | null
  ai_cards?: number
}

/** 表单问题（文案键，相对 ingest.）。 */
export function validateIngest(f: IngestForm, aiConfigured: boolean): string[] {
  const out: string[] = []
  if (!f.doc_dir.trim()) out.push('errDocDir')
  if (!f.rules) out.push('errRules')
  if (!f.domains.length) out.push('errDomains')
  if (f.use_ai && !aiConfigured) out.push('errAi')
  return out
}

export function ingestBody(f: IngestForm): IngestForm {
  return {
    doc_dir: f.doc_dir.trim(),
    rules: f.rules,
    domains: DOMAINS.filter((d) => f.domains.includes(d)),
    version: f.version.trim(),
    use_ai: f.use_ai,
  }
}

/**
 * 后端进度的阶段划分（service.ingest 中的 progress 调用）：
 * 0–4 准备文档、5–79 抽取命令卡（AI 补抽在 60–79）、80–89 合并进知识库、90–99 写入审核队列。
 */
export const STAGES = ['prepare', 'extract', 'merge', 'queue'] as const
export type StageState = 'done' | 'cur' | 'todo'

export function stageIndex(progress: number): number {
  if (progress >= 90) return 3
  if (progress >= 80) return 2
  if (progress >= 5) return 1
  return 0
}

export function stageStates(progress: number, status: string): StageState[] {
  if (status === 'done') return STAGES.map(() => 'done')
  const cur = stageIndex(progress)
  return STAGES.map((_, i) => (i < cur ? 'done' : i === cur ? 'cur' : 'todo'))
}

export interface IngestStats {
  files: number
  commands: number
  cards: number
  unchanged: number
  review: number
  added: number
  updated: number
  changed: number
  skipped: number
  errors: number
  aiCards: number
  patched: number
  perDomain: [string, number][]
  skippedBy: [string, number][]
}

const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)

export function ingestStats(r: IngestResult | null | undefined): IngestStats {
  const m = r?.merge ?? {}
  const skippedBy = Object.entries(r?.skipped ?? {}).filter(([, v]) => n(v) > 0).sort((a, b) => b[1] - a[1])
  return {
    files: n(r?.files),
    commands: n(r?.commands),
    cards: n(r?.cards),
    unchanged: n(m.unchanged),
    review: n(r?.review_items),
    added: n(m.new),
    updated: n(m.updated_draft),
    changed: n(m.changed_reviewed),
    skipped: skippedBy.reduce((s, [, v]) => s + n(v), 0),
    errors: (r?.errors ?? []).length,
    aiCards: n(r?.ai_cards),
    patched: n(r?.patched),
    perDomain: Object.entries(r?.per_domain ?? {}).sort((a, b) => b[1] - a[1]),
    skippedBy,
  }
}

/** 后端时间按 UTC 保存，SQLite 返回时不带时区：没有时区的 ISO 时间按 UTC 解析。返回毫秒，无效时 NaN。 */
export function parseIso(iso: string | null | undefined): number {
  if (!iso) return NaN
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`)
}

/** 任务耗时（秒）；没有时间戳时返回 null。 */
export function durationSec(created: string | null | undefined, updated: string | null | undefined): number | null {
  if (!created || !updated) return null
  const a = parseIso(created), b = parseIso(updated)
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return null
  return Math.round((b - a) / 1000)
}

export function fmtDuration(sec: number | null): string {
  if (sec === null) return '—'
  const m = Math.floor(sec / 60), s = sec % 60
  return m ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`
}

/** 列表里的时间：MM-DD HH:mm（本地时区）。 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(parseIso(iso))
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export const TASK_TAG: Record<string, string> = { queued: 'pending', running: 'pending', done: 'pass', failed: 'fail' }

/** POST /kb/import 的计划（kb.package.ImportPlan + review_items）。 */
export interface ImportPlan {
  kb_version: string
  added: string[]
  unchanged: string[]
  conflicts: string[]
  issues: { level: string; code: string; message: string; file: string }[]
  applied: boolean
  review_items?: number[]
}

export function isImportPlan(v: unknown): v is ImportPlan {
  return !!v && typeof v === 'object' && Array.isArray((v as ImportPlan).added) && Array.isArray((v as ImportPlan).issues)
}

/** 预览后能否正式导入：没有校验错误，且有新文件或冲突要处理。 */
export function canApply(p: ImportPlan | null): boolean {
  return !!p && !p.applied && p.issues.length === 0 && p.added.length + p.conflicts.length > 0
}

/** 包内文件按顶层目录（schema/、profiles/、commands/ …）计数。 */
export function groupByDir(files: string[]): [string, number][] {
  const m = new Map<string, number>()
  for (const f of files) {
    const i = f.indexOf('/')
    const k = i > 0 ? f.slice(0, i + 1) : f
    m.set(k, (m.get(k) ?? 0) + 1)
  }
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
}

export function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}
