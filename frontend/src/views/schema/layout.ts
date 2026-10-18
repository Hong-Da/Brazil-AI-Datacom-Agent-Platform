/** Schema 视图的 SVG 布局：功能域分栏、节点胶囊的位置、依赖边的路径。纯计算，便于测试。 */
import type { TreeGroup, TreeItem } from './model'

export const CW = 228 // 栏宽
export const GAP = 54 // 栏间距
export const X0 = 16
export const Y0 = 14
export const ROW = 24 // 行高
export const PH = 20 // 胶囊高
export const HEAD = 38 // 功能域标题高
export const GROUP_GAP = 14

/** 预设的分栏：接口在左，VRF / 静态路由 / 路由策略在中，BGP 在右（与预览一致）；其他功能域放到当前最短的一栏。 */
const PRESET: Record<string, number> = { interface: 0, 'service-access-point': 0, vrf: 1, 'static-route': 1, 'routing-policy': 1, bgp: 2 }
export const NCOLS = 3

export function assignColumns(groups: { domain: string; size: number }[]): string[][] {
  const cols: string[][] = Array.from({ length: NCOLS }, () => [])
  const load = Array<number>(NCOLS).fill(0)
  const rest: { domain: string; size: number }[] = []
  for (const g of groups) {
    const c = PRESET[g.domain]
    if (c === undefined) { rest.push(g); continue }
    cols[c]!.push(g.domain)
    load[c]! += g.size + 2
  }
  for (const g of rest) {
    let best = 0
    for (let i = 1; i < NCOLS; i++) if (load[i]! < load[best]!) best = i
    cols[best]!.push(g.domain)
    load[best]! += g.size + 2
  }
  return cols.filter((c) => c.length > 0)
}

export interface PillPos { x: number; y: number; w: number; h: number; item: TreeItem; col: number }
export interface GroupBox { domain: string; x: number; y: number; w: number; h: number; count: number }
export interface Layout { pills: PillPos[]; groups: GroupBox[]; pos: Map<string, PillPos>; width: number; height: number }

export function layoutGroups(groups: TreeGroup[]): Layout {
  const byDomain = new Map(groups.map((g) => [g.domain, g]))
  const cols = assignColumns(groups.map((g) => ({ domain: g.domain, size: g.items.length })))
  const pills: PillPos[] = []
  const boxes: GroupBox[] = []
  const pos = new Map<string, PillPos>()
  let maxY = 0
  cols.forEach((col, ci) => {
    const x = X0 + ci * (CW + GAP)
    let y = Y0
    for (const d of col) {
      const g = byDomain.get(d)!
      const h = HEAD + g.items.length * ROW + 8
      boxes.push({ domain: d, x, y, w: CW, h, count: g.items.length })
      let yy = y + HEAD
      for (const it of g.items) {
        const dp = Math.min(it.depth, 6)
        const p: PillPos = { x: x + 10 + dp * 14, y: yy, w: CW - 20 - dp * 14, h: PH, item: it, col: ci }
        pills.push(p)
        pos.set(it.node.id, p)
        yy += ROW
      }
      y += h + GROUP_GAP
    }
    maxY = Math.max(maxY, y)
  })
  return { pills, groups: boxes, pos, width: X0 + cols.length * (CW + GAP), height: maxY + 10 }
}

/** 胶囊内能放下的字符数（等宽字体约 6.7px / 字），超出时截断加省略号。 */
export function fitText(text: string, width: number, reserve: number): string {
  const room = Math.max(4, Math.floor((width - reserve) / 6.7))
  return text.length > room ? text.slice(0, room - 1) + '…' : text
}

/** 两个胶囊之间的依赖边：同栏从右侧绕出，跨栏用水平贝塞尔曲线；i 用于错开重叠的边。 */
export function edgePath(a: PillPos, b: PillPos, i: number): string {
  const sy = a.y + PH / 2, ty = b.y + PH / 2
  if (a.col === b.col) {
    const sx = a.x + a.w, tx = b.x + b.w
    const bx = Math.max(sx, tx) + 16 + Math.min(40, Math.abs(ty - sy) * 0.08) + (i % 3) * 4
    return `M${sx} ${sy}C${bx} ${sy} ${bx} ${ty} ${tx} ${ty}`
  }
  const [sx, tx] = a.x < b.x ? [a.x + a.w, b.x] : [a.x, b.x + b.w]
  const m = (sx + tx) / 2 + (i % 4) * 5 - 8
  return `M${sx} ${sy}C${m} ${sy} ${m} ${ty} ${tx} ${ty}`
}
