import type { GraphData } from '@/views/device-graph/types'

/** GET /devices/{id}/analysis 的返回（见 src/lmesh/api/routes_analysis.py、core/config_analysis.py、core/layers.py）。 */

export type Lang3 = Record<string, string>

export interface LayerInfo {
  id: string
  order: number
  name: Lang3
  desc: Lang3
}
export interface FeatureInfo {
  id: string
  name: Lang3
  desc: Lang3
  span: string[]
}

export interface Span {
  s: number
  e: number
  t: 'kw' | 'param' | 'ref'
  p?: string
  ref?: string[]
}
export interface ScriptLine {
  no: number
  kind: string // command / raw / unknown / comment / separator / blank / end
  text: string
  depth: number
  parent: number | null
  node?: string
  layer?: string | null
  domain?: string
  card?: string
  negated?: boolean
  spans?: Span[]
}
export interface DefaultLine {
  node: string
  owner: string | null
  schema: string
  value: unknown
  after: number | null
  depth: number
  text: string | null
}
export interface ScriptData {
  device: string | null
  profile: string | null
  family: string | null
  lines: ScriptLine[]
  refs: Record<string, number[]>
  defs: Record<string, number | null>
  defaults: DefaultLine[]
}

export interface LayerRow {
  id: string
  order: number
  name: Lang3 | null
  desc: Lang3 | null
  objects: number
  attrs: number
  defaults: number
  other: number
}
export interface CrossEdge {
  from: string
  to: string
  kind: string
  from_layer: string
  to_layer: string
  via: string
  count: number
}
export interface LayersData {
  layers: LayerRow[]
  features: (FeatureInfo & { objects: number })[]
  nodes: Record<string, string>
  features_of: Record<string, string>
  cross: CrossEdge[]
  cross_by_layers: { a: string; b: string; count: number }[]
  outside: number
  unclassified: string[]
}

export interface MsgRef {
  key: string
  params: Record<string, unknown>
}
export interface Finding {
  rule: string
  severity: 'error' | 'warning' | 'info'
  node: string
  domain?: string
  lines: number[]
  message: MsgRef
  suggestion: MsgRef
}
export interface SummaryData {
  device: string | null
  profile: string | null
  family: string | null
  kb_version: string | null
  lines: { total: number; command: number; raw: number; unknown: number; comment: number; separator: number; blank: number; end: number; coverage: number }
  domains: { domain: string; objects: number; attrs: number; defaults: number; lines: number }[]
  layers: { id: string; objects: number; attrs: number }[]
  cross_layer: number
  dangling: number
  defaults: {
    total: number
    key: number
    truncated: boolean
    items: { node: string; owner: string | null; schema: string; domain: string; value: unknown; others: { profile: string; value: unknown }[] }[]
  }
  unknown_lines: number[]
  check: {
    summary: { total: number; ignored: number; has_errors: boolean; by_severity: Record<string, number>; by_rule: Record<string, number> }
    rules_loaded: number
    top: Finding[]
    texts: Record<string, Lang3>
  } | null
  baseline: {
    baseline: string
    score: number | null
    summary: { pass: number; fail: number; na: number }
    failures: Finding[]
    failure_count: number
    texts: Record<string, Lang3>
  } | null
  history: {
    current: { id: number; seq: number; collected_at: string; source_name: string }
    previous: { id: number; seq: number; collected_at: string; source_name: string } | null
    snapshots: number
    equal?: boolean
    summary: { added: number; modified: number; removed: number; renamed: number; total: number } | null
    items: { object: string; kind: string; domain: string }[]
  } | null
}

export interface AnalysisData {
  device: string | null
  device_id: number | null
  version_id: number | null
  profile: string | null
  family: string | null
  kb_version: string | null
  parts: string[]
  layer_info: { layers: LayerInfo[]; features: FeatureInfo[] }
  summary?: SummaryData
  layers?: LayersData
  script?: ScriptData
  graph?: GraphData
}

export type ViewName = 'script' | 'tree' | 'tcpip' | 'relation' | 'summary'
export const VIEWS: ViewName[] = ['script', 'tree', 'tcpip', 'relation', 'summary']
/** TCP/IP 视图自上而下的层顺序 */
export const BAND_ORDER = ['application', 'transport', 'network', 'mpls', 'datalink', 'physical']

