<script setup lang="ts">
/**
 * 关系图谱（REQ-027）：类似笔记软件的关系图。每个对象一个圆点（大小按连接数、颜色按功能域），
 * 包含关系是细淡的线，依赖按类型着色；cytoscape 自带的 cose 力导向布局；可拖动单个点与整张图、滚轮缩放；
 * 悬停高亮该点与相邻点，其余淡出；点击打开详情。结构变化（显示默认值 / 原文）时重新布局，
 * 功能域开关、依赖类型开关、选中、搜索只改样式类，不重新布局。
 * 设备配置分析页（REQ-034）另用 layout="bands"：按层分带（预设位置 + 每层一条背景带），跨层的引用 / 前置依赖加粗；
 * colorOf 可把圆点颜色改为按层着色。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape'
import { EDGE_SHORT } from './model'
import { bandLayout, dotSize, domainColorVar, type FNode, type ForceData } from './force'
import { readPalette, truncate, type Palette } from './style'

const props = defineProps<{
  data: ForceData
  domainOrder: string[]
  hiddenDomains: Set<string>
  /** 显示的依赖类型（contains 也在内） */
  kinds: Set<string>
  /** 选中的圆点 */
  selected: string | null
  matches: Set<string>
  dimOthers: boolean
  edgeName: (kind: string) => string
  /** 布局：cose 力导向（默认）/ bands 按层分带 */
  layout?: 'cose' | 'bands'
  /** 分带：层的顺序（自上而下）、节点 → 层、层名 */
  bands?: { order: string[]; of: (id: string) => string | null; label: (band: string) => string }
  /** 圆点颜色的 CSS 变量名（默认按功能域） */
  colorOf?: (n: FNode) => string
}>()
const emit = defineEmits<{ (e: 'tap', id: string): void; (e: 'background'): void }>()

const box = ref<HTMLDivElement>()
const tip = ref<{ x: number; y: number; text: string } | null>(null)
const layouting = ref(false)
let cy: Core | null = null
let structureKey = ''
let observer: MutationObserver | null = null
let resizer: ResizeObserver | null = null

function domColors(): Map<string, string> {
  const cs = getComputedStyle(document.documentElement)
  const m = new Map<string, string>()
  const all = new Set([...props.domainOrder, ...props.data.nodes.map((n) => n.domain)])
  for (const d of all) m.set(d, cs.getPropertyValue(domainColorVar(d, props.domainOrder)).trim() || '#888')
  return m
}
/** 圆点颜色：给了 colorOf 时按它（CSS 变量），否则按功能域。 */
function colorFn(): (n: FNode) => string {
  if (props.colorOf) {
    const cs = getComputedStyle(document.documentElement)
    const cache = new Map<string, string>()
    return (n) => {
      const v = props.colorOf!(n)
      if (!cache.has(v)) cache.set(v, cs.getPropertyValue(v).trim() || '#888')
      return cache.get(v)!
    }
  }
  const colors = domColors()
  return (n) => colors.get(n.domain) ?? '#888'
}
const banded = (): boolean => props.layout === 'bands' && !!props.bands
function bandColor(id: string): string {
  const v = id === '__other' ? 'unclassified' : id
  return getComputedStyle(document.documentElement).getPropertyValue(`--ly-${v}`).trim() || '#888'
}

