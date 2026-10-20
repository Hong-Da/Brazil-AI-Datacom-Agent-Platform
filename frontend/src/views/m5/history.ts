/**
 * 版本历史页（REQ-021）的纯逻辑：时间轴坐标、图差异分组、原文差异的并排配对与折叠、行与对象的联动、对象历史矩阵。
 * 后端接口：GET /devices/{id}/history、/history/diff、/history/object（结构见 docs/api.md）。
 */

export interface ImportRec { id: number; imported_at: string; source_kind: string; source_name: string; actor: string; duplicate: boolean }
export interface VsPrev { added: number; modified: number; removed: number; renamed: number; noneff: number; fmt: number }
export interface Snapshot {
  id: number
  seq: number
  collected_at: string
  source_name: string
  imports: ImportRec[]
  import_count: number
  kb_version: string
  kb_current: boolean
  fingerprint: string
  tag: string | null
  lines: number
  nodes: number | null
  graph_stored: boolean
  vs_previous: VsPrev | null
  latest: boolean
  graph?: 'stored' | 'rebuilt'
}
export interface Timeline {
  device: { id: number; name: string; vendor: string; sw_version: string; profile: string }
  snapshots: Snapshot[]
  count: number
  imports: number
  tagged: number
  keep: number
  kb_version: string
}
export interface SideVal { node?: string; value: unknown; origin: string; lines: number[]; raw?: string }
export interface Change { node: string; field: string; schema: string; node_kind: string; kind: string; a: SideVal | null; b: SideVal | null }
export interface Item {
  object: string
  schema: string
  domain: string
  key: string
  kind: 'added' | 'modified' | 'removed' | 'renamed'
  parent: string
  from: string | null
  to: string | null
  lines_a: number[]
  lines_b: number[]
  changes: Change[]
}
export interface NonEff { node: string; schema: string; domain: string; object: string; reason: 'default_explicit' | 'spelling'; a: SideVal; b: SideVal }
export interface TextLine { op: 'equal' | 'del' | 'add'; a: number | null; b: number | null; text: string; node: string | null; fmt?: boolean }
export interface Hunk { a_start: number; a_len: number; b_start: number; b_len: number; lines: TextLine[] }
export interface DiffResult {
  /** REQ-044：只存原文的设备（认不出厂商）只有原文差异 */
  raw_only?: boolean
  device: Timeline['device']
  a: Snapshot
  b: Snapshot
  kb: { a: string; b: string; current: string; differs: boolean; rebuilt: boolean }
  equal: boolean
  summary: { added: number; modified: number; removed: number; renamed: number; total: number; noneff: number; fmt: number; by_domain: Record<string, Record<string, number>> }
  items: Item[]
  noneff: NonEff[]
  text?: { hunks: Hunk[]; stats: { added: number; removed: number; fmt: number }; equal: boolean }
}
export interface ObjSnap { id: number; seq: number; collected_at: string; tag: string | null; present: boolean; lines: number[]; values: Record<string, SideVal>; changed: string[] }
export interface ObjectHistory { node: string; schema: string; fields: string[]; snapshots: ObjSnap[]; changes: number }

/** 对象级变化数（时间轴上点的大小与柱高）。 */
export const objChanges = (v: VsPrev | null): number => (v ? v.added + v.modified + v.removed + v.renamed : 0)

/** 时间戳显示为本地时间 YYYY-MM-DD HH:mm。 */
export function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/**
 * 时间轴横坐标：按时间比例排列，相邻两点至少相隔 minGap（导入时间很接近时不会叠在一起），再整体缩放到 [left, right]。
 * 返回与 times 同序的 x。
 */
export function timelineX(times: number[], left: number, right: number, minGap = 36): number[] {
  const n = times.length
  if (!n) return []
  if (n === 1) return [(left + right) / 2]
  const width = right - left
  const t0 = times[0]
  const span = Math.max(1, times[n - 1] - t0)
  const xs = times.map((t) => ((t - t0) / span) * width)
  const gap = Math.min(minGap, width / (n - 1))
  for (let i = 1; i < n; i++) if (xs[i] - xs[i - 1] < gap) xs[i] = xs[i - 1] + gap
  const total = xs[n - 1] || 1
  return xs.map((x) => left + (x / total) * width)
}

