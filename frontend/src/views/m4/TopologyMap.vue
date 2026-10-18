<script setup lang="ts">
/**
 * 三层拓扑图（cytoscape）：设备是圆角方块（名称 + 环回地址，有问题时红点），
 * 线按“邻接”画：同网段链路实线（一致 = 青、需注意 = 琥珀、不匹配 = 红），BGP 会话紫色点线，伪线 / 远端 LDP / 静态 BFD 灰色虚线。
 * 选中一条线时两端设备描边、其余淡出；选中设备时它的线高亮。颜色取自 CSS 变量，跟随明 / 暗主题。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape'
import { protocols, shortIf, type Group, type TopoNode } from './topology'

const props = defineProps<{
  nodes: TopoNode[]
  groups: Group[]
  layers: { phy: boolean; bgp: boolean; l2: boolean; ifn: boolean; iso: boolean }
  sel: { k: 'link' | 'dev'; id: string } | null
}>()
const emit = defineEmits<{ (e: 'pick', k: 'link' | 'dev', id: string): void; (e: 'clear'): void }>()

const box = ref<HTMLDivElement>()
const tip = ref<{ x: number; y: number; text: string } | null>(null)
let cy: Core | null = null
let observer: MutationObserver | null = null
let resizer: ResizeObserver | null = null
let structure = ''

const v = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()

function style(): StylesheetJson {
  const mono = v('font-mono') || 'monospace'
  const ui = v('font-ui') || 'sans-serif'
  return [
    {
      selector: 'node',
      style: {
        shape: 'round-rectangle', width: 150, height: 46, 'background-color': v('surface'), 'border-width': 1.2, 'border-color': v('line-strong'),
        label: 'data(label)', 'text-wrap': 'wrap', 'font-family': mono, 'font-size': 11, color: v('ink'), 'text-valign': 'center', 'text-halign': 'center',
        'overlay-opacity': 0,
      },
    },
    { selector: 'node.hw', style: { 'border-color': '#C7000B', 'border-width': 1.4 } },
    { selector: 'node.cs', style: { 'border-color': '#1BA0D7', 'border-width': 1.4 } },
    { selector: 'node.bad', style: { 'background-color': v('red-soft') } },
    { selector: 'node.is-sel', style: { 'border-color': v('ink'), 'border-width': 2.6 } },
    { selector: 'node.is-end', style: { 'border-color': v('amber'), 'border-width': 2.6 } },
    { selector: 'node.dim', style: { opacity: 0.35 } },
    { selector: 'edge', style: { width: 3, 'curve-style': 'bezier', 'line-color': v('teal'), 'font-family': mono, 'font-size': 9.5, color: v('ink-2'), 'text-background-color': v('canvas'), 'text-background-opacity': 0.85, 'text-background-padding': '1px', 'text-rotation': 'autorotate', 'overlay-opacity': 0 } },
    { selector: 'edge.phy', style: { label: 'data(label)' } },
    { selector: 'edge.ifn', style: { 'source-label': 'data(ai)', 'target-label': 'data(bi)', 'source-text-offset': 40, 'target-text-offset': 40, 'font-family': ui } },
    { selector: 'edge.st-warn', style: { 'line-color': v('amber') } },
    { selector: 'edge.st-bad', style: { 'line-color': v('red') } },
    { selector: 'edge.bgp', style: { width: 1.6, 'line-color': v('violet'), 'line-style': 'dotted' } },
    { selector: 'edge.bgp.st-bad', style: { 'line-color': v('red'), 'line-style': 'dashed', width: 2 } },
    { selector: 'edge.bgp.st-warn', style: { 'line-color': v('amber'), 'line-style': 'dashed', width: 2 } },
    { selector: 'edge.l2', style: { width: 1.6, 'line-color': v('ink-3'), 'line-style': 'dashed' } },
    { selector: 'edge.l2.st-bad', style: { 'line-color': v('red') } },
    { selector: 'edge.l2.st-warn', style: { 'line-color': v('amber') } },
    { selector: 'edge.is-sel', style: { width: 6, 'z-index': 20 } },
    { selector: 'edge.dim', style: { opacity: 0.18 } },
    { selector: '.off', style: { display: 'none' } },
  ]
}

function elements(): ElementDefinition[] {
  const out: ElementDefinition[] = []
  const ids = new Set(props.nodes.map((n) => n.id))
  for (const n of props.nodes) {
    const fam = n.family.startsWith('huawei') ? 'hw' : n.family.startsWith('cisco') ? 'cs' : ''
    out.push({ group: 'nodes', data: { id: n.id, label: `${n.id}\n${n.loopbacks[0] ?? n.lsr_id ?? ''}`, tip: `${n.id} · ${n.profile}` }, classes: [fam, n.issues ? 'bad' : ''].join(' ') })
  }
  for (const g of props.groups) {
    if (!ids.has(g.a) || !ids.has(g.b)) continue
    const proto = protocols(g).map((p) => p.toUpperCase().replace('ISIS', 'IS-IS')).join(' · ')
    out.push({
      group: 'edges',
      data: { id: g.id, source: g.a, target: g.b, label: [g.segment, proto].filter(Boolean).join('  '), ai: shortIf(g.ai), bi: shortIf(g.bi), tip: `${g.a} ${g.ai} ⟷ ${g.b} ${g.bi}` },
      classes: `${g.kind} st-${g.status}`,
    })
  }
  return out
}

function marks(): void {
  if (!cy) return
  const sel = props.sel
  const g = sel?.k === 'link' ? props.groups.find((x) => x.id === sel.id) : null
  cy.batch(() => {
    cy!.edges().forEach((e) => {
      const kind = (['phy', 'bgp', 'l2'] as const).find((k) => e.hasClass(k)) ?? 'phy'
      e.toggleClass('off', !props.layers[kind])
      e.toggleClass('ifn', props.layers.ifn || e.id() === g?.id)
      const on = g ? e.id() === g.id : sel?.k === 'dev' ? e.source().id() === sel.id || e.target().id() === sel.id : true
      e.toggleClass('is-sel', !!g && e.id() === g.id)
      e.toggleClass('dim', !on)
    })
    cy!.nodes().forEach((n) => {
      const end = !!g && (g.a === n.id() || g.b === n.id())
      n.toggleClass('is-end', end)
      n.toggleClass('is-sel', sel?.k === 'dev' && sel.id === n.id())
      n.toggleClass('dim', !!g && !end)
    })
  })
}

function refresh(): void {
  if (!cy) return
  const key = props.nodes.map((n) => n.id).join(',') + '|' + props.groups.map((g) => g.id).join(',')
  if (key !== structure) {
    structure = key
    cy.elements().remove()
    cy.add(elements())
    marks()
    cy.layout({ name: 'cose', animate: false, randomize: false, fit: true, padding: 40, nodeRepulsion: () => 400000, nodeOverlap: 40, idealEdgeLength: () => 180, componentSpacing: 120, gravity: 0.25, numIter: 2000, nodeDimensionsIncludeLabels: true } as cytoscape.LayoutOptions)
      .one('layoutstop', () => { if (cy && cy.zoom() > 1.2) { cy.zoom(1.2); cy.center() } })
      .run()
  } else marks()
}
function fit(): void { cy?.animate({ fit: { eles: cy.elements(':visible'), padding: 40 } }, { duration: 200 }) }
defineExpose({ fit })

onMounted(() => {
  cy = cytoscape({ container: box.value, style: style(), minZoom: 0.15, maxZoom: 3, boxSelectionEnabled: false, autounselectify: true })
  ;(box.value as unknown as { __cy?: Core }).__cy = cy
  cy.on('tap', 'node', (ev) => emit('pick', 'dev', ev.target.id() as string))
  cy.on('tap', 'edge', (ev) => emit('pick', 'link', ev.target.id() as string))
  cy.on('tap', (ev) => { if (ev.target === cy) emit('clear') })
  cy.on('mouseover', 'node, edge', (ev) => {
    const p = ev.renderedPosition ?? { x: 0, y: 0 }
    tip.value = { x: p.x + 12, y: p.y + 12, text: ev.target.data('tip') as string }
  })
  cy.on('mouseout', 'node, edge', () => { tip.value = null })
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
watch(() => [props.nodes, props.groups], refresh)
watch(() => [props.sel, props.layers], marks, { deep: true })
</script>

<template>
  <div class="mapw">
    <div ref="box" class="gview" data-testid="topo-canvas" :data-nodes="nodes.length" :data-links="groups.length" />
    <div v-if="tip" class="gtip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }">{{ tip.text }}</div>
  </div>
</template>

<style scoped>
.mapw { flex: 1; min-height: 0; position: relative; background: var(--canvas); background-image: radial-gradient(var(--grid) 1px, transparent 1px); background-size: 20px 20px; }
.gview { position: absolute; inset: 0; }
.gtip { position: absolute; z-index: 5; pointer-events: none; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 4px; padding: 3px 7px; font: 11.5px var(--font-mono); color: var(--ink); box-shadow: var(--shadow-pop); }
</style>
