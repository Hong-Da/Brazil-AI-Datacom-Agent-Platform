/** 画布节点的文字与尺寸、cytoscape 样式（颜色从设计系统的 CSS 变量读取，跟随明 / 暗主题）。 */
import type { StylesheetJson } from 'cytoscape'
import { formatValue, type Model, type VisNode } from './model'

export function truncate(s: string, max: number): string {
  const t = s.replace(/\s+/g, ' ').trim()
  return t.length > max ? `${t.slice(0, Math.max(1, max - 1))}…` : t
}

/** 节点在画布上的文字。moreText 是“还有 N 个”的当前语言文字。 */
export function canvasLabel(m: Model, v: VisNode, moreText: (n: number) => string): string {
  if (v.more) return moreText(v.more.count)
  const n = m.nodes.get(v.id)!
  let s: string
  switch (n.kind) {
    case 'attr':
      s = `${truncate(n.label, 22)}  ${truncate(n.value, 26)}`
      break
    case 'ext': {
      // 扩展命令只显示参数值，例如 interface  Loopback0
      const v = n.api?.value
      const short = v && typeof v === 'object' && !Array.isArray(v) ? Object.values(v).map(formatValue).join(' ') : n.value
      s = `${truncate(n.label, 22)}  ${truncate(short, 26)}`
      break
    }
    case 'raw':
      s = truncate(n.value || n.label, 34)
      break
    case 'unknown':
      s = `? ${truncate(n.value || n.label, 32)}`
      break
    case 'domain':
      s = `${n.label}  ${n.size}`
      break
    default:
      s = truncate(n.label, 36)
  }
  if (!v.expanded && v.expandable && n.kind !== 'domain') s += `  +${v.hidden}`
  if (!v.expanded && v.expandable && n.kind === 'domain') s = `${n.label}  +${n.size}`
  return s
}

let ctx: CanvasRenderingContext2D | null | undefined
/** 文字宽度（画布测量；测不了时按字符数估算）。 */
export function textWidth(s: string, font: string): number {
  if (ctx === undefined) {
    try { ctx = document.createElement('canvas').getContext('2d') } catch { ctx = null }
  }
  if (ctx) {
    ctx.font = font
    const w = ctx.measureText(s).width
    if (w > 0) return w
  }
  return s.length * 7
}

export interface Palette { [k: string]: string }

const VARS = [
  'ink', 'ink-2', 'ink-3', 'surface', 'surface-2', 'surface-3', 'canvas', 'line', 'line-strong',
  'blue', 'blue-soft', 'blue-line', 'teal', 'teal-soft', 'teal-line', 'teal-ink', 'amber', 'red', 'red-soft', 'red-ink',
  'violet', 'e-ref', 'e-pre', 'e-side', 'e-mutex', 'e-cross', 'font-ui', 'font-mono',
]

export function readPalette(el: Element = document.documentElement): Palette {
  const cs = getComputedStyle(el)
  const p: Palette = {}
  for (const v of VARS) p[v] = cs.getPropertyValue(`--${v}`).trim()
  p.dark = document.documentElement.getAttribute('data-theme') === 'dark' ? '1' : ''
  return p
}

