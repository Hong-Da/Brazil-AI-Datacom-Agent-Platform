/** 配置对比接口（POST /compare）的结果类型，字段说明见 docs/project-spec.md“配置对比（M2-3 结果）”。 */

export type DiffKind = 'added' | 'removed' | 'changed' | 'renamed'
export type Origin = 'explicit' | 'default' | 'derived' | string

export interface SideVal {
  /** 该侧图里的原始节点编号 */
  node: string
  value: unknown
  origin: Origin
  lines: number[]
  cid?: string
}

export interface Diff {
  kind: DiffKind
  node_kind: 'object' | 'attr' | 'ext' | 'raw' | string
  /** 规范编号 */
  node: string
  schema: string | null
  domain: string
  a: SideVal | null
  b: SideVal | null
  from: string | null
  to: string | null
  similarity: number | null
  count: number | null
  related: string[]
}

export interface DefaultOnly {
  node: string
  schema: string | null
  domain: string
  side: 'a' | 'b'
  value: unknown
}

export interface UnknownLine { line: number; text: string; owner: string }

export interface SideInfo {
  label: string
  device: string | null
  profile: string | null
  family: string | null
  kb_version: string | null
  device_id: number | null
  version_id: number | null
  nodes: number
}

export interface CompareResult {
  a: SideInfo
  b: SideInfo
  options: Record<string, unknown> & { hidden_identity?: number }
  equal: boolean
  diffs: Diff[]
  renames: { schema: string; from: string; to: string; similarity: number }[]
  unknown: { a: UnknownLine[]; b: UnknownLine[] }
  default_only: DefaultOnly[]
  summary: {
    total: number
    by_kind: Record<DiffKind, number>
    by_domain: Record<string, Record<string, number>>
    unknown: { a: number; b: number }
    default_only: number
    hidden_identity?: number
  }
}

export interface VersionInfo {
  id: number
  seq: number
  source_name: string
  collected_at: string | null
  kb_version: string
  lines: number
  latest: boolean
}

export interface GraphNode { id: string; kind: string; schema: string | null; key?: unknown; value?: unknown; origin?: string; lines?: number[] }
export interface DeviceGraph { device: string; profile: string; nodes: GraphNode[]; version_id: number; text: string | null }
