<script setup lang="ts">
/**
 * 影响范围的关系图（cytoscape）：起点琥珀实心，1 跳深色环，2 跳及以上浅色环，业务对象虚线环；
 * 边从 via 指向节点，按依赖类型着色（引用 / 前置 / 包含 / 别名）。布局：关系图谱（cose）或按距离分层（列 = 距离）。
 * 单击节点设为起点，按住 Shift 单击加入起点；focus 给出的路径加粗。颜色取自 CSS 变量，跟随明 / 暗主题。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape'
import { truncate } from '@/views/device-graph/style'
import { edgeClass, type ImpactNode } from './impact'

const props = defineProps<{
  nodes: ImpactNode[]
  label: (id: string) => string
  /** 路径上的节点（从起点到选中对象），加粗显示 */
  path: string[]
  layout: 'force' | 'layer'
}>()
const emit = defineEmits<{ (e: 'tap', id: string, shift: boolean): void }>()

const box = ref<HTMLDivElement>()
const tip = ref<{ x: number; y: number; text: string } | null>(null)
let cy: Core | null = null
let observer: MutationObserver | null = null
let resizer: ResizeObserver | null = null

function v(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()
}

function style(): StylesheetJson {
  const mono = v('font-mono') || 'monospace'
  return [
    {
      selector: 'node',
      style: {
        width: 18, height: 18, 'background-color': v('surface'), 'border-width': 1.6, 'border-color': v('line-strong'),
        label: 'data(short)', 'font-family': mono, 'font-size': 10, color: v('ink'), 'text-valign': 'center', 'text-halign': 'right',
        'text-margin-x': 5, 'text-background-color': v('canvas'), 'text-background-opacity': 0.75, 'text-background-padding': '1px',
        'overlay-opacity': 0,
      },
    },
    { selector: 'node.k-attr', style: { width: 10, height: 10, color: v('ink-2'), 'font-size': 9 } },
    { selector: 'node.h0', style: { width: 24, height: 24, 'background-color': v('amber'), 'border-color': v('amber-ink'), 'font-weight': 600 } },
    { selector: 'node.h1', style: { 'background-color': v('amber-soft'), 'border-color': v('ring1'), 'border-width': 2.4 } },
    { selector: 'node.h2', style: { 'border-color': v('ring2'), 'border-width': 2.4 } },
    { selector: 'node.biz', style: { 'border-style': 'dashed', shape: 'round-rectangle', width: 22, height: 16 } },
    { selector: 'node.on-path', style: { 'border-color': v('ink'), 'border-width': 2.6, 'z-index': 20, color: v('ink') } },
    { selector: 'node.dim', style: { opacity: 0.3 } },
    { selector: 'edge', style: { width: 1.3, 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.7, opacity: 0.8, 'line-color': v('line-strong'), 'target-arrow-color': v('line-strong') } },
    { selector: 'edge.ref', style: { 'line-color': v('e-ref'), 'target-arrow-color': v('e-ref') } },
    { selector: 'edge.pre', style: { 'line-color': v('e-pre'), 'target-arrow-color': v('e-pre') } },
    { selector: 'edge.alias', style: { 'line-color': v('violet'), 'target-arrow-color': v('violet'), 'line-style': 'dashed' } },
    { selector: 'edge.contains', style: { 'line-color': v('ink-3'), 'target-arrow-color': v('ink-3'), width: 1 } },
    { selector: 'edge.on-path', style: { width: 3, opacity: 1, 'z-index': 15 } },
    { selector: 'edge.dim', style: { opacity: 0.15 } },
  ]
}

function elements(): ElementDefinition[] {
  const ids = new Set(props.nodes.map((n) => n.node))
  const out: ElementDefinition[] = []
  for (const n of props.nodes) {
    const cls = [`k-${n.kind}`, n.depth === 0 ? 'h0' : n.depth === 1 ? 'h1' : 'h2']
    if (n.business) cls.push('biz')
    const lb = props.label(n.node)
    out.push({ group: 'nodes', data: { id: n.node, short: truncate(lb, 30), full: lb, depth: n.depth }, classes: cls.join(' ') })
  }
  for (const n of props.nodes) {
    if (n.via && ids.has(n.via)) out.push({ group: 'edges', data: { id: `${n.via}->${n.node}`, source: n.via, target: n.node, kind: n.edge }, classes: edgeClass(n.edge) })
  }
  return out
}

