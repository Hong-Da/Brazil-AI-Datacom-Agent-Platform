<script setup lang="ts">
/**
 * 版本历史的时间轴（预览 history.html 的 SVG 时间轴）：点的大小 = 相对上一快照的对象变化数，柱 = 新增 / 修改 / 删除 / 仅格式，
 * ×N = 内容相同的重复导入，旗标 = 标签。单击点设为 B（早于 A 时设为 A），Shift 单击设为 A，也可以拖动 A / B 标记。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { fmtTime, objChanges, pickPoint, timelineX, type Snapshot } from './history'

const props = defineProps<{ snaps: Snapshot[]; a: number; b: number; single: boolean }>()
const emit = defineEmits<{ (e: 'pick', a: number, b: number): void }>()
const { t } = useI18n()

const wrap = ref<HTMLDivElement>()
const svg = ref<SVGSVGElement>()
const W = ref(900)
const H = 178
const AY = 96
let ro: ResizeObserver | null = null
onMounted(() => {
  const upd = () => { W.value = Math.max(420, (wrap.value?.clientWidth ?? 900) - 12) }
  upd()
  if (typeof ResizeObserver !== 'undefined' && wrap.value) { ro = new ResizeObserver(upd); ro.observe(wrap.value) }
})
onBeforeUnmount(() => ro?.disconnect())

const xs = computed(() => timelineX(props.snaps.map((s) => Date.parse(s.collected_at) || 0), 58, W.value - 58))
const pts = computed(() => props.snaps.map((s, i) => {
  const c = s.vs_previous
  const tot = objChanges(c)
  const r = c ? Math.min(12, 5 + tot * 1.1) : 6
  const bars: { cls: string; y: number; h: number }[] = []
  if (c) {
    const total = c.added + c.modified + c.renamed + c.removed + c.fmt
    const scale = total > 0 ? Math.min(6, 50 / total) : 6
    let y = AY + 16
    for (const [cls, n] of [['add', c.added], ['mod', c.modified + c.renamed], ['del', c.removed], ['fmt', c.fmt]] as [string, number][]) {
      if (!n) continue
      bars.push({ cls, y, h: n * scale })
      y += n * scale
    }
  }
  return { s, i, x: xs.value[i], r, bars, tot }
}))
/** 日期标签相互太近时上下错开两行。 */
const labelRow = computed(() => {
  const rows: number[] = []
  let last = -999
  let row = 0
  for (const p of pts.value) {
    row = p.x - last < 64 ? (row ? 0 : 1) : 0
    rows.push(row)
    last = p.x
  }
  return rows
})
const flagText = (p: { s: Snapshot; i: number; x: number }) => {
  const tag = p.s.tag ?? ''
  const next = xs.value[p.i + 1] ?? W.value
  const cw = /[一-鿿]/.test(tag) ? 11.5 : 6.4
  const max = Math.max(3, Math.floor((next - p.x - 22) / cw))
  return { text: tag.length > max ? `${tag.slice(0, max - 1)}…` : tag, w: Math.min(tag.length, max) * cw + 12 }
}
const tip = (p: { s: Snapshot; tot: number }) => {
  const im = p.s.imports[0]
  const c = p.s.vs_previous
  return `#${p.s.seq} · ${fmtTime(p.s.collected_at)} · ${t(`history.src.${im?.source_kind ?? 'file'}`)} · ${im?.actor ?? ''}${c ? ` · +${c.added} ~${c.modified + c.renamed} −${c.removed}` : ''}`
}

// ---------------------------------------------------------------- 点击与拖动
const drag = ref<'a' | 'b' | null>(null)
const dragAt = ref<number | null>(null)
function nearest(clientX: number): number {
  const el = svg.value
  if (!el) return 0
  const rect = el.getBoundingClientRect()
  const x = ((clientX - rect.left) / rect.width) * W.value
  let best = 0
  let bd = Infinity
  xs.value.forEach((tx, k) => { const d = Math.abs(tx - x); if (d < bd) { bd = d; best = k } })
  return best
}
function down(ev: PointerEvent): void {
  if (props.single) return
  const target = ev.target as Element
  const mk = target.closest('[data-mk]')
  if (mk) {
    drag.value = mk.getAttribute('data-mk') as 'a' | 'b'
    dragAt.value = drag.value === 'a' ? props.a : props.b
    svg.value?.setPointerCapture?.(ev.pointerId)
    ev.preventDefault()
    return
  }
  const p = target.closest('[data-i]')
  if (!p) return
  const [a, b] = pickPoint(Number(p.getAttribute('data-i')), props.a, props.b, ev.shiftKey)
  if (a !== props.a || b !== props.b) emit('pick', a, b)
}
function move(ev: PointerEvent): void {
  if (!drag.value) return
  const i = nearest(ev.clientX)
  if (drag.value === 'a' && i < props.b) dragAt.value = i
  if (drag.value === 'b' && i > props.a) dragAt.value = i
}
function up(): void {
  if (!drag.value) return
  const which = drag.value
  const at = dragAt.value
  drag.value = null
  dragAt.value = null
  if (at === null) return
  if (which === 'a' && at !== props.a) emit('pick', at, props.b)
  if (which === 'b' && at !== props.b) emit('pick', props.a, at)
}
const ia = computed(() => (drag.value === 'a' && dragAt.value !== null ? dragAt.value : props.a))
const ib = computed(() => (drag.value === 'b' && dragAt.value !== null ? dragAt.value : props.b))
</script>

