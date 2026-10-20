import type { Note } from '@/i18n/note'

/** GET /devices/{id}/graph 返回的数据（见 src/lmesh/core/graph.py 的 to_json）。 */
export interface ApiNode {
  id: string
  kind: string // device / object / attr / raw / unknown / ext
  schema: string | null
  origin: string // explicit / default / derived / inherited
  lines: number[]
  cards: string[]
  value?: unknown
  raw?: unknown
  key?: unknown
  text?: string
  negated?: boolean
}

export interface ApiEdge {
  from: string
  to: string
  kind: string // contains / reference / prerequisite / side_effect / mutex
  note: Note // 三语说明 {zh-CN, en, pt-BR}，用 noteText 取值
}

export interface GraphSummary {
  nodes: number
  edges: number
  kinds: Record<string, number>
  attr_origins: Record<string, number>
  edge_kinds: Record<string, number>
  dangling: number
}

export interface GraphData {
  device: string | null
  profile: string | null
  kb_version: string | null
  version_id?: number
  nodes: ApiNode[]
  edges: ApiEdge[]
  dangling: unknown[]
  summary: GraphSummary
  text?: string | null
  /** REQ-044：Profile 来源与近似标记（近似时页头提示条） */
  profile_info?: { profile: string; profile_source: string; profile_rule_id: number | null; approx: boolean; unknown_ratio: number | null }
}

/** GET /devices 的一行。 */
export interface DeviceRow {
  id: number
  name: string
  vendor: string
  sw_version: string
  profile: string
  source_name: string
  lines: number
  parsed: boolean
  unknown: number
  coverage: number
  roundtrip: boolean | null
  kb_version: string
  stale: boolean
}

/** POST /roundtrip（传 text）的结果。 */
export interface RoundtripResult {
  ok: boolean
  profile: string
  lines: number
  unknown: number
  coverage: number
  diffs: { line: number; original: string[]; rendered: string[] }[]
}

/** GET /kb/schema 中用到的部分。 */
export interface SchemaNodeInfo {
  id: string
  type: string
  semantic: Record<string, string> | null
  status?: string
}
export interface SchemaTree {
  kb_version: string
  domains: { domain: string; nodes: SchemaNodeInfo[] }[]
}
