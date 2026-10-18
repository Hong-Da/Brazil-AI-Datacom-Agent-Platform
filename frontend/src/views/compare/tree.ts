/** 差异图：设备 → 功能域 → 对象 → 属性的叠加树，引用关系画成右侧的弧线。纯逻辑（建树、可见性、布局）。 */
import { fmtValue, hiddenKind, segLabels, sideOf, splitPath, type PartsFn, type Row } from './logic'

export type NodeState = 'same' | 'add' | 'del' | 'mod' | 'ren' | 'na' | 'ref'
export type GSide = 'both' | 'a' | 'b'

export interface TNode {
  key: string
  /** 规范编号（根与功能域节点为空） */
  path: string
  domain: string
  label: string
  labelA: string
  labelB: string
  state: NodeState
  /** 本节点自己的状态（不含下级汇总），用于 A / B 侧隐藏 */
  own: NodeState
  /** 隐藏配置标记（REQ-028）：差异的某侧是默认值 / 派生值 */
  hid?: 'default' | 'derived' | ''
  depth: number
  rowId: string | null
  parent: TNode | null
  children: TNode[]
}

export interface RefEdge { from: string; to: string; state: 'add' | 'del' | 'ren' | 'ref' }
export interface Tree { root: TNode; byKey: Map<string, TNode>; byRow: Map<string, string>; refs: RefEdge[]; size: number }

const STATE: Record<Row['type'], NodeState> = { added: 'add', removed: 'del', modified: 'mod', renamed: 'ren', na: 'na' }

function segName(seg: string): string {
  const i = seg.indexOf('[')
  return i < 0 ? seg : seg.slice(0, i)
}

function lastLabel(node: string, parts?: PartsFn): string {
  const l = segLabels(node, parts)
  return l[l.length - 1] ?? node
}

function labels(row: Row, seg: string, base: string, parts?: PartsFn): [string, string, string] {
  const d = row.diff
  if (d?.kind === 'renamed') {
    // 有显示风格时两侧各用自己的命令写法（route-policy OLD ⇢ route-policy NEW）
    if (parts && d.a?.node && d.b?.node) {
      const a = lastLabel(d.a.node, parts)
      const b = lastLabel(d.b.node, parts)
      return [`${a} ⇢ ${b}`, a, b]
    }
    const n = segName(seg)
    const from = d.from ?? fmtValue(d.a?.value)
    const to = d.to ?? fmtValue(d.b?.value)
    return [`${n} ${from} ⇢ ${to}`, `${n} ${from}`, `${n} ${to}`]
  }
  const isAttr = row.dflt ? true : d?.node_kind === 'attr'
  if (!isAttr) return [base, base, base]
  const a = sideOf(row, 'a').text
  const b = sideOf(row, 'b').text
  if (row.type === 'modified') return [`${base} ${a} ⇢ ${b}`, `${base} ${a}`, `${base} ${b}`]
  const v = a || b
  const l = v ? `${base} ${v}` : base
  return [l, l, l]
}

export interface Extra { node: string; domain: string }

/**
 * 建树：rows 是差异行（含不可比项），extras 是“显示全部”时补进来的无变化节点（规范编号 + 功能域）。
 * 树的键：根 dev、功能域 D:<域>、其余 <域>|<规范编号>（同一对象在不同功能域下各自出现，保持纯树）。
 */
