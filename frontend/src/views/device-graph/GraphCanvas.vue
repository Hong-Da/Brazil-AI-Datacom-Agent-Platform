<script setup lang="ts">
/**
 * 配置图画布：cytoscape 画可见节点，ELK layered 只按包含关系（树）布局，依赖边按曲线叠加。
 * 结构（可见节点 / 边）变化时重新布局并尽量保持锚点节点在屏幕上的位置；只有选中 / 筛选变化时只改样式类。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import elk from 'cytoscape-elk'
import { EDGE_SHORT, type AggEdge, type Model, type VisNode } from './model'
import { canvasLabel, graphStyle, readPalette, textWidth, truncate } from './style'
import { noteText } from '@/i18n/note'

cytoscape.use(elk)

const props = defineProps<{
  model: Model
  vis: VisNode[]
  edges: AggEdge[]
  /** 选中节点在可见图中的代表 */
  selected: string | null
  related: Set<string>
  matches: Set<string>
  /** 搜索中时，不匹配的节点变淡 */
  dimOthers: boolean
  showContains: boolean
  /** 结构变化后保持在屏幕上不动的节点 */
  anchor: string | null
  moreText: (n: number) => string
  edgeName: (kind: string) => string
}>()
const emit = defineEmits<{ (e: 'tap', id: string): void; (e: 'more', parent: string): void; (e: 'background'): void }>()
const { locale } = useI18n()

const box = ref<HTMLDivElement>()
const tip = ref<{ x: number; y: number; text: string } | null>(null)
const layouting = ref(false)
let cy: Core | null = null
let structureKey = ''
let observer: MutationObserver | null = null
let resizer: ResizeObserver | null = null
let firstLayout = true

function fonts(): { mono: string; ui: string } {
  const p = readPalette()
  return { mono: `600 11.5px ${p['font-mono']}`, ui: `600 12.5px ${p['font-ui']}` }
}

function elements(): ElementDefinition[] {
  const f = fonts()
  const out: ElementDefinition[] = []
  for (const v of props.vis) {
    const label = canvasLabel(props.model, v, props.moreText)
    const n = v.more ? null : props.model.nodes.get(v.id)!
    const kind = v.more ? 'more' : n!.kind
    const font = kind === 'device' || kind === 'domain' || kind === 'more' ? f.ui : f.mono
    const w = Math.max(56, Math.min(340, textWidth(label, font) + 22))
    const cls = [`k-${kind}`]
    if (n && n.origin !== 'explicit') cls.push(`s-${n.origin}`)
    if (n && n.hasUnknown && n.kind !== 'unknown' && !v.expanded) cls.push('has-unk')
    out.push({ group: 'nodes', data: { id: v.id, label, w }, classes: cls.join(' ') })
    if (v.parent) out.push({ group: 'edges', data: { id: `c:${v.id}`, source: v.parent, target: v.id }, classes: 'contains' })
  }
  for (const e of props.edges) {
    out.push({
      group: 'edges',
      data: { id: e.id, source: e.source, target: e.target, count: e.count, countLabel: `×${e.count}` },
      classes: EDGE_SHORT[e.kind] ?? 'ref',
    })
  }
  return out
}

function applyClasses(): void {
  if (!cy) return
  const sel = props.selected
  const anySel = !!sel
  cy.batch(() => {
    cy!.nodes().forEach((n) => {
      const id = n.id()
      n.toggleClass('is-sel', id === sel)
      n.toggleClass('is-rel', id !== sel && props.related.has(id))
      n.toggleClass('is-match', props.matches.has(id))
      const k = props.model.nodes.get(id)?.kind
      n.toggleClass('is-dim', props.dimOthers && !props.matches.has(id) && id !== sel && k !== 'device' && k !== 'domain')
    })
    cy!.edges('.contains').toggleClass('off', !props.showContains)
    for (const e of props.edges) {
      const el = cy!.getElementById(e.id)
      el.toggleClass('is-hot', e.hot)
      el.toggleClass('is-dim', anySel && !e.hot)
    }
  })
}

function syncGrid(): void {
  if (!cy || !box.value) return
  const z = cy.zoom()
  const p = cy.pan()
  box.value.style.backgroundSize = `${48 * z}px ${27.7 * z}px`
  box.value.style.backgroundPosition = `${p.x}px ${p.y}px`
}

function initialView(): void {
  if (!cy || !box.value) return
  cy.fit(undefined, 28)
  const z = cy.zoom()
  if (z > 1.1 || z < 0.6) {
    const zoom = Math.min(1.1, Math.max(0.75, z))
    const root = cy.getElementById(props.model.root)
    const bb = cy.elements().boundingBox()
    cy.zoom(zoom)
    const h = box.value.clientHeight
    const ry = root.nonempty() ? root.position('y') : (bb.y1 + bb.y2) / 2
    cy.pan({ x: 28 - bb.x1 * zoom, y: z > 1.1 ? h / 2 - ((bb.y1 + bb.y2) / 2) * zoom : h / 2 - ry * zoom })
  }
}