function style(p: Palette): StylesheetJson {
  const ui = p['font-ui'] || 'sans-serif'
  const mono = p['font-mono'] || 'monospace'
  return [
    {
      selector: 'node',
      style: {
        width: 'data(size)', height: 'data(size)', shape: 'ellipse', 'background-color': 'data(color)',
        'border-width': 1, 'border-color': p.surface, label: 'data(short)', 'font-family': mono, 'font-size': 9,
        color: p['ink-2'], 'text-valign': 'bottom', 'text-margin-y': 3, 'min-zoomed-font-size': 7,
        'text-background-color': p.canvas, 'text-background-opacity': 0.7, 'text-background-padding': '1px',
        'overlay-opacity': 0,
      },
    },
    { selector: 'node[degree >= 6]', style: { 'font-size': 10.5, 'font-weight': 600, color: p.ink } },
    { selector: 'node.k-raw, node.k-ext', style: { shape: 'round-rectangle', 'background-opacity': 0.55 } },
    { selector: 'node.k-unknown', style: { shape: 'diamond', 'background-color': p.red } },
    // 隐藏配置（REQ-028）：默认值灰色虚线描边，派生值紫色点线
    { selector: 'node.s-default', style: { 'background-color': p.canvas, 'border-width': 1.6, 'border-style': 'dashed', 'border-color': p['ink-3'] } },
    { selector: 'node.s-derived', style: { 'border-width': 1.8, 'border-style': 'dotted', 'border-color': p.violet } },
    { selector: 'node.is-sel', style: { 'border-width': 3, 'border-color': p.amber, 'border-style': 'solid', 'z-index': 20, label: 'data(label)', 'font-size': 11, color: p.ink } },
    { selector: 'node.is-match', style: { 'border-width': 2.4, 'border-color': p.amber } },
    { selector: 'node.hl', style: { label: 'data(label)', 'z-index': 15, color: p.ink, 'font-size': 10.5 } },
    { selector: 'node.faded, node.is-dim', style: { opacity: 0.14, 'text-opacity': 0 } },
    { selector: 'node.off, edge.off', style: { display: 'none' } },
    { selector: 'edge', style: { width: 1.3, 'curve-style': 'straight', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.6, opacity: 0.85, 'font-family': ui } },
    { selector: 'edge.contains', style: { 'curve-style': 'haystack', 'haystack-radius': 0, width: 0.7, 'line-color': p['line-strong'], opacity: 0.55, 'target-arrow-shape': 'none' } },
    { selector: 'edge.ref', style: { 'line-color': p['e-ref'], 'target-arrow-color': p['e-ref'] } },
    { selector: 'edge.pre', style: { 'line-color': p['e-pre'], 'target-arrow-color': p['e-pre'] } },
    { selector: 'edge.side', style: { 'line-color': p['e-side'], 'target-arrow-color': p['e-side'], 'line-style': 'dashed' } },
    { selector: 'edge.mutex', style: { 'line-color': p['e-mutex'], 'target-arrow-color': p['e-mutex'], 'target-arrow-shape': 'tee' } },
    { selector: 'edge.hl', style: { width: 2.2, opacity: 1, 'z-index': 12 } },
    // 按层分带：背景带（不响应事件）与跨层依赖
    {
      selector: 'node.band',
      style: {
        shape: 'round-rectangle', width: 'data(w)', height: 'data(h)', 'background-color': 'data(color)', 'background-opacity': 0.07,
        'border-width': 1, 'border-color': 'data(color)', 'border-opacity': 0.35, label: 'data(label)', 'font-family': ui, 'font-size': 'data(fs)' as unknown as number,
        'min-zoomed-font-size': 0, 'font-weight': 600, color: 'data(color)', 'text-valign': 'top', 'text-halign': 'center',
        'text-margin-y': 'data(my)' as unknown as number, 'text-margin-x': 'data(lx)' as unknown as number,
        'text-background-opacity': 0, events: 'no', 'z-index': 0, 'overlay-opacity': 0,
      },
    },
    { selector: 'node.k-object, node.k-raw, node.k-unknown, node.k-ext', style: { 'z-index': 10 } },
    { selector: 'edge.cross', style: { width: 2.4, 'line-color': p['e-cross'], 'target-arrow-color': p['e-cross'], opacity: 1, 'z-index': 11 } },
    { selector: 'edge.faded, edge.is-dim', style: { opacity: 0.05 } },
  ]
}

function elements(): ElementDefinition[] {
  const color = colorFn()
  const out: ElementDefinition[] = []
  for (const n of props.data.nodes) {
    const cls = [`k-${n.kind}`]
    if (n.origin !== 'explicit') cls.push(`s-${n.origin}`)
    out.push({
      group: 'nodes',
      data: { id: n.id, label: truncate(n.label, 60), short: truncate(n.label, 28), size: dotSize(n.degree), degree: n.degree, color: color(n), domain: n.domain },
      classes: cls.join(' '),
    })
  }
  const bandOf = banded() ? props.bands!.of : null
  for (const e of props.data.edges) {
    const cls = [EDGE_SHORT[e.kind] ?? 'ref']
    if (bandOf && (e.kind === 'reference' || e.kind === 'prerequisite') && bandOf(e.source) !== bandOf(e.target)) cls.push('cross')
    out.push({ group: 'edges', data: { id: e.id, source: e.source, target: e.target, kind: e.kind }, classes: cls.join(' ') })
  }
  return out
}