export function buildTree(rows: Row[], rootLabel: string, extras: Extra[] = [], parts?: PartsFn): Tree {
  const root: TNode = { key: 'dev', path: '', domain: '', label: rootLabel, labelA: rootLabel, labelB: rootLabel, state: 'same', own: 'same', depth: 0, rowId: null, parent: null, children: [] }
  const byKey = new Map<string, TNode>([['dev', root]])
  const byPath = new Map<string, string>()
  const byRow = new Map<string, string>()

  function domainNode(dom: string): TNode {
    const key = `D:${dom}`
    let n = byKey.get(key)
    if (!n) {
      n = { key, path: '', domain: dom, label: dom, labelA: dom, labelB: dom, state: 'same', own: 'same', depth: 1, rowId: null, parent: root, children: [] }
      root.children.push(n)
      byKey.set(key, n)
    }
    return n
  }
  function ensure(dom: string, path: string): TNode {
    let parent = domainNode(dom)
    const segs = splitPath(path)
    let labelsOf: string[] | null = null
    let n: TNode = parent
    for (let i = 0; i < segs.length; i++) {
      const p = segs.slice(0, i + 1).join('/')
      const key = `${dom}|${p}`
      let c = byKey.get(key)
      if (!c) {
        labelsOf ??= segLabels(path, parts)
        const l = labelsOf[i]
        c = { key, path: p, domain: dom, label: l, labelA: l, labelB: l, state: 'same', own: 'same', depth: i + 2, rowId: null, parent, children: [] }
        parent.children.push(c)
        byKey.set(key, c)
        if (!byPath.has(p)) byPath.set(p, key)
      }
      parent = c
      n = c
    }
    return n
  }

  for (const row of rows) {
    const n = ensure(row.domain, row.node)
    const segs = splitPath(row.node)
    ;[n.label, n.labelA, n.labelB] = labels(row, segs[segs.length - 1] ?? row.node, lastLabel(row.node, parts), parts)
    n.own = STATE[row.type]
    n.hid = hiddenKind(row)
    n.rowId = row.id
    byRow.set(row.id, n.key)
  }

  // 关联差异（引用边）：引用方不在差异里时作为“随改名 / 随变化”的节点补进来
  const refs: RefEdge[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    const d = row.diff
    if (!d?.related.length) continue
    const to = byRow.get(row.id)!
    for (const rel of d.related) {
      let from = byPath.get(rel)
      if (!from) {
        // 放在已有的最长上级所在的功能域下（例如 BGP 对等体引用了改名的策略，放在 bgp 下），没有就放在差异的功能域下
        const segs = splitPath(rel)
        let dom = row.domain
        for (let i = segs.length - 1; i > 0; i--) {
          const hit = byPath.get(segs.slice(0, i).join('/'))
          if (hit) {
            dom = byKey.get(hit)!.domain
            break
          }
        }
        const n = ensure(dom, rel)
        if (n.own === 'same') n.own = 'ref'
        from = n.key
      }
      if (from === to) continue
      const pair = [from, to].sort().join('\u0000')
      if (seen.has(pair)) continue
      seen.add(pair)
      const st = row.type === 'renamed' ? 'ren' : row.type === 'added' ? 'add' : row.type === 'removed' ? 'del' : 'ref'
      refs.push({ from, to, state: st })
    }
  }

  for (const x of extras) if (!byPath.has(x.node)) ensure(x.domain || 'raw', x.node)

  // 汇总状态：自己有差异用自己的，否则下级有差异记为修改
  function settle(n: TNode): boolean {
    let changed = false
    n.children.sort((a, b) => (n.depth === 0 ? 0 : a.path.localeCompare(b.path, undefined, { numeric: true })))
    for (const c of n.children) if (settle(c)) changed = true
    if (n.own !== 'same' && n.own !== 'ref') {
      n.state = n.own
      return true
    }
    n.state = changed ? 'mod' : n.own
    return changed
  }
  settle(root)
  return { root, byKey, byRow, refs, size: byKey.size }
}

/** 节点多时默认收起到功能域。 */
export function initialCollapsed(tree: Tree, limit = 120): Set<string> {
  if (tree.size <= limit) return new Set()
  return new Set(tree.root.children.map((c) => c.key))
}

export function countDesc(n: TNode): number {
  let s = 0
  for (const c of n.children) s += 1 + countDesc(c)
  return s
}

export interface LNode {
  key: string
  /** 规范编号（根与功能域为空） */
  path: string
  hid: 'default' | 'derived' | ''
  label: string
  state: NodeState
  depth: number
  x: number
  y: number
  w: number
  hasKids: boolean
  collapsed: boolean
  hidden: number
  rowId: string | null
}
export interface LRef { d: string; state: RefEdge['state'] }
export interface Layout { nodes: LNode[]; links: string[]; refs: LRef[]; width: number; height: number }

export interface LayoutOpts { side: GSide; collapsed: Set<string>; row?: number; charW?: number; maxW?: number; gap?: number }

function hiddenOnSide(n: TNode, side: GSide): boolean {
  return (side === 'a' && n.own === 'add') || (side === 'b' && n.own === 'del')
}

