<script setup lang="ts">
/** 差异图：设备 → 功能域 → 对象 → 属性的叠加树（SVG），引用关系画成右侧弧线；A / B / 叠加切换，节点可收起。 */
import { computed } from 'vue'
import { layoutTree, type GSide, type LNode, type NodeState, type Tree } from './tree'

const props = defineProps<{
  tree: Tree
  sel: string | null
  side: GSide
  only: 'diff' | 'all'
  collapsed: Set<string>
  note: string
  big: boolean
}>()
const emit = defineEmits<{
  (e: 'select', rowId: string): void
  (e: 'toggle', key: string): void
  (e: 'update:side', v: GSide): void
  (e: 'update:only', v: 'diff' | 'all'): void
  (e: 'expand-all'): void
  (e: 'collapse-all'): void
}>()

const CW = 7
const lay = computed(() => layoutTree(props.tree, { side: props.side, collapsed: props.collapsed, charW: CW }))
const SYM: Partial<Record<NodeState, string>> = { add: '+', del: '−', mod: '~', ren: '⇢', na: '≠', ref: '↺' }
const legend: [NodeState, string][] = [
  ['add', 'compare.type.added'], ['del', 'compare.type.removed'], ['mod', 'compare.type.modified'], ['ren', 'compare.type.renamed'],
  ['na', 'compare.type.na'], ['ref', 'compare.graph.follow'], ['same', 'compare.graph.unchanged'],
]

function sym(n: LNode): string {
  return n.depth > 1 ? SYM[n.state] ?? '' : ''
}
function text(n: LNode): string {
  const room = n.w - (sym(n) ? 20 : 9) - (n.collapsed ? 5 * CW : 0) - 8
  const max = Math.max(2, Math.floor(room / CW))
  return n.label.length > max ? n.label.slice(0, max - 1) + '…' : n.label
}
function click(n: LNode): void {
  if (n.rowId) emit('select', n.rowId)
  else if (n.hasKids && n.depth > 0) emit('toggle', n.key)
}
function key(ev: KeyboardEvent, n: LNode): void {
  if (ev.key === 'Enter' || ev.key === ' ') {
    ev.preventDefault()
    click(n)
  }
}
</script>

<template>
  <div class="gbar">
    <div class="seg" role="group" data-testid="graph-side">
      <button type="button" :aria-pressed="side === 'both'" @click="emit('update:side', 'both')">{{ $t('compare.graph.overlay') }}</button>
      <button type="button" :aria-pressed="side === 'a'" @click="emit('update:side', 'a')">{{ $t('compare.graph.a') }}</button>
      <button type="button" :aria-pressed="side === 'b'" @click="emit('update:side', 'b')">{{ $t('compare.graph.b') }}</button>
    </div>
    <div class="seg" role="group" data-testid="graph-only">
      <button type="button" :aria-pressed="only === 'diff'" @click="emit('update:only', 'diff')">{{ $t('compare.graph.onlyDiff') }}</button>
      <button type="button" :aria-pressed="only === 'all'" @click="emit('update:only', 'all')">{{ $t('compare.graph.all') }}</button>
    </div>
    <button class="btn btn-ghost btn-sm" @click="emit('expand-all')">{{ $t('compare.graph.expandAll') }}</button>
    <button class="btn btn-ghost btn-sm" @click="emit('collapse-all')">{{ $t('compare.graph.collapseAll') }}</button>
    <span class="faint hint">{{ side === 'a' ? $t('compare.graph.hintA') : side === 'b' ? $t('compare.graph.hintB') : $t('compare.graph.hintBoth') }}</span>
  </div>
  <div v-if="note || big" class="gnote small">{{ note || $t('compare.graph.big') }}</div>
  <div class="gview canvas" data-testid="diff-graph">
    <svg :width="lay.width" :height="lay.height" :viewBox="`0 0 ${lay.width} ${lay.height}`" role="img" aria-label="Diff graph">
      <defs>
        <marker v-for="k in ['ref', 'add', 'del', 'ren']" :id="'cmp-m-' + k" :key="k" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path :class="'mk-' + k" d="M0 0L8 4L0 8z" />
        </marker>
      </defs>
      <path v-for="(d, i) in lay.links" :key="'l' + i" class="gl-tree" :d="d" />
      <path v-for="(r, i) in lay.refs" :key="'r' + i" class="gl-ref" :class="'st-' + r.state" :d="r.d" :marker-end="`url(#cmp-m-${r.state})`" />
      <g
        v-for="n in lay.nodes" :key="n.key"
        class="dn" :class="['lv' + Math.min(n.depth, 2), 'st-' + n.state, { 'is-sel': n.rowId && n.rowId === sel }]"
        :transform="`translate(${n.x},${n.y - 11})`" tabindex="0" :data-key="n.key"
        @click="click(n)" @keydown="key($event, n)"
      >
        <title>{{ n.label }}</title>
        <rect :width="n.w" height="22" rx="4" />
        <text v-if="sym(n)" class="sym" x="8" y="15">{{ sym(n) }}</text>
        <text :x="sym(n) ? 20 : 9" y="15">{{ text(n) }}</text>
        <g v-if="n.hasKids && n.depth > 0" class="tg" :transform="`translate(${n.w - 4},11)`" @click.stop="emit('toggle', n.key)">
          <title>{{ $t('compare.graph.toggle') }}</title>
          <circle r="7" />
          <text x="0" y="3.5" text-anchor="middle">{{ n.collapsed ? '+' : '−' }}</text>
        </g>
        <text v-if="n.collapsed" class="hid" :x="n.w - 16" y="15" text-anchor="end">+{{ n.hidden }}</text>
      </g>
    </svg>
  </div>
  <div class="glegend">
    <span v-for="[st, k] in legend" :key="st" class="nk">
      <svg viewBox="0 0 22 12"><rect class="lg" :class="'st-' + st" x="1" y="1" width="20" height="10" rx="2" /></svg>{{ $t(k) }}
    </span>
    <span class="nk"><svg viewBox="0 0 22 12"><path d="M1 6h17" class="gl-ref st-ref" /><path d="M16 3l4 3-4 3z" class="mk-ref" /></svg>{{ $t('e.ref') }}</span>
    <span class="ml-auto faint">{{ $t('compare.graph.count', { n: lay.nodes.length, e: lay.refs.length }) }}</span>
  </div>
