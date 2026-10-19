<script setup lang="ts">
/**
 * TCP/IP 模型视图（REQ-034）：六条横带自上而下（应用 → 物理，2.5 层斜纹缩进），每层按对象类型分组列出实例；
 * 作用层与所属对象不同的属性单独成组；橙色细曲线按对象类型汇总跨层依赖，选中对象后画出它自己的跨层连线；
 * 右侧竖条是跨层特性（QoS、时钟同步）。层的归类全部来自后端（layers.nodes）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Model } from '@/views/device-graph/model'
import { formatValue } from '@/views/device-graph/model'
import { bandGroups, chipOf, crossOf, groupLinks, ownerObject, type BandGroup } from './layers'
import { BAND_ORDER, type FeatureInfo, type LayerInfo, type LayersData } from './types'

const props = defineProps<{
  model: Model
  layers: LayersData
  info: { layers: LayerInfo[]; features: FeatureInfo[] }
  selected: string | null
  showDefault: boolean
  labelOf: (id: string) => string
  typeName: (schema: string) => string
  attrName: (schema: string) => string
  pick: (o: Record<string, string> | null | undefined) => string
}>()
const emit = defineEmits<{ (e: 'tap', id: string): void }>()
const { t } = useI18n()

const LIMIT = 12
const open = ref(new Set<string>())
const grid = ref<HTMLDivElement>()
const svg = ref<{ w: number; h: number; agg: { d: string; w: number }[]; hot: { d: string; kind: string }[] }>({ w: 0, h: 0, agg: [], hot: [] })
const rails = ref<{ id: string; top: number; height: number; name: string; desc: string; on: boolean }[]>([])

const layerOf = computed(() => props.layers.nodes)
const groups = computed(() => bandGroups(props.model, layerOf.value, { showDefault: props.showDefault }))
const bands = computed(() => {
  const ids = [...BAND_ORDER]
  if (props.layers.layers.some((r) => r.id === 'unclassified')) ids.push('unclassified')
  return ids.map((id) => {
    const info = props.info.layers.find((x) => x.id === id)
    const row = props.layers.layers.find((r) => r.id === id)
    return { id, name: info ? props.pick(info.name) : t('device-analysis.unclassified'), desc: info ? props.pick(info.desc) : '', row, groups: groups.value.get(id) ?? [] }
  })
})
const selObj = computed(() => ownerObject(props.model, props.selected))
const selChip = computed(() => (props.selected ? chipOf(props.model, layerOf.value, props.selected) : null))
const mine = computed(() => crossOf(props.layers.cross, selObj.value))
const relChips = computed(() => {
  const out = new Set<string>()
  for (const x of mine.value) {
    const c = chipOf(props.model, layerOf.value, x.other)
    if (c) out.add(c)
  }
  return out
})
const featOfSel = computed(() => (props.selected ? props.layers.features_of[props.selected] ?? (selObj.value ? props.layers.features_of[selObj.value] : undefined) : undefined))

function groupTitle(g: BandGroup): string {
  return g.attr ? `${g.ownerSchema ? props.typeName(g.ownerSchema) : ''} · ${props.attrName(g.schema)}` : props.typeName(g.schema)
}
function chipText(id: string): string {
  const n = props.model.nodes.get(id)
  if (!n) return id
  if (n.kind === 'attr') {
    const own = ownerObject(props.model, id)
    return `${own ? props.labelOf(own) : ''} · ${formatValue(n.api?.value)}`
  }
  return props.labelOf(id)
}
function shown(g: BandGroup): string[] {
  if (open.value.has(g.key)) return g.items
  const first = g.items.slice(0, LIMIT)
  // 选中或相关的格子即使在折叠部分也显示出来
  const extra = g.items.slice(LIMIT).filter((id) => id === selChip.value || relChips.value.has(id))
  return [...first, ...extra]
}
function toggle(key: string): void {
  const s = new Set(open.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  open.value = s
}
function featName(id: string | undefined): string {
  const f = props.info.features.find((x) => x.id === id)
  return f ? props.pick(f.name) : ''
}

// ---------- 连线与竖条（按渲染后的位置画） ----------
function esc(s: string): string {
  return typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(s) : s.replace(/["\\]/g, '\\$&')
}
function draw(): void {
  const g = grid.value
  if (!g) return
  const gr = g.getBoundingClientRect()
  const pt = (el: Element) => {
    const r = el.getBoundingClientRect()
    return { x: r.left - gr.left + r.width / 2, y: r.top - gr.top + r.height / 2, t: r.top - gr.top, b: r.bottom - gr.top }
  }
  const curve = (a: ReturnType<typeof pt>, b: ReturnType<typeof pt>) => {
    const up = b.y < a.y
    const y1 = up ? a.t : a.b
    const y2 = up ? b.b : b.t
    const dy = (y2 - y1) / 2
    return `M${a.x.toFixed(1)} ${y1.toFixed(1)} C${a.x.toFixed(1)} ${(y1 + dy).toFixed(1)} ${b.x.toFixed(1)} ${(y2 - dy).toFixed(1)} ${b.x.toFixed(1)} ${y2.toFixed(1)}`
  }
  const head = (key: string) => g.querySelector(`[data-grp="${esc(key)}"] .grp-h`)
  const agg: { d: string; w: number }[] = []
  for (const l of groupLinks(props.model, layerOf.value, props.layers.cross)) {
    const a = head(l.a)
    const b = head(l.b)
    if (a && b) agg.push({ d: curve(pt(a), pt(b)), w: Math.min(4, 1 + Math.log2(l.count)) })
  }
  const hot: { d: string; kind: string }[] = []
  const anchorOf = (id: string): Element | null => {
    const c = chipOf(props.model, layerOf.value, id)
    return (c && g.querySelector(`[data-chip="${esc(c)}"]`)) || null
  }
  for (const x of mine.value) {
    const a = anchorOf(x.edge.from)
    const b = anchorOf(x.edge.to)
    if (a && b && a !== b) hot.push({ d: curve(pt(a), pt(b)), kind: x.edge.kind })
  }
  svg.value = { w: gr.width, h: gr.height, agg, hot }
  const out: typeof rails.value = []
  for (const f of props.info.features) {
    const tops: number[] = []
    const bots: number[] = []
    for (const ly of f.span) {
      const el = g.querySelector(`[data-band="${ly}"]`)
      if (!el) continue
      const r = el.getBoundingClientRect()
      tops.push(r.top - gr.top)
      bots.push(r.bottom - gr.top)
    }
    if (!tops.length) continue
    const top = Math.min(...tops)
    out.push({ id: f.id, top, height: Math.max(...bots) - top - 6, name: props.pick(f.name), desc: props.pick(f.desc), on: featOfSel.value === f.id })
  }
  rails.value = out
}
let raf = 0
function schedule(): void {
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(() => nextTick(draw))
}
/** 外部选中：滚到对应的格子。 */
function focus(): void {
  nextTick(() => {
    const c = selChip.value
    const el = c && grid.value?.querySelector(`[data-chip="${esc(c)}"]`)
    if (el) (el as HTMLElement).scrollIntoView({ block: 'nearest', inline: 'nearest' })
    schedule()
  })
}
defineExpose({ focus })

