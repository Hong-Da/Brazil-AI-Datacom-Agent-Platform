/** /kb/profiles、/kb/profiles/{id}、/kb/profile-compare、/kb/coverage 的返回结构（只列页面用到的字段）。 */

export type Cred = 'draft' | 'reviewed' | 'verified'
export type EntryState = 'supported' | 'unsupported' | 'unfilled'
export type Scalar = string | number | boolean | null

export interface ProfileRow {
  id: string
  title: string
  vendor: string
  family: string
  platform: string
  software: string
  inherits: string | null
  match: Record<string, string>
  own_entries: number
  entries: number
  coverage: number
  unfilled: number
  credibility: Record<Cred, number>
  devices: number
  file: string
}

export interface ProfileList { profiles: ProfileRow[]; families: string[] }

export interface Entry {
  node: string
  domain: string
  type: string
  semantic: Record<string, string>
  deprecated: boolean
  /** Schema 定义的可选值（enum）与取值范围（integer）；默认值输入按类型变化（M6-9） */
  choices?: string[]
  range?: number[]
  state: EntryState
  default?: Scalar
  show_rule?: string
  cards?: string[]
  source?: string
  verified?: string
  manual?: boolean
  origin?: string
  inherited?: boolean
  credibility?: Cred
}

export interface ProfileDetail {
  profile: {
    id: string
    title: string
    vendor: string
    family: string
    platform: string
    software: string
    inherits: string | null
    match: Record<string, string>
    lineage: string[]
  }
  show_rules: string[]
  entries: Entry[]
}

export type CompareKind = 'same' | 'only_a' | 'only_b' | 'default' | 'unfilled'

export interface CompareRow {
  node: string
  domain: string
  semantic: Record<string, string>
  a: { state: EntryState; default: Scalar }
  b: { state: EntryState; default: Scalar }
  kind: CompareKind
}

export interface CompareResult {
  a: string
  b: string
  counts: Record<CompareKind, number>
  rows: CompareRow[]
}

export interface CoverageResult {
  profiles: string[]
  totals: Record<string, Record<EntryState, number>>
  matrix: Record<string, Record<string, EntryState>>
}