/** 点到 A / B 的规则（与预览一致）：单击设为 B（早于 A 时设为 A），Shift 单击设为 A。返回新的 [a, b] 下标。 */
export function pickPoint(i: number, a: number, b: number, shift: boolean): [number, number] {
  if (shift) return i < b ? [i, b] : [a, b]
  if (i < a) return [i, b]
  if (i > a) return [a, i]
  return [a, b]
}

/** 图差异按功能域分组（保持后端的顺序）。 */
export function groupItems(items: Item[]): { domain: string; items: Item[] }[] {
  const out: { domain: string; items: Item[] }[] = []
  for (const it of items) {
    const d = it.domain || 'other'
    let g = out.find((x) => x.domain === d)
    if (!g) out.push((g = { domain: d, items: [] }))
    g.items.push(it)
  }
  return out
}

/** 只是写法不同的变化按所属对象归到图差异列表（显示为“等值”项）。 */
export function noneffByObject(list: NonEff[]): { object: string; domain: string; schema: string; rows: NonEff[] }[] {
  const m = new Map<string, { object: string; domain: string; schema: string; rows: NonEff[] }>()
  for (const n of list) {
    const k = n.object || n.node
    if (!m.has(k)) m.set(k, { object: k, domain: n.domain || 'other', schema: n.schema.split('.').slice(0, -1).join('.') || n.schema, rows: [] })
    m.get(k)!.rows.push(n)
  }
  return [...m.values()]
}

/** 节点编号是否属于对象（对象本身或其子孙）。 */
export const underObject = (node: string | null | undefined, obj: string): boolean => !!node && (node === obj || node.startsWith(`${obj}/`))

/** 一行原文的节点属于哪一项（最长前缀）。 */
export function itemOfNode(node: string | null | undefined, objects: string[]): string | null {
  if (!node) return null
  let best: string | null = null
  for (const o of objects) if (underObject(node, o) && (!best || o.length > best.length)) best = o
  return best
}

export interface PairRow { kind: 'eq' | 'ch'; a: TextLine | null; b: TextLine | null; fmt: boolean }

/** 原文差异的并排行：相同行左右对齐；连续的删除 + 新增配成一行一行（多出的一侧留空）。 */
export function pairLines(lines: TextLine[]): PairRow[] {
  const rows: PairRow[] = []
  let k = 0
  while (k < lines.length) {
    const l = lines[k]
    if (l.op === 'equal') {
      rows.push({ kind: 'eq', a: l, b: l, fmt: false })
      k++
      continue
    }
    const dels: TextLine[] = []
    const adds: TextLine[] = []
    while (k < lines.length && lines[k].op !== 'equal') {
      if (lines[k].op === 'del') dels.push(lines[k])
      else adds.push(lines[k])
      k++
    }
    for (let x = 0; x < Math.max(dels.length, adds.length); x++) {
      const a = dels[x] ?? null
      const b = adds[x] ?? null
      rows.push({ kind: 'ch', a, b, fmt: !!(a?.fmt ?? true) && !!(b?.fmt ?? true) })
    }
  }
  return rows
}

export type Seg = { type: 'row'; row: PairRow; i: number } | { type: 'fold'; key: string; count: number; from: number; to: number }

/**
 * 折叠相同的行：保留变化前后 context 行，以及 keep(row) 为真的行；其余连续的相同行合成一个“展开 N 行”。
 * open 中的折叠键（起始下标）表示已展开。
 */
export function foldRows(rows: PairRow[], keep: (r: PairRow) => boolean, open: Set<string>, context = 3): Seg[] {
  const vis = rows.map((r) => r.kind === 'ch' || keep(r))
  rows.forEach((r, i) => {
    if (r.kind !== 'ch') return
    for (let d = -context; d <= context; d++) if (rows[i + d]) vis[i + d] = true
  })
  const out: Seg[] = []
  let i = 0
  while (i < rows.length) {
    if (vis[i]) { out.push({ type: 'row', row: rows[i], i }); i++; continue }
    const st = i
    while (i < rows.length && !vis[i]) i++
    const key = String(st)
    if (open.has(key) || i - st < 3) for (let q = st; q < i; q++) out.push({ type: 'row', row: rows[q], i: q })
    else out.push({ type: 'fold', key, count: i - st, from: st, to: i })
  }
  return out
}

export interface Part { s: string; mark: boolean }