let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(schedule)
  if (grid.value) ro.observe(grid.value)
  focus()
})
onBeforeUnmount(() => { ro?.disconnect(); cancelAnimationFrame(raf) })
watch(() => [props.selected, props.showDefault, open.value, props.layers, props.labelOf], schedule)
</script>

<template>
  <div class="tcp" data-testid="tcpip-view">
    <div ref="grid" class="tcp-grid">
      <div class="bands">
        <section v-for="b in bands" :key="b.id" class="band" :class="{ mpls: b.id === 'mpls' }" :data-ly="b.id" :data-band="b.id">
          <div class="band-h">
            <b>{{ b.name }}</b>
            <span class="d">{{ b.desc }}</span>
            <span class="c">{{ $t('device-analysis.bandCount', { o: b.row?.objects ?? 0, a: b.row?.attrs ?? 0 }) }}</span>
          </div>
          <div class="band-b">
            <span v-if="!b.groups.length" class="small faint">{{ $t('device-analysis.bandEmpty') }}</span>
            <div v-for="g in b.groups" :key="g.key" class="grp" :class="{ attr: g.attr }" :data-grp="g.key">
              <button type="button" class="grp-h" :aria-expanded="open.has(g.key)" @click="toggle(g.key)">
                <b>{{ groupTitle(g) }}</b><span>{{ g.items.length }}</span>
                <span v-if="layers.features_of[g.items[0]]" class="tag ft">{{ featName(layers.features_of[g.items[0]]) }}</span>
              </button>
              <div class="chips">
                <button
                  v-for="id in shown(g)" :key="id" type="button" class="chip-o"
                  :class="{ 'is-sel': id === selChip, 'is-rel': relChips.has(id), 's-derived': model.nodes.get(id)?.origin === 'derived', 's-default': model.nodes.get(id)?.origin === 'default' }"
                  :data-chip="id" :title="id" data-testid="tcp-chip" @click="emit('tap', id)"
                >{{ chipText(id) }}</button>
                <button v-if="g.items.length > LIMIT" type="button" class="chip-more" @click="toggle(g.key)">{{ open.has(g.key) ? $t('device-analysis.less') : `+${g.items.length - shown(g).length}` }}</button>
              </div>
            </div>
          </div>
        </section>
      </div>
      <div class="rails">
        <div v-for="r in rails" :key="r.id" class="rail" :class="[r.id, { 'is-on': r.on }]" :style="{ top: `${r.top}px`, height: `${r.height}px` }" :title="r.desc"><span>{{ r.name }}</span></div>
      </div>
      <svg class="xsvg" :width="svg.w" :height="svg.h" aria-hidden="true">
        <defs><marker id="xarr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L8 4L0 8z" /></marker></defs>
        <path v-for="(p, i) in svg.agg" :key="`a${i}`" class="agg" :d="p.d" :style="{ strokeWidth: p.w }" />
        <path v-for="(p, i) in svg.hot" :key="`h${i}`" class="hot" :d="p.d" marker-end="url(#xarr)" />
      </svg>
    </div>
  </div>