/** 按距离分层：每个距离一列，一列超过 LAYER_ROWS 个节点时折成几列（几十上百个节点时不挤成一列，REQ-055-21）。 */
const LAYER_ROWS = 18
function layerPositions(): Record<string, { x: number; y: number }> {
  const byDepth = new Map<number, string[]>()
  for (const n of props.nodes) byDepth.set(n.depth, [...(byDepth.get(n.depth) ?? []), n.node])
  const pos: Record<string, { x: number; y: number }> = {}
  let x = 0
  for (const d of [...byDepth.keys()].sort((p, q) => p - q)) {
    const ids = byDepth.get(d)!
    const cols = Math.ceil(ids.length / LAYER_ROWS)
    const rows = Math.min(ids.length, LAYER_ROWS)
    ids.forEach((id, i) => { pos[id] = { x: x + Math.floor(i / LAYER_ROWS) * 210, y: ((i % LAYER_ROWS) - (rows - 1) / 2) * 36 } })
    x += cols * 210 + 70
  }
  return pos
}

function run(): void {
  if (!cy) return
  const n = props.nodes.length
  const pos = props.layout === 'layer' ? layerPositions() : {}
  const opts: cytoscape.LayoutOptions = props.layout === 'layer'
    ? ({ name: 'preset', positions: (node: cytoscape.NodeSingular) => pos[node.id()], padding: 20, fit: true } as unknown as cytoscape.LayoutOptions)
    // 节点多时加大斥力与边长，并把标签算进节点大小，减少标签重叠
    : ({ name: 'cose', animate: false, randomize: true, fit: true, padding: 24, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 7000 * Math.max(1, n / 25), idealEdgeLength: () => 60 + Math.min(120, n), gravity: 0.5, numIter: 1500 } as cytoscape.LayoutOptions)
  const lay = cy.layout(opts)
  // 节点少时不要放得过大
  lay.one('layoutstop', () => { if (cy && cy.zoom() > 1.3) { cy.zoom(1.3); cy.center() } })
  lay.run()
}

function refresh(): void {
  if (!cy) return
  cy.elements().remove()
  cy.add(elements())
  marks()
  run()
}
function marks(): void {
  if (!cy) return
  const on = new Set(props.path)
  cy.batch(() => {
    cy!.nodes().forEach((n) => {
      n.toggleClass('on-path', on.has(n.id()))
      n.toggleClass('dim', on.size > 0 && !on.has(n.id()))
      const lb = props.label(n.id())
      n.data({ short: truncate(lb, 30), full: lb })
    })
    cy!.edges().forEach((e) => {
      const p = on.has(e.data('source')) && on.has(e.data('target'))
      e.toggleClass('on-path', p)
      e.toggleClass('dim', on.size > 0 && !p)
    })
  })
}
function fit(): void { cy?.animate({ fit: { eles: cy.elements(), padding: 24 } }, { duration: 200 }) }
defineExpose({ fit })

onMounted(() => {
  cy = cytoscape({ container: box.value, style: style(), minZoom: 0.1, maxZoom: 4, boxSelectionEnabled: false, autounselectify: true })
  ;(box.value as unknown as { __cy?: Core }).__cy = cy
  cy.on('tap', 'node', (ev) => emit('tap', ev.target.id() as string, !!(ev.originalEvent as MouseEvent | undefined)?.shiftKey))
  cy.on('mouseover', 'node', (ev) => {
    const p = ev.target.renderedPosition()
    tip.value = { x: p.x + 12, y: p.y + 12, text: ev.target.data('full') as string }
  })
  cy.on('mouseout', 'node', () => { tip.value = null })
  cy.on('pan zoom', () => { tip.value = null })
  observer = new MutationObserver(() => cy?.style(style()))
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  resizer = new ResizeObserver(() => cy?.resize())
  if (box.value) resizer.observe(box.value)
  void nextTick(refresh)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  resizer?.disconnect()
  cy?.destroy()
  cy = null
})
watch(() => [props.nodes, props.layout], refresh)
watch(() => [props.path, props.label], marks)
</script>

<template>
  <div class="gwrap">
    <div ref="box" class="gview" data-testid="impact-canvas" :data-nodes="nodes.length" />
    <div v-if="tip" class="gtip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }">{{ tip.text }}</div>
  </div>
</template>

<style scoped>
.gwrap { position: relative; flex: 1; min-height: 0; background: var(--canvas); background-image: radial-gradient(var(--grid) 1px, transparent 1px); background-size: 18px 18px; }
.gview { position: absolute; inset: 0; }
.gtip { position: absolute; z-index: 5; pointer-events: none; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 4px; padding: 3px 7px; font: 11.5px var(--font-mono); color: var(--ink); box-shadow: var(--shadow-pop); max-width: 420px; overflow-wrap: anywhere; }
</style>
