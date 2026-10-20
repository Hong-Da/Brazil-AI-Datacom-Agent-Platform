/**
 * 未支持型号的处理（REQ-044，预览 DevelopDocs/ui-preview/REQ-044/）的数据结构与纯逻辑：
 * 匹配程度与 Profile 来源、试解析候选、导入前识别后的每文件选择（改选 / 记住 / 只存原文 / 跳过）→ 导入接口的 choices。
 */

export type MatchLevel = 'exact' | 'approx' | 'none'
export type ProfileSource = 'auto' | 'fallback' | 'rule' | 'manual' | 'none'
export type RuleScope = 'project' | 'global'

export const APPROX_SOURCES: readonly ProfileSource[] = ['fallback', 'rule', 'manual']

export function levelOf(source: string | null | undefined): MatchLevel {
  if (source === 'auto') return 'exact'
  if (!source || source === 'none') return 'none'
  return 'approx'
}

export const isApprox = (source: string | null | undefined): boolean => (APPROX_SOURCES as readonly string[]).includes(source ?? '')

/** 比例 → “3.6%”；没有时为“—”。 */
export function pct(x: number | null | undefined, digits = 1): string {
  return x === null || x === undefined || Number.isNaN(x) ? '—' : `${(x * 100).toFixed(digits)}%`
}

/** 未识别比例达到 5% 时醒目显示。 */
export const unknownHigh = (x: number | null | undefined): boolean => (x ?? 0) >= 0.05

export interface Candidate {
  profile: string
  title: string
  vendor: string
  family: string
  ratio: number
  recognized: number
  command: number
  unknown: number
  unsupported: number
  exact: boolean
  fallback: boolean
}

export interface RuleConds { name_pattern: string; version: string; feature: string }

export interface ModelRule extends RuleConds {
  id: number
  scope: RuleScope
  project_id: number | null
  vendor: string
  profile: string
  note: string
  enabled: boolean
  conditions: number
  created_by: string
  created_at: string | null
  updated_at: string | null
  devices?: number
}

/** POST /configs/inspect 的一个文件。 */
export interface InspectFile {
  source: string
  ok: boolean
  error: string
  device?: string
  vendor?: string
  version?: string
  family?: string | null
  lines?: number
  profile?: string
  profile_source?: ProfileSource
  match_level?: MatchLevel
  rule?: ModelRule | null
  previous?: { profile: string; source: ProfileSource } | null
  candidates?: Candidate[]
  recommended?: string | null
  suggested_rule?: RuleConds
}

/** 认不出厂商的文件怎么处理：只存原文 / 手工选 Profile / 跳过。 */
export type UnknownAction = 'raw' | 'pick' | 'skip'

/** 每个文件在对话框里的选择。 */
export interface FileChoice {
  profile: string // 选中的 Profile（空 = 不指定，按自动顺序）
  remember: boolean
  scope: RuleScope
  rule: RuleConds
  unknown: UnknownAction
}

export function initialChoice(f: InspectFile): FileChoice {
  return {
    profile: f.profile ?? '',
    remember: false,
    scope: 'project',
    rule: { ...(f.suggested_rule ?? { name_pattern: f.device ?? '', version: '', feature: '' }) },
    unknown: 'raw',
  }
}

/** 是否改选了（与按自动顺序得到的 Profile 不同）。 */
export const changed = (f: InspectFile, c: FileChoice): boolean => !!c.profile && c.profile !== (f.profile ?? '')

/** 下拉里的候选：试解析的结果（认得厂商时为同厂商 / 同平台族，认不出时为全部 Profile），按识别比例排序。 */
export function options(f: InspectFile): { profile: string; ratio: number | null; recommended: boolean }[] {
  return (f.candidates ?? []).map((c) => ({ profile: c.profile, ratio: c.ratio, recommended: !!f.vendor && c.profile === f.recommended }))
}

/** 设备名模式（* ? 通配，不分大小写）是否匹配。 */
export function globMatch(pattern: string, name: string): boolean {
  if (!pattern) return true
  const re = new RegExp('^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$', 'i')
  return re.test(name)
}

function safeSearch(re: string, text: string): boolean {
  if (!re) return true
  try { return new RegExp(re).test(text) } catch { return false }
}

/** 规则条件（设备名、版本）在本批文件上的命中（特征命令要看原文，界面上不预判）。 */
export function batchHits(files: InspectFile[], r: RuleConds, vendor: string): string[] {
  return files.filter((f) => f.ok && (f.vendor ?? '') === vendor && globMatch(r.name_pattern, f.device ?? '') && (!r.version || safeSearch(r.version, f.version ?? ''))).map((f) => f.source)
}

export const hasCondition = (r: RuleConds): boolean => !!(r.name_pattern.trim() || r.version.trim() || r.feature.trim())

/** 正则写法是否有效（空也算有效）。 */
export function regexOk(s: string): boolean {
  if (!s) return true
  try { new RegExp(s); return true } catch { return false }
}

export interface ChoiceOut { profile?: string; raw_only?: boolean; remember?: { scope: RuleScope } & RuleConds }

/**
 * 导入接口的 choices（按文件名）与要跳过的文件：只写与自动结果不同的选择；记住时带规则；
 * 认不出厂商：raw → raw_only，pick → profile，skip → 不上传。
 */
export function buildChoices(files: InspectFile[], choices: Record<string, FileChoice>): { choices: Record<string, ChoiceOut>; skip: string[] } {
  const out: Record<string, ChoiceOut> = {}
  const skip: string[] = []
  for (const f of files) {
    if (!f.ok) continue
    const c = choices[f.source]
    if (!c) continue
    const name = f.source.split('/').pop() ?? f.source
    if (!f.vendor) {
      if (c.unknown === 'skip') { skip.push(f.source); continue }
      if (c.unknown === 'raw' || !c.profile) { out[name] = { raw_only: true }; continue }
    }
    const pick = changed(f, c) || (!f.vendor && !!c.profile) || (c.remember && !!c.profile)
    if (!pick) continue
    const o: ChoiceOut = { profile: c.profile }
    if (c.remember && hasCondition(c.rule)) o.remember = { scope: c.scope, ...c.rule }
    out[name] = o
  }
  return { choices: out, skip }
}

/** 三档计数（页面上方的小结）。 */
export function levelCounts(files: InspectFile[]): Record<MatchLevel, number> {
  const n: Record<MatchLevel, number> = { exact: 0, approx: 0, none: 0 }
  for (const f of files) if (f.ok && f.match_level) n[f.match_level]++
  return n
}

/** 设备行（GET /devices）里 REQ-044 的字段。 */
export interface ProfileInfo {
  profile: string
  profile_source: ProfileSource
  profile_rule_id: number | null
  match_level: MatchLevel
  approx: boolean
  unsupported: boolean
  unknown_ratio: number | null
}

/** 规则条件的简短文字（列表、提示里用）。 */
export function condText(r: Partial<RuleConds>): string {
  return [r.name_pattern, r.version, r.feature].filter(Boolean).join(' · ')
}