</template>

<style scoped>
.tcp { flex: 1; min-height: 0; overflow: auto; padding: 10px 12px 14px; }
.tcp-grid { display: grid; grid-template-columns: minmax(0, 1fr) 54px; gap: 0 10px; position: relative; }
.band { display: grid; grid-template-columns: 150px minmax(0, 1fr); border: 1px solid var(--line); border-left: 4px solid var(--c); border-radius: 6px; background: var(--surface); margin-bottom: 6px; min-height: 58px; }
.band.mpls { border-left-style: dashed; background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--c) 8%, var(--surface)) 0 6px, var(--surface) 6px 12px); margin-left: 22px; }
.band-h { padding: 8px 10px; border-right: 1px solid var(--line); display: flex; flex-direction: column; gap: 3px; }
.band-h b { font-size: 13px; }
.band-h .d { font-size: 11px; color: var(--ink-3); line-height: 1.35; }
.band-h .c { font-size: 11px; color: var(--ink-2); }
.band-b { padding: 8px; display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start; min-width: 0; }
.grp { border: 1px solid var(--line); border-radius: 5px; background: var(--surface-2); padding: 4px 6px; display: flex; flex-direction: column; gap: 4px; min-width: 120px; max-width: 100%; }
.grp.attr { border-style: dashed; }
.grp-h { all: unset; display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-2); cursor: pointer; }
.grp-h:focus-visible { outline: 2px solid var(--focus); border-radius: 3px; }
.grp-h b { color: var(--ink); font-weight: 600; }
.grp-h .ft { margin-left: auto; }
.chips { display: flex; flex-wrap: wrap; gap: 3px; }
.chip-o { all: unset; box-sizing: border-box; font: 11px/18px var(--font-mono); padding: 0 6px; border-radius: 3px; background: var(--surface); border: 1px solid var(--line); cursor: pointer; white-space: nowrap; max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: var(--ink); }
.chip-o:hover { border-color: var(--line-strong); }
.chip-o:focus-visible { outline: 2px solid var(--focus); }
.chip-o.is-sel { background: var(--amber-soft); border-color: var(--amber); font-weight: 600; }
.chip-o.is-rel { border-color: var(--e-cross); box-shadow: 0 0 0 1px var(--e-cross) inset; }
.chip-o.s-derived { outline: 1.2px dotted var(--violet); outline-offset: -2px; }
.chip-o.s-default { outline: 1.2px dashed var(--ink-3); outline-offset: -2px; color: var(--ink-2); }
.chip-more { all: unset; font-size: 11px; color: var(--blue-ink); cursor: pointer; padding: 0 4px; }
.rails { position: relative; }
.rail { position: absolute; width: 22px; border-radius: 11px; border: 1px solid var(--line-strong); background: var(--surface-2); display: flex; align-items: flex-end; justify-content: center; padding-bottom: 8px; }
.rail span { writing-mode: vertical-rl; transform: rotate(180deg); font-size: 11px; color: var(--ink-2); white-space: nowrap; }
.rail.qos { left: 2px; }
.rail.clock { left: 28px; }
.rail.is-on { border-color: var(--amber); background: var(--amber-soft); }
.rail.is-on span { color: var(--amber-ink); font-weight: 600; }
.xsvg { position: absolute; left: 0; top: 0; pointer-events: none; overflow: visible; }
.xsvg path { fill: none; stroke: var(--e-cross); }
.xsvg path.agg { stroke-width: 1.2; opacity: .26; }
.xsvg path.hot { stroke-width: 2; opacity: 1; }
.xsvg marker path { fill: var(--e-cross); stroke: none; }
@media (max-width: 900px) { .band { grid-template-columns: 1fr; } .band-h { border-right: 0; border-bottom: 1px solid var(--line); } }
</style>
