<script setup lang="ts">
/**
 * 三层拓扑图（cytoscape）：设备画成 REQ-042 的设备图标（按角色或平台外形，叠加厂商标识与状态角标；待采纳的 AI 角色建议
 * 为紫色虚线半透明），名称与角色 / 平台小字在图标下方；按分组标注画成分组框（compound 父节点），有分组或角色时按
 * “分组成列、角色分层”排版，否则力导向。线按“邻接”画：同网段链路实线（一致 = 青、需注意 = 琥珀、不匹配 = 红），
 * BGP 会话紫色点线，伪线 / 远端 LDP / 静态 BFD 灰色虚线；采纳的推测对端灰色细线，待采纳的推测对端紫色虚线（“AI 推测”）。
 * 图标做成 SVG data URI：CSS 变量在图片里不生效，按当前主题的实际颜色生成，主题或图标风格变化时重绘。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape'
import { protocols, shortIf, type Group, type TopoNode } from './topology'
import { dataUri, readPalette, svg, type Badge, type VendorCode } from '@/components/devicon/lmi'
import type { Pos } from './topomarks'
import '@/components/devicon/devicon.css'

/** 每台设备的显示（父组件按标注与建议算好，文字已是当前语言）。 */
export interface NodeShow { glyph: string; vendor: VendorCode | ''; badges: Badge[]; ghost: boolean; sub: string; subAi: boolean; group: string }
/** 额外的节点与边：推测的对端（peer / ai），以及 M9 网络外的对端（out：灰色虚线短线，节点可点，点了 emit pick('out', id)）。 */
export interface ExtraShow { nodes: { id: string; label: string; glyph: string; ghost: boolean; group: string; out?: boolean }[]; edges: { id: string; source: string; target: string; kind: 'peer' | 'ai' | 'out'; label: string }[] }

const props = withDefaults(defineProps<{
  nodes: TopoNode[]
  groups: Group[]
  layers: { phy: boolean; bgp: boolean; l2: boolean; ifn: boolean; iso: boolean }
  sel: { k: 'link' | 'dev'; id: string } | null
  show?: Record<string, NodeShow>
  extra?: ExtraShow
  positions?: Record<string, Pos> | null
  iconSet?: string
}>(), { show: () => ({}), extra: () => ({ nodes: [], edges: [] }), positions: null, iconSet: 'geo' })
const emit = defineEmits<{ (e: 'pick', k: 'link' | 'dev' | 'out', id: string): void; (e: 'clear'): void }>()

const box = ref<HTMLDivElement>()
const tip = ref<{ x: number; y: number; text: string } | null>(null)
let cy: Core | null = null
let observer: MutationObserver | null = null
let resizer: ResizeObserver | null = null
let structure = ''
const ICON = 48

const v = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()

function style(): StylesheetJson {
  const mono = v('font-mono') || 'monospace'
  const ui = v('font-ui') || 'sans-serif'
  return [
    {
      selector: 'node.dev, node.ext',
      style: {
        shape: 'round-rectangle', width: ICON + 8, height: ICON + 8, 'background-color': v('canvas'), 'background-opacity': 0,
        'background-image': 'data(img)', 'background-width': `${ICON}px`, 'background-height': `${ICON}px`, 'background-clip': 'none', 'bounds-expansion': 6,
        'border-width': 0, 'border-color': v('blue'),
        label: 'data(label)', 'text-wrap': 'wrap', 'text-max-width': '170px', 'font-family': mono, 'font-size': 11, 'font-weight': 600, color: v('ink'),
        'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 3, 'line-height': 1.3,
        'text-background-color': v('canvas'), 'text-background-opacity': 0.75, 'text-background-padding': '1px', 'overlay-opacity': 0,
      },
    },
    { selector: 'node.ghost, node.sub-ai', style: { color: v('violet') } },
    { selector: 'node.is-sel', style: { 'border-width': 2, 'border-color': v('blue'), 'background-color': v('blue-soft'), 'background-opacity': 1 } },
    { selector: 'node.is-end', style: { 'border-width': 2, 'border-color': v('amber'), 'background-color': v('amber-soft'), 'background-opacity': 1 } },
    { selector: 'node.dim', style: { opacity: 0.38 } },
    {
      selector: 'node.grp',
      style: {
        shape: 'round-rectangle', 'background-color': v('surface'), 'background-opacity': 0.55, 'border-width': 1, 'border-color': v('line-strong'),
        label: 'data(label)', 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -4, 'font-family': ui, 'font-size': 12.5, 'font-weight': 600, color: v('ink-2'),
        padding: '22px', 'overlay-opacity': 0,
      },
    },
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
    { selector: 'edge.xpeer', style: { width: 1.4, 'line-color': v('ink-3'), label: 'data(label)', 'font-family': ui } },
    { selector: 'edge.xai', style: { width: 1.6, 'line-color': v('violet'), 'line-style': 'dashed', 'line-dash-pattern': [5, 4], label: 'data(label)', color: v('violet'), 'font-family': ui, 'font-weight': 600, 'font-size': 10.5 } },
    { selector: 'edge.xout', style: { width: 1.6, 'line-color': v('ink-3'), 'line-style': 'dashed', 'line-dash-pattern': [3, 3], label: 'data(label)', color: v('ink-3'), 'font-family': mono, 'font-size': 9.5, opacity: 0.85 } },
    { selector: 'node.out', style: { opacity: 0.72, color: v('ink-2'), 'font-weight': 500 } },
    { selector: 'edge.is-sel', style: { width: 6, 'z-index': 20 } },
    { selector: 'edge.dim', style: { opacity: 0.18 } },
    { selector: '.off', style: { display: 'none' } },
  ]
}