/** 按层分带：算出圆点位置并加上背景带（模型坐标，宽度取画布宽度）。 */
function bandPositions(): Map<string, { x: number; y: number }> {
  if (!cy || !props.bands) return new Map()
  // 画布宽高比决定模型宽度：圆点多时把带拉宽，整体比例接近画布，适应窗口后不至于细长
  const cw = Math.max(640, box.value?.clientWidth ?? 900)
  const ch = Math.max(360, box.value?.clientHeight ?? 600)
  const width = Math.max(cw, Math.round(120 + Math.sqrt(props.data.nodes.length * 74 * 44 * (cw / ch)) * 1.15))
  const { pos, bands } = bandLayout(props.data.nodes, props.bands.of, props.bands.order, width)
  cy.remove('node.band')
  cy.add(
    bands.map((b) => ({
      group: 'nodes' as const,
      // 带名的字号按缩放比例放大：适应窗口后屏幕上约 12px
      data: { id: `band:${b.id}`, w: width - 8, h: b.h, fs: 12 * (width / cw), my: 18 * (width / cw), lx: -(width - 8) / 2 + 64 * (width / cw), label: b.id === '__other' ? '' : props.bands!.label(b.id), color: bandColor(b.id) },
      position: { x: width / 2, y: b.y + b.h / 2 - 12 },
      classes: 'band',
      selectable: false,
      grabbable: false,
    })),
  )
  return pos
}

function applyClasses(): void {
  if (!cy) return
  const sel = props.selected
  cy.batch(() => {
    cy!.nodes(':not(.band)').forEach((n) => {
      const id = n.id()
      n.toggleClass('off', props.hiddenDomains.has(n.data('domain')))
      n.toggleClass('is-sel', id === sel)
      n.toggleClass('is-match', props.matches.has(id))
      n.toggleClass('is-dim', props.dimOthers && !props.matches.has(id) && id !== sel)
    })
    cy!.edges().forEach((e) => { e.toggleClass('off', !props.kinds.has(e.data('kind'))) })
  })
}

function layout(): void {
  if (!cy) return
  layouting.value = true
  // 先让“布局中”提示画出来，再做同步计算
  setTimeout(() => {
    if (!cy) return
    if (banded()) {
      const pos = bandPositions()
      const lay = cy.layout({ name: 'preset', positions: (nd: cytoscape.NodeSingular) => pos.get(nd.id()) ?? nd.position(), fit: true, padding: 16, animate: false } as cytoscape.LayoutOptions)
      lay.one('layoutstop', () => { layouting.value = false })
      lay.run()
      return
    }
    cy.remove('node.band')
    const n = cy.nodes().length
    const lay = cy.layout({
      name: 'cose',
      animate: false,
      randomize: true,
      fit: true,
      padding: 24,
      nodeDimensionsIncludeLabels: false,
      componentSpacing: 30,
      nodeRepulsion: () => 9000,
      nodeOverlap: 8,
      idealEdgeLength: (e: cytoscape.EdgeSingular) => (e.data('kind') === 'contains' ? 34 : 70),
      edgeElasticity: (e: cytoscape.EdgeSingular) => (e.data('kind') === 'contains' ? 120 : 60),
      gravity: 0.6,
      numIter: n > 600 ? 600 : 1000,
      coolingFactor: 0.97,
      initialTemp: 600,
    } as cytoscape.LayoutOptions)
    lay.one('layoutstop', () => { layouting.value = false })
    lay.run()
  }, 30)
}

function refresh(): void {
  if (!cy) return
  const key = `${props.layout ?? 'cose'}\u0000` + props.data.nodes.map((n) => n.id).join('\n') + '\u0000' + props.data.edges.map((e) => e.id).join('\n')
  if (key !== structureKey) {
    structureKey = key
    cy.elements().remove()
    cy.add(elements())
    applyClasses()
    layout()
  } else {
    // 节点名（显示风格）变化时只更新文字
    cy.batch(() => {
      for (const n of props.data.nodes) {
        const el = cy!.getElementById(n.id)
        if (el.nonempty() && el.data('label') !== truncate(n.label, 60)) el.data({ label: truncate(n.label, 60), short: truncate(n.label, 28) })
      }
    })
    applyClasses()
  }
}

function hover(id: string | null): void {
  if (!cy) return
  cy.batch(() => {
    cy!.elements().removeClass('faded hl')
    if (!id) return
    const n = cy!.getElementById(id)
    if (n.empty()) return
    const hood = n.closedNeighborhood()
    cy!.elements().not(hood).not('.band').addClass('faded')
    hood.addClass('hl')
  })
}