export function graphStyle(p: Palette): StylesheetJson {
  const mono = p['font-mono'] || 'monospace'
  const ui = p['font-ui'] || 'sans-serif'
  return [
    {
      selector: 'node',
      style: {
        shape: 'round-rectangle', width: 'data(w)', height: 24, label: 'data(label)',
        'font-family': mono, 'font-size': 11.5, color: p.ink, 'text-valign': 'center', 'text-halign': 'center',
        'background-color': p.surface, 'border-width': 1.2, 'border-color': p['line-strong'],
        'overlay-padding': 3, 'overlay-opacity': 0,
      },
    },
    { selector: 'node:active', style: { 'overlay-opacity': 0.08, 'overlay-color': p.blue } },
    { selector: 'node.k-device', style: { 'background-color': p.blue, 'border-color': p.blue, color: p.dark ? '#06182A' : '#FFFFFF', 'font-family': ui, 'font-weight': 600, 'font-size': 12.5, height: 28 } },
    { selector: 'node.k-domain', style: { 'background-color': p['teal-soft'], 'border-color': p['teal-line'], color: p['teal-ink'], 'font-family': ui, 'font-weight': 600, 'font-size': 12, height: 26 } },
    { selector: 'node.k-object', style: { 'font-weight': 600 } },
    { selector: 'node.k-raw, node.k-rawgroup', style: { 'background-color': p['surface-3'], 'border-style': 'dashed', color: p['ink-2'] } },
    { selector: 'node.k-ext', style: { 'background-color': p['surface-2'], 'border-color': p['blue-line'], color: p['ink-2'] } },
    { selector: 'node.k-unknown', style: { 'background-color': p['red-soft'], 'border-color': p.red, color: p['red-ink'] } },
    { selector: 'node.k-more', style: { 'background-opacity': 0, 'border-style': 'dashed', 'border-color': p['line-strong'], color: p['ink-3'], 'font-family': ui, 'font-size': 11 } },
    { selector: 'node.s-default', style: { 'background-color': p.canvas, 'border-style': 'dashed', 'border-color': p['ink-3'], color: p['ink-2'] } },
    { selector: 'node.s-derived', style: { 'background-color': p.canvas, 'border-style': 'dotted', 'border-color': p.violet } },
    { selector: 'node.s-inherited', style: { 'background-color': p.canvas, 'border-style': 'dashed', 'border-color': p.teal } },
    { selector: 'node.has-unk', style: { 'underlay-color': p.red, 'underlay-opacity': 0.22, 'underlay-padding': 3, 'underlay-shape': 'round-rectangle' } },
    { selector: 'node.is-match', style: { 'border-color': p.amber, 'border-width': 2 } },
    { selector: 'node.is-rel', style: { 'border-color': p.blue, 'border-width': 1.8 } },
    { selector: 'node.is-sel', style: { 'border-color': p.amber, 'border-width': 2.6, 'border-style': 'solid' } },
    { selector: 'node.is-dim', style: { opacity: 0.3 } },
    {
      selector: 'edge',
      style: { width: 1.6, 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8, 'control-point-step-size': 36, 'font-family': ui, 'font-size': 10, 'font-weight': 600 },
    },
    { selector: 'edge[count > 1]', style: { label: 'data(countLabel)', 'text-background-color': p.surface, 'text-background-opacity': 1, 'text-background-padding': '2px', color: p['ink-2'] } },
    { selector: 'edge.contains', style: { 'curve-style': 'taxi', 'taxi-direction': 'rightward', 'taxi-turn': 16, 'target-arrow-shape': 'none', 'line-color': p['line-strong'], width: 1.1 } },
    { selector: 'edge.ref', style: { 'line-color': p['e-ref'], 'target-arrow-color': p['e-ref'] } },
    { selector: 'edge.pre', style: { 'line-color': p['e-pre'], 'target-arrow-color': p['e-pre'] } },
    { selector: 'edge.side', style: { 'line-color': p['e-side'], 'target-arrow-color': p['e-side'], 'line-style': 'dashed', 'line-dash-pattern': [2, 3] } },
    { selector: 'edge.mutex', style: { 'line-color': p['e-mutex'], 'target-arrow-color': p['e-mutex'], 'source-arrow-color': p['e-mutex'], 'target-arrow-shape': 'tee', 'source-arrow-shape': 'tee' } },
    { selector: 'edge.is-hot', style: { width: 2.8, 'z-index': 10 } },
    { selector: 'edge.is-dim', style: { opacity: 0.16 } },
    { selector: 'edge.off', style: { display: 'none' } },
  ]
}