function rebuild(): void {
  if (!cy) return
  const anchorId = props.anchor
  const before = anchorId && cy.getElementById(anchorId).nonempty() ? cy.getElementById(anchorId).renderedPosition() : null
  cy.elements().remove()
  cy.add(elements())
  applyClasses()
  layouting.value = true
  const lay = cy.elements('node, edge.contains').layout({
    name: 'elk',
    fit: false,
    animate: false,
    nodeDimensionsIncludeLabels: false,
    elk: {
      algorithm: 'layered',
      'elk.direction': 'RIGHT',
      // 连线由 cytoscape 绘制，不用 ELK 的路由结果；默认的正交路由会按连线数加宽层间距，展开上百个子节点时子节点被推到视野外
      'elk.edgeRouting': 'POLYLINE',
      'elk.layered.spacing.nodeNodeBetweenLayers': 44,
      'elk.spacing.nodeNode': 7,
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
      'elk.layered.crossingMinimization.forceNodeModelOrder': true,
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    },
  } as cytoscape.LayoutOptions)
  lay.one('layoutstop', () => {
    layouting.value = false
    if (!cy) return
    const a = anchorId ? cy.getElementById(anchorId) : null
    if (before && a && a.nonempty() && !firstLayout) {
      const z = cy.zoom()
      const pos = a.position()
      cy.pan({ x: before.x - pos.x * z, y: before.y - pos.y * z })
    } else {
      initialView()
      // 带 ?node= 打开时已经选中了节点：首次布局后把它移到视野里，而不是停在根节点（REQ-055-07）
      const s = props.selected ? cy.getElementById(props.selected) : null
      if (s && s.nonempty()) cy.center(s)
    }
    firstLayout = false
    syncGrid()
  })
  lay.run()
}

function refresh(): void {
  const key = props.vis.map((v) => v.id).join('\n') + '\u0000' + props.edges.map((e) => `${e.id}:${e.count}`).join('\n') + '\u0000' + props.vis.map((v) => (v.expanded ? 1 : 0)).join('')
  if (key !== structureKey) {
    structureKey = key
    rebuild()
  } else {
    applyClasses()
  }
}

/** 把节点移到可视范围内（已在范围内时不动）。 */
function focus(id: string): void {
  if (!cy || !box.value) return
  const n = cy.getElementById(id)
  if (n.empty()) return
  const run = () => {
    if (!cy) return
    const rp = n.renderedPosition()
    const w = box.value!.clientWidth
    const h = box.value!.clientHeight
    if (rp.x > 40 && rp.x < w - 40 && rp.y > 30 && rp.y < h - 30) return
    cy.animate({ center: { eles: n } }, { duration: 260 })
  }
  if (layouting.value) cy.one('layoutstop', run)
  else run()
}

function fit(): void {
  if (!cy) return
  cy.animate({ fit: { eles: cy.elements(), padding: 28 } }, { duration: 260 })
}

defineExpose({ focus, fit })

onMounted(() => {
  cy = cytoscape({
    container: box.value,
    style: graphStyle(readPalette()),
    minZoom: 0.12,
    maxZoom: 2.5,
    boxSelectionEnabled: false,
    autounselectify: true,
  })
  // e2e 用：在容器元素上留一个 cytoscape 实例的引用（检查画出的节点）
  ;(box.value as unknown as { __cy?: Core }).__cy = cy
  cy.on('tap', 'node', (ev) => {
    const id = ev.target.id() as string
    if (id.startsWith('more:')) emit('more', id.slice(5))
    else emit('tap', id)
  })
  cy.on('tap', (ev) => { if (ev.target === cy) emit('background') })
  cy.on('viewport', syncGrid)
  cy.on('mouseover', 'node, edge', (ev) => {
    const el = ev.target
    let text = ''
    if (el.isNode()) {
      const n = props.model.nodes.get(el.id())
      if (!n) return
      text = n.kind === 'attr' || n.kind === 'ext' ? `${n.label} = ${n.value}` : n.kind === 'raw' || n.kind === 'unknown' ? n.value : n.label
      if (text === el.data('label')) return
    } else if (!el.hasClass('contains')) {
      const e = props.edges.find((x) => x.id === el.id())
      if (!e) return
      text = `${props.edgeName(e.kind)}${e.count > 1 ? ` ×${e.count}` : ''}${e.notes.length ? ` — ${e.notes.map((x) => noteText(x, String(locale.value))).filter(Boolean).join(' / ')}` : ''}`
    }
    if (!text) return
    const p = ev.renderedPosition ?? el.renderedPosition()
    tip.value = { x: p.x + 12, y: p.y + 14, text: truncate(text, 240) }
  })
  cy.on('mouseout', 'node, edge', () => { tip.value = null })
  cy.on('pan zoom', () => { tip.value = null })
  observer = new MutationObserver(() => { cy?.style(graphStyle(readPalette())) })
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

watch(() => props.model, () => { firstLayout = true; structureKey = '' })
watch(() => [props.vis, props.edges, props.selected, props.related, props.matches, props.dimOthers, props.showContains], refresh)
</script>

<template>
  <div class="gwrap">
    <div ref="box" class="gview canvas" data-testid="graph-canvas" />
    <div v-if="tip" class="gtip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }">{{ tip.text }}</div>
    <div v-if="layouting" class="glayout small faint">{{ $t('c.loading') }}</div>
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
</style>