<template>
  <div ref="wrap" class="tlwrap">
    <svg ref="svg" :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="$t('history.tlAria')" data-testid="hist-timeline" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up">
      <line class="tl-axis" :x1="20" :y1="AY" :x2="W - 20" :y2="AY" />
      <rect v-if="!single && snaps.length > 1" class="tl-band" :x="xs[ia]" y="52" :width="Math.max(0, xs[ib] - xs[ia])" :height="H - 70" />
      <template v-for="p in pts" :key="p.s.id">
        <g v-if="p.s.tag" class="tl-flag">
          <title>{{ p.s.tag }}</title>
          <line :x1="p.x" y1="30" :x2="p.x" :y2="AY - p.r" />
          <rect :x="p.x - 4" y="10" :width="flagText(p).w" height="17" rx="3" />
          <text :x="p.x + 2" y="22.5">{{ flagText(p).text }}</text>
        </g>
        <g class="tl-pt" :class="{ 'is-a': !single && p.i === ia, 'is-b': !single && p.i === ib, in: !single && p.i > ia && p.i < ib }" :data-i="p.i" :data-testid="`hist-pt-${p.s.seq}`">
          <title>{{ tip(p) }}</title>
          <rect :x="p.x - 14" :y="AY - 16" width="28" height="80" fill="transparent" />
          <circle class="p" :cx="p.x" :cy="AY" :r="p.r" />
          <template v-if="p.s.import_count > 1">
            <rect class="dupbg" :x="p.x + p.r - 2" :y="AY - p.r - 12" width="20" height="13" rx="6.5" />
            <text class="dup" :x="p.x + p.r + 8" :y="AY - p.r - 2.5" text-anchor="middle">×{{ p.s.import_count }}</text>
          </template>
          <rect v-for="(bar, k) in p.bars" :key="k" class="tl-bar" :class="bar.cls" :x="p.x - 5" :y="bar.y" width="10" :height="bar.h" />
          <text class="d" :x="p.x" :y="H - 22 + labelRow[p.i] * 12">#{{ p.s.seq }} {{ fmtTime(p.s.collected_at).slice(5, 16) }}</text>
        </g>
      </template>
      <template v-if="!single && snaps.length > 1">
        <g v-for="m in (['a', 'b'] as const)" :key="m" class="tl-mk" :class="m" :data-mk="m" :data-testid="`hist-mk-${m}`">
          <line :x1="xs[m === 'a' ? ia : ib]" y1="56" :x2="xs[m === 'a' ? ia : ib]" :y2="AY - 6" />
          <circle :cx="xs[m === 'a' ? ia : ib]" cy="48" r="10" />
          <text :x="xs[m === 'a' ? ia : ib]" y="52">{{ m.toUpperCase() }}</text>
        </g>
      </template>
    </svg>
  </div>
</template>

<style scoped>
.tlwrap { position: relative; padding: 0 6px; }
.tlwrap svg { width: 100%; height: 178px; user-select: none; touch-action: none; display: block; }
.tl-axis { stroke: var(--line-strong); stroke-width: 1.5; }
.tl-band { fill: color-mix(in srgb, var(--vb) 12%, transparent); stroke: none; }
.tl-pt { cursor: pointer; }
.tl-pt circle.p { fill: var(--surface); stroke: var(--ink-3); stroke-width: 1.8; }
.tl-pt:hover circle.p { stroke: var(--blue); }
.tl-pt.in circle.p { stroke: var(--ink-2); }
.tl-pt.is-a circle.p { stroke: var(--va); stroke-width: 3; }
.tl-pt.is-b circle.p { fill: var(--vb); stroke: var(--vb); }
.tl-pt text.d { font: 10.5px var(--font-mono); fill: var(--ink-2); text-anchor: middle; }
.tl-pt.is-a text.d, .tl-pt.is-b text.d { fill: var(--ink); font-weight: 700; }
.tl-pt text.dup { font: 700 9.5px var(--font-ui); fill: var(--ink-2); }
.tl-pt rect.dupbg { fill: var(--surface-3); stroke: var(--line-strong); }
.tl-bar.add { fill: var(--d-add); }
.tl-bar.mod { fill: var(--d-mod); }
.tl-bar.del { fill: var(--d-del); }
.tl-bar.fmt { fill: var(--line-strong); }
.tl-flag text { font: 600 10.5px var(--font-ui); fill: var(--teal-ink); }
.tl-flag rect { fill: var(--teal-soft); stroke: var(--teal-line); }
.tl-flag line { stroke: var(--teal-line); stroke-dasharray: 2 2; }
.tl-mk { cursor: grab; }
.tl-mk:active { cursor: grabbing; }
.tl-mk line { stroke-width: 1.5; }
.tl-mk.a line { stroke: var(--va); }
.tl-mk.b line { stroke: var(--vb); }
.tl-mk.a circle { fill: var(--surface); stroke: var(--va); stroke-width: 2.2; }
.tl-mk.b circle { fill: var(--vb); stroke: var(--vb); stroke-width: 2.2; }
.tl-mk text { font: 700 11px var(--font-ui); text-anchor: middle; }
.tl-mk.a text { fill: var(--va); }
.tl-mk.b text { fill: #3A2600; }
</style>