function focus(id: string): void {
  if (!cy || !box.value) return
  const run = () => {
    const n = cy?.getElementById(id)
    if (!cy || !n || n.empty()) return
    const rp = n.renderedPosition()
    const w = box.value!.clientWidth
    const h = box.value!.clientHeight
    if (rp.x > 40 && rp.x < w - 40 && rp.y > 30 && rp.y < h - 30) return
    cy.animate({ center: { eles: n } }, { duration: 260 })
  }
  if (layouting.value) setTimeout(run, 400)
  else run()
}
function fit(): void {
  if (!cy) return
  cy.animate({ fit: { eles: cy.elements(':visible'), padding: 24 } }, { duration: 260 })
}
function relayout(): void {
  layout()
}
defineExpose({ focus, fit, relayout })

onMounted(() => {
  cy = cytoscape({
    container: box.value,
    style: style(readPalette()),
    minZoom: 0.08,
    maxZoom: 4,
    boxSelectionEnabled: false,
    autounselectify: true,
    textureOnViewport: true,
    hideEdgesOnViewport: false,
    pixelRatio: 'auto',
  })
  // e2e 用：在容器元素上留一个 cytoscape 实例的引用（拖动测试）
  ;(box.value as unknown as { __cy?: Core }).__cy = cy
  cy.on('tap', 'node:not(.band)', (ev) => emit('tap', ev.target.id() as string))
  cy.on('tap', (ev) => { if (ev.target === cy) emit('background') })
  cy.on('mouseover', 'node:not(.band)', (ev) => {
    const n = ev.target
    hover(n.id())
    const p = n.renderedPosition()
    tip.value = { x: p.x + 12, y: p.y + 12, text: truncate(`${n.data('label')}  ·  ${n.data('degree')}`, 200) }
  })
  cy.on('mouseout', 'node', () => { hover(null); tip.value = null })
  cy.on('grab', 'node', () => { tip.value = null })
  cy.on('mouseover', 'edge', (ev) => {
    const e = ev.target
    if (e.data('kind') === 'contains') return
    const p = ev.renderedPosition ?? e.midpoint()
    tip.value = { x: p.x + 10, y: p.y + 10, text: props.edgeName(e.data('kind')) }
  })
  cy.on('mouseout', 'edge', () => { tip.value = null })
  cy.on('pan zoom', () => { tip.value = null })
  observer = new MutationObserver(() => {
    if (!cy) return
    cy.style(style(readPalette()))
    const color = colorFn()
    const byId = new Map(props.data.nodes.map((n) => [n.id, n]))
    cy.batch(() => {
      cy!.nodes(':not(.band)').forEach((n) => { const fn = byId.get(n.id()); if (fn) n.data('color', color(fn)) })
      cy!.nodes('.band').forEach((n) => { n.data('color', bandColor(n.id().slice(5))) })
    })
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  resizer = new ResizeObserver(() => cy?.resize())
  if (box.value) resizer.observe(box.value)
  nextTick(refresh)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  resizer?.disconnect()
  cy?.destroy()
  cy = null
})

watch(() => [props.data, props.hiddenDomains, props.kinds, props.selected, props.matches, props.dimOthers, props.layout], refresh)
</script>

<template>
  <div class="gwrap">
    <div ref="box" class="gview canvas" data-testid="force-canvas" :data-nodes="data.nodes.length" :data-layouting="layouting ? '1' : '0'" />
    <div v-if="tip" class="gtip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }">{{ tip.text }}</div>
    <div v-if="layouting" class="glayout small faint">{{ $t('device-graph.layouting') }}</div>
    <div v-if="!data.nodes.length" class="gempty small faint">{{ $t('device-graph.forceEmpty') }}</div>
  </div>
</template>

<style scoped>
.gwrap { position: relative; flex: 1; min-height: 0; display: flex; }
.gview { flex: 1; min-height: 0; }
.gtip {
  position: absolute; z-index: 5; max-width: 420px; pointer-events: none;
  padding: 5px 8px; border-radius: 5px; border: 1px solid var(--line); background: var(--surface);
  box-shadow: var(--shadow-pop); font: 12px/1.45 var(--font-mono); color: var(--ink); overflow-wrap: anywhere; white-space: pre-wrap;
}
.glayout { position: absolute; top: 8px; right: 12px; }
.gempty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
</style>