</template>

<style scoped>
.gbar { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; font-size: 12px; color: var(--ink-2); }
.gbar .hint { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
.gnote { padding: 6px 12px; color: var(--ink-2); background: var(--surface-2); border-bottom: 1px dashed var(--line-strong); }
.gview { flex: 1; overflow: auto; min-height: 0; }
.glegend { display: flex; gap: 6px 14px; padding: 7px 12px; border-top: 1px solid var(--line); flex-wrap: wrap; align-items: center; font-size: 11.5px; color: var(--ink-2); }
.glegend .nk { display: inline-flex; gap: 5px; align-items: center; }
.glegend svg { width: 22px; height: 12px; }
.lg, .dn rect { stroke-width: 1.3; }
.dn text { font: 11.5px var(--font-mono); fill: var(--ink); }
.dn.lv0 text, .dn.lv1 text { font-family: var(--font-ui); font-weight: 600; }
.st-same.lg, .dn.st-same rect { fill: var(--surface); stroke: var(--line-strong); }
.dn.st-same text { fill: var(--ink-2); }
.st-ref.lg, .dn.st-ref rect { fill: var(--canvas); stroke: var(--ink-3); stroke-dasharray: 4 3; }
.dn.st-ref text { fill: var(--ink-2); }
.st-add.lg, .dn.st-add rect { fill: var(--d-add-soft); stroke: var(--d-add); }
.dn.st-add text { fill: var(--d-add-ink); }
.st-del.lg, .dn.st-del rect { fill: var(--d-del-soft); stroke: var(--d-del); stroke-dasharray: 5 3; }
.dn.st-del text { fill: var(--d-del-ink); }
.st-mod.lg, .dn.st-mod rect { fill: var(--d-mod-soft); stroke: var(--d-mod); }
.dn.st-mod text { fill: var(--d-mod-ink); }
.st-ren.lg, .dn.st-ren rect { fill: var(--d-ren-soft); stroke: var(--d-ren); }
.dn.st-ren text { fill: var(--d-ren-ink); }
.st-na.lg, .dn.st-na rect { fill: var(--d-na-soft); stroke: var(--d-na); stroke-dasharray: 1.5 2.5; }
.dn.st-na text { fill: var(--ink-3); }
.dn.lv0 rect { fill: var(--blue); stroke: var(--blue); }
.dn.lv0 text { fill: var(--surface); }
.dn.lv1.st-mod rect, .dn.lv1.st-same rect { fill: var(--teal-soft); stroke: var(--teal-line); }
.dn.lv1 text { fill: var(--teal-ink); }
.dn .sym { font: 700 11px var(--font-mono); }
.dn { cursor: pointer; outline: none; }
.dn:hover > rect { stroke-width: 2; }
.dn:focus-visible > rect { stroke: var(--focus); stroke-width: 2.4; }
.dn.is-sel > rect { stroke: var(--sel-ring); stroke-width: 2.4; }
.dn .tg circle { fill: var(--surface); stroke: var(--line-strong); }
.dn .tg text { font: 700 11px var(--font-mono); fill: var(--ink-2); }
.dn .tg:hover circle { stroke: var(--blue); }
.dn .hid { font: 10.5px var(--font-ui); fill: var(--ink-3); }
.gl-tree { fill: none; stroke: var(--line-strong); stroke-width: 1.1; }
.gl-ref { fill: none; stroke-width: 1.6; }
.gl-ref.st-ref { stroke: var(--e-ref); opacity: .7; }
.gl-ref.st-add { stroke: var(--d-add); }
.gl-ref.st-del { stroke: var(--d-del); stroke-dasharray: 5 3; }
.gl-ref.st-ren { stroke: var(--d-ren); stroke-dasharray: 6 3; }
.mk-ref { fill: var(--e-ref); }
.mk-add { fill: var(--d-add); }
.mk-del { fill: var(--d-del); }
.mk-ren { fill: var(--d-ren); }
</style>