/** 列式树布局：同一深度一列，叶子逐行排列，父节点居中于子节点。 */
export function layoutTree(tree: Tree, o: LayoutOpts): Layout {
  const ROW = o.row ?? 30
  const CW = o.charW ?? 7
  const MAXW = o.maxW ?? 340
  const GAP = o.gap ?? 34
  const vis: TNode[] = []
  const visible = new Set<string>()
  function walk(n: TNode): void {
    if (hiddenOnSide(n, o.side)) return
    vis.push(n)
    visible.add(n.key)
    if (o.collapsed.has(n.key)) return
    for (const c of n.children) walk(c)
  }
  walk(tree.root)

  const labelOf = (n: TNode) => (o.side === 'a' ? n.labelA : o.side === 'b' ? n.labelB : n.label)
  const widthOf = (n: TNode) => {
    const extra = o.collapsed.has(n.key) && n.children.length ? 5 * CW : 0
    const sym = n.depth > 1 ? 14 : 0
    return Math.min(MAXW, Math.max(n.depth < 2 ? 110 : 70, labelOf(n).length * CW + 22 + sym + extra))
  }
  const colW: number[] = []
  for (const n of vis) colW[n.depth] = Math.max(colW[n.depth] ?? 0, widthOf(n))
  const colX: number[] = [12]
  for (let d = 1; d < colW.length; d++) colX[d] = colX[d - 1] + (colW[d - 1] ?? 0) + GAP

  const pos = new Map<string, LNode>()
  let rowN = 0
  function place(n: TNode): LNode {
    const kids = o.collapsed.has(n.key) ? [] : n.children.filter((c) => visible.has(c.key))
    const ys = kids.map((k) => place(k).y)
    const y = ys.length ? (ys[0] + ys[ys.length - 1]) / 2 : rowN++ * ROW + 20
    const ln: LNode = {
      key: n.key,
      path: n.path,
      hid: n.hid ?? '',
      label: labelOf(n),
      state: n.state,
      depth: n.depth,
      x: colX[n.depth],
      y,
      w: widthOf(n),
      hasKids: n.children.length > 0,
      collapsed: o.collapsed.has(n.key) && n.children.length > 0,
      hidden: o.collapsed.has(n.key) ? countDesc(n) : 0,
      rowId: n.rowId,
    }
    pos.set(n.key, ln)
    return ln
  }
  place(tree.root)

  const links: string[] = []
  for (const n of vis) {
    const p = n.parent && pos.get(n.parent.key)
    const c = pos.get(n.key)
    if (!p || !c) continue
    const x1 = p.x + p.w
    const mx = x1 + (c.x - x1) / 2
    links.push(`M${x1} ${p.y} H${mx} V${c.y} H${c.x}`)
  }

  const nearest = (key: string): LNode | undefined => {
    let n: TNode | null | undefined = tree.byKey.get(key)
    while (n && !pos.has(n.key)) n = n.parent
    return n ? pos.get(n.key) : undefined
  }
  let maxX = 0
  for (const n of pos.values()) maxX = Math.max(maxX, n.x + n.w)
  const refs: LRef[] = []
  tree.refs.forEach((e, i) => {
    const a = nearest(e.from)
    const b = nearest(e.to)
    if (!a || !b || a === b) return
    const ax = a.x + a.w
    const bx = b.x + b.w
    const cx = Math.max(ax, bx) + 30 + (i % 4) * 12
    refs.push({ d: `M${ax} ${a.y} C${cx} ${a.y} ${cx} ${b.y} ${bx + 2} ${b.y}`, state: e.state })
  })
  const nodes = [...pos.values()]
  return { nodes, links, refs, width: maxX + (refs.length ? 90 : 24), height: rowN * ROW + 24 }
}

/**
 * 把图里的原始编号换成规范编号：用差异两侧的（原始编号, 规范编号）对齐出前缀映射。
 * 段数相同的才对齐；改名对象的 A 侧旧名映射到 B 侧新名，叠加时合成一个节点。
 */
export function prefixMap(rows: Row[]): Map<string, string> {
  const m = new Map<string, string>()
  for (const r of rows) {
    const canon = splitPath(r.node)
    for (const side of ['a', 'b'] as const) {
      const raw = r.diff?.[side]?.node
      if (!raw || raw === r.node) continue
      const segs = splitPath(raw)
      if (segs.length !== canon.length) continue
      for (let i = 0; i < segs.length; i++) {
        const rp = segs.slice(0, i + 1).join('/')
        const cp = canon.slice(0, i + 1).join('/')
        if (rp !== cp && !m.has(rp)) m.set(rp, cp)
      }
    }
  }
  return m
}

export function toCanonical(id: string, map: Map<string, string>): string {
  if (!map.size) return id
  const segs = splitPath(id)
  let out: string[] = []
  for (let i = 0; i < segs.length; i++) {
    const rp = segs.slice(0, i + 1).join('/')
    const hit = map.get(rp)
    if (hit) out = splitPath(hit)
    else out.push(segs[i])
  }
  return out.join('/')
}

/** “显示全部”用的无变化节点：图中的对象与属性，按 Schema 找功能域。 */
export function extrasFromGraph(
  nodes: { id: string; kind: string; schema: string | null }[],
  schemaDomain: Map<string, string>,
  map: Map<string, string>,
  domain = '',
): Extra[] {
  const out: Extra[] = []
  for (const n of nodes) {
    if ((n.kind !== 'object' && n.kind !== 'attr') || !n.schema) continue
    const dom = schemaDomain.get(n.schema)
    if (!dom || (domain && dom !== domain)) continue
    out.push({ node: toCanonical(n.id, map), domain: dom })
  }
  return out
}