/** 一对修改行中不同的词（空白分隔）标出来。 */
export function markWords(a: string, b: string): [Part[], Part[]] {
  const wa = a.split(/(\s+)/)
  const wb = b.split(/(\s+)/)
  const sa = new Set(wa)
  const sb = new Set(wb)
  const part = (w: string, other: Set<string>): Part => ({ s: w, mark: !/^\s*$/.test(w) && !other.has(w) })
  return [wa.filter((w) => w !== '').map((w) => part(w, sb)), wb.filter((w) => w !== '').map((w) => part(w, sa))]
}

/** 取值显示：列表用顿号，布尔与空值交给调用方。 */
export function showVal(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.map(showVal).join('、')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export interface MatrixCell { span: number; from: number; kind: 'abs' | 'val'; value: SideVal | null; cls: '' | 'chg' | 'new' | 'def' | 'none'; first: boolean; label: 'notYet' | 'removed' | '' }

/** 对象历史的一行（一个字段 × 各快照）：相同取值连成一段；变化处标 chg，新出现标 new，默认值 def，未配置 none，对象不存在 abs。 */
export function matrixRow(snaps: ObjSnap[], field: string): MatrixCell[] {
  const out: MatrixCell[] = []
  const key = (s: ObjSnap): string => (s.present ? JSON.stringify([s.values[field]?.value ?? null, s.values[field]?.origin ?? 'none']) : '@abs')
  let i = 0
  let prev: string | undefined
  let seenAbs = false
  while (i < snaps.length) {
    const k = key(snaps[i])
    let j = i + 1
    while (j < snaps.length && key(snaps[j]) === k) j++
    if (k === '@abs') {
      out.push({ span: j - i, from: i, kind: 'abs', value: null, cls: '', first: !seenAbs, label: i === 0 ? 'notYet' : 'removed' })
      seenAbs = true
    } else {
      const v = snaps[i].values[field] ?? null
      let cls: MatrixCell['cls'] = !v || v.value === null || v.value === undefined ? 'none' : v.origin === 'default' ? 'def' : ''
      const pv = prev !== undefined && prev !== '@abs' ? JSON.parse(prev)[0] : undefined
      if (i > 0 && prev !== undefined && prev !== '@abs' && JSON.stringify(pv) !== JSON.stringify(v?.value ?? null)) cls = cls === 'def' ? 'def' : 'chg'
      else if (i > 0 && prev === '@abs' && cls !== 'none') cls = cls === 'def' ? 'def' : 'new'
      out.push({ span: j - i, from: i, kind: 'val', value: v, cls, first: false, label: '' })
    }
    prev = k
    i = j
  }
  return out
}

export interface LogEvent { seq: number; kind: 'add' | 'del' | 'mod'; snap: ObjSnap; fields: { field: string; a: SideVal | null; b: SideVal | null }[] }

/** 对象历史的变化记录（新的在前）。 */
export function objectLog(snaps: ObjSnap[]): LogEvent[] {
  const out: LogEvent[] = []
  snaps.forEach((s, i) => {
    const p = i > 0 ? snaps[i - 1] : null
    if (s.present && (!p || !p.present)) out.push({ seq: s.seq, kind: 'add', snap: s, fields: [] })
    else if (!s.present && p?.present) out.push({ seq: s.seq, kind: 'del', snap: s, fields: [] })
    else if (s.present && p) {
      const fs = s.changed.filter((f) => f !== '@presence').map((f) => ({ field: f, a: p.values[f] ?? null, b: s.values[f] ?? null }))
      if (fs.length) out.push({ seq: s.seq, kind: 'mod', snap: s, fields: fs })
    }
  })
  return out.reverse()
}

/** 对象选择列表：取最新配置图里显式的对象节点，按 Schema 首段分组。 */
export function objectOptions(nodes: { id: string; kind: string; schema: string | null; origin?: string }[]): { group: string; items: { id: string; schema: string }[] }[] {
  const groups = new Map<string, { id: string; schema: string }[]>()
  for (const n of nodes) {
    if (n.kind !== 'object' || !n.schema || n.origin === 'default' || n.origin === 'derived') continue
    const g = n.schema.split('.')[0]
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push({ id: n.id, schema: n.schema })
  }
  return [...groups.entries()].map(([group, items]) => ({ group, items }))
}

/** CLI 等价写法（复制用）。 */
export function diffCli(device: string, a: number, b: number, opts: { noneff: boolean; rebuild: boolean }): string {
  return `lmesh history diff ${device} --from v${a} --to v${b}${opts.noneff ? ' --show-noneff' : ''}${opts.rebuild ? ' --rebuild' : ''} --output json`
}