function icon(glyph: string, o: { vendor?: VendorCode | ''; badges?: Badge[]; ghost?: boolean }): string {
  const pal = readPalette(o.ghost ? 'violet' : 'ink')
  return dataUri(svg(props.iconSet, glyph, { size: ICON, vendor: o.vendor || null, badges: o.badges, ghost: o.ghost, palette: pal }))
}

function devData(n: TopoNode): { img: string; label: string; cls: string } {
  const s = props.show[n.id]
  const glyph = s?.glyph ?? 'plat_atn'
  const sub = s?.sub ?? (n.loopbacks[0] ?? n.lsr_id ?? '')
  return {
    img: icon(glyph, { vendor: s?.vendor, badges: s?.badges, ghost: s?.ghost }),
    label: sub ? `${n.id}\n${sub}` : n.id,
    cls: ['dev', s?.ghost ? 'ghost' : '', s?.subAi ? 'sub-ai' : ''].filter(Boolean).join(' '),
  }
}

function groupIds(): string[] {
  const set = new Set<string>()
  for (const n of props.nodes) { const g = props.show[n.id]?.group; if (g) set.add(g) }
  for (const x of props.extra.nodes) if (x.group) set.add(x.group)
  return [...set].sort()
}

function elements(): ElementDefinition[] {
  const out: ElementDefinition[] = []
  const ids = new Set(props.nodes.map((n) => n.id))
  for (const g of groupIds()) out.push({ group: 'nodes', data: { id: `grp:${g}`, label: g }, classes: 'grp', selectable: false })
  const pos = props.positions
  for (const n of props.nodes) {
    const d = devData(n)
    const g = props.show[n.id]?.group
    out.push({
      group: 'nodes',
      data: { id: n.id, label: d.label, img: d.img, tip: `${n.id} · ${n.profile}`, ...(g ? { parent: `grp:${g}` } : {}) },
      classes: d.cls,
      ...(pos?.[n.id] ? { position: { ...pos[n.id] } } : {}),
    })
  }
  for (const x of props.extra.nodes) {
    ids.add(x.id)
    out.push({
      group: 'nodes',
      data: { id: x.id, label: x.label, img: icon(x.glyph, { ghost: x.ghost }), tip: x.label, ...(x.group ? { parent: `grp:${x.group}` } : {}) },
      classes: `ext${x.ghost ? ' ghost' : ''}${x.out ? ' out' : ''}`,
      ...(pos?.[x.id] ? { position: { ...pos[x.id] } } : {}),
    })
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
  for (const e of props.extra.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue
    out.push({ group: 'edges', data: { id: e.id, source: e.source, target: e.target, label: e.label, tip: e.label }, classes: e.kind === 'ai' ? 'xai' : e.kind === 'out' ? 'xout' : 'xpeer' })
  }
  return out
}

/** 只更新图标与文字（主题、图标风格、标注变化），不重新排版。 */
function decorate(): void {
  if (!cy) return
  cy.batch(() => {
    for (const n of props.nodes) {
      const el = cy!.getElementById(n.id)
      if (!el.nonempty()) continue
      const d = devData(n)
      el.data('img', d.img)
      el.data('label', d.label)
      el.classes(d.cls)
    }
    for (const x of props.extra.nodes) {
      const el = cy!.getElementById(x.id)
      if (el.nonempty()) el.data('img', icon(x.glyph, { ghost: x.ghost }))
    }
  })
  marks()
}

function marks(): void {
  if (!cy) return
  const sel = props.sel
  const g = sel?.k === 'link' ? props.groups.find((x) => x.id === sel.id) : null
  cy.batch(() => {
    cy!.edges().forEach((e) => {
      const kind = (['phy', 'bgp', 'l2'] as const).find((k) => e.hasClass(k))
      e.toggleClass('off', kind ? !props.layers[kind] : false)
      e.toggleClass('ifn', !!kind && (props.layers.ifn || e.id() === g?.id))
      const on = g ? e.id() === g.id : sel?.k === 'dev' ? e.source().id() === sel.id || e.target().id() === sel.id : true
      e.toggleClass('is-sel', !!g && e.id() === g.id)
      e.toggleClass('dim', !on)
    })
    cy!.nodes('.dev, .ext').forEach((n) => {
      const end = !!g && (g.a === n.id() || g.b === n.id())
      n.toggleClass('is-end', end)
      n.toggleClass('is-sel', sel?.k === 'dev' && sel.id === n.id())
      n.toggleClass('dim', !!g && !end)
    })
  })
}

function refresh(): void {
  if (!cy) return
  const key = [
    props.nodes.map((n) => n.id).join(','), props.groups.map((g) => g.id).join(','),
    props.extra.nodes.map((n) => `${n.id}@${n.group}`).join(','), props.extra.edges.map((e) => e.id).join(','),
    props.nodes.map((n) => props.show[n.id]?.group ?? '').join(','), JSON.stringify(props.positions ?? null),
  ].join('|')
  if (key !== structure) {
    structure = key
    cy.elements().remove()
    cy.add(elements())
    marks()
    const layout = props.positions
      ? ({ name: 'preset', fit: true, padding: 40 } as cytoscape.LayoutOptions)
      : ({ name: 'cose', animate: false, randomize: false, fit: true, padding: 40, nodeRepulsion: () => 400000, nodeOverlap: 40, idealEdgeLength: () => 180, componentSpacing: 120, gravity: 0.25, numIter: 2000, nodeDimensionsIncludeLabels: true } as cytoscape.LayoutOptions)
    if (!props.positions) {
      // 起始位置按编号排在圆上：cose 不随机，每次打开同一份拓扑布局相同（REQ-055-22）
      const ns = cy.nodes().sort((x, y) => x.id().localeCompare(y.id()))
      const r = 60 + ns.length * 18
      ns.forEach((n, i) => { n.position({ x: r * Math.cos((2 * Math.PI * i) / ns.length), y: r * Math.sin((2 * Math.PI * i) / ns.length) }) })
    }
    cy.layout(layout).one('layoutstop', () => { if (cy && cy.zoom() > 1.2) { cy.zoom(1.2); cy.center() } }).run()
  } else decorate()
}
function fit(): void { cy?.animate({ fit: { eles: cy.elements(':visible'), padding: 40 } }, { duration: 200 }) }
defineExpose({ fit })

onMounted(() => {
  cy = cytoscape({ container: box.value, style: style(), minZoom: 0.15, maxZoom: 3, boxSelectionEnabled: false, autounselectify: true })
  ;(box.value as unknown as { __cy?: Core }).__cy = cy
  cy.on('tap', 'node.dev', (ev) => emit('pick', 'dev', ev.target.id() as string))
  cy.on('tap', 'node.out', (ev) => emit('pick', 'out', ev.target.id() as string))
  cy.on('tap', 'edge', (ev) => {
    if (ev.target.hasClass('xout')) emit('pick', 'out', ev.target.target().id() as string)
    else if (!ev.target.hasClass('xpeer') && !ev.target.hasClass('xai')) emit('pick', 'link', ev.target.id() as string)
  })
  cy.on('tap', (ev) => { if (ev.target === cy) emit('clear') })
  cy.on('mouseover', 'node.dev, node.ext, edge', (ev) => {
    const p = ev.renderedPosition ?? { x: 0, y: 0 }
    tip.value = { x: p.x + 12, y: p.y + 12, text: ev.target.data('tip') as string }
  })
  cy.on('mouseout', 'node, edge', () => { tip.value = null })
  cy.on('pan zoom', () => { tip.value = null })
  observer = new MutationObserver(() => { cy?.style(style()); decorate() })
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
watch(() => [props.nodes, props.groups, props.extra, props.positions, props.show, props.iconSet], refresh)
watch(() => [props.sel, props.layers], marks, { deep: true })
// 选中一条线（例如点了一致性问题）：地图移到它的两端（REQ-055-22）
watch(() => props.sel, (sel) => {
  if (!cy || sel?.k !== 'link') return
  const g = props.groups.find((x) => x.id === sel.id)
  const ends = g ? cy.nodes().filter((n) => n.id() === g.a || n.id() === g.b) : null
  if (!ends || ends.empty()) return
  const ext = cy.extent()
  let inView = true
  ends.nodes().forEach((n) => { const q = n.position(); if (q.x < ext.x1 || q.x > ext.x2 || q.y < ext.y1 || q.y > ext.y2) inView = false })
  if (!inView) cy.animate({ fit: { eles: ends, padding: 120 } }, { duration: 220 }) // 两端都在视野里时不动
})
</script>

<template>
  <div class="mapw">
    <div ref="box" class="gview" data-testid="topo-canvas" :data-nodes="nodes.length" :data-links="groups.length" :data-icon-set="iconSet" :data-extra="extra.edges.length" :data-outside="extra.edges.filter((e) => e.kind === 'out').length" />
    <div v-if="tip" class="gtip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }">{{ tip.text }}</div>
  </div>
</template>

<style scoped>
.mapw { flex: 1; min-height: 0; position: relative; background: var(--canvas); background-image: radial-gradient(var(--grid) 1px, transparent 1px); background-size: 20px 20px; }
.gview { position: absolute; inset: 0; }
.gtip { position: absolute; z-index: 5; pointer-events: none; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 4px; padding: 3px 7px; font: 11.5px var(--font-mono); color: var(--ink); box-shadow: var(--shadow-pop); }
</style>
