<script setup lang="ts">
/** 差异列表：按功能域分组（可折叠），每行显示类型、对象 / 属性、两侧有效值与来源。 */
import { nextTick, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useTerms } from '@/stores/terms'
import { defaultOnly, describe, sideOf, TYPE_SYM, type Group, type Row } from './logic'

const props = defineProps<{
  groups: Group[]
  sel: string | null
  collapsed: Set<string>
  aLabel: string
  bLabel: string
  /** M8-3 变化解读的覆盖核对：行编号 → cov（已归入意图，左侧紫条）/ uncov（没有被解释，黄底） */
  marks?: Record<string, string>
}>()
const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'step', delta: number): void
  (e: 'toggle', domain: string): void
  (e: 'show-na'): void
  (e: 'reset'): void
}>()
const box = ref<HTMLDivElement>()
const terms = useTerms()

function what(r: Row): { o: string; a: string } {
  return describe(r.node, r.dflt ? 'attr' : r.diff?.node_kind ?? 'attr', terms.describeParts)
}
/** 隐藏配置的样式（REQ-028）：默认值灰色虚线、派生值紫色点线 */
function hidClass(origin: string): string {
  return origin === 'default' ? 'hid-default' : origin === 'derived' ? 'hid-derived' : ''
}
function srcLabel(o: string): string {
  return o === 'absent' ? 'compare.src.absent' : `src.${o}`
}

// 选中项变化时只滚动列表，不滚动页面
watch(() => props.sel, async () => {
  await nextTick()
  const list = box.value
  const el = list?.querySelector<HTMLElement>('.drow.is-sel')
  if (!list || !el) return
  const top = el.offsetTop - 34
  const bottom = el.offsetTop + el.offsetHeight
  if (top < list.scrollTop) list.scrollTop = Math.max(0, top)
  else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight
})

function onKey(ev: KeyboardEvent): void {
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
    ev.preventDefault()
    emit('step', ev.key === 'ArrowDown' ? 1 : -1)
    void nextTick(() => box.value?.querySelector<HTMLElement>('.drow.is-sel')?.focus())
  }
}
</script>

<template>
  <div class="dl-cols">
    <span>{{ $t('compare.col.type') }}</span>
    <span>{{ $t('compare.col.what') }}</span>
    <span class="side-k">A <span :title="aLabel">{{ aLabel }}</span></span>
    <span />
    <span class="side-k">B <span :title="bLabel">{{ bLabel }}</span></span>
  </div>
  <div ref="box" class="dlist" data-testid="diff-list" @keydown="onKey">
    <div v-for="g in groups" :key="g.domain" class="dgrp">
      <div class="dgrp-h" role="button" tabindex="0" :aria-expanded="!collapsed.has(g.domain)" @click="emit('toggle', g.domain)" @keydown.enter.prevent="emit('toggle', g.domain)">
        <span class="tw"><Icon :name="collapsed.has(g.domain) ? 'chevR' : 'chevD'" small /></span>
        <span class="dn">{{ g.domain }}</span>
        <span class="cnts">
          <span v-if="g.counts.added" class="c-add">+<b>{{ g.counts.added }}</b></span>
          <span v-if="g.counts.removed" class="c-del">−<b>{{ g.counts.removed }}</b></span>
          <span v-if="g.counts.modified" class="c-mod">~<b>{{ g.counts.modified }}</b></span>
          <span v-if="g.counts.renamed" class="c-ren">⇢<b>{{ g.counts.renamed }}</b></span>
          <span v-if="g.counts.na" class="c-na">≠<b>{{ g.counts.na }}</b></span>
        </span>
      </div>
      <template v-if="!collapsed.has(g.domain)">
        <div
          v-for="r in g.rows" :key="r.id"
          class="drow" :class="['t-' + r.type, { child: r.child, 'is-sel': sel === r.id, 'hid-default': defaultOnly(r), 'cov-ai': props.marks?.[r.id] === 'cov', uncov: props.marks?.[r.id] === 'uncov' }]"
          tabindex="0" :data-id="r.id" data-testid="diff-row"
          @click="emit('select', r.id)" @keydown.enter.prevent="emit('select', r.id)"
        >
          <span><span class="dk" :class="r.type">{{ $t('compare.type.' + r.type) }}</span></span>
          <span class="what">
            <span class="o" :title="`${$t('hid.canonical')}: ${r.node}`">{{ what(r).o }}</span>
            <span v-if="what(r).a || r.diff?.count" class="a">
              {{ what(r).a }}<span v-if="r.diff?.count" class="why-chip">{{ $t('compare.objCount', { n: r.diff.count }) }}</span>
            </span>
          </span>
          <template v-for="s in (['a', 'b'] as const)" :key="s">
            <span>
              <span class="ev" :class="['is-' + sideOf(r, s).origin, hidClass(sideOf(r, s).origin)]">
                <span class="v" :title="sideOf(r, s).text">{{ sideOf(r, s).origin === 'absent' ? $t('compare.absent') : sideOf(r, s).text }}</span>
                <span class="tag" :class="sideOf(r, s).origin === 'absent' ? 'absent' : sideOf(r, s).origin">{{ $t(srcLabel(sideOf(r, s).origin)) }}</span>
              </span>
            </span>
            <span v-if="s === 'a'" class="arr">{{ r.type === 'na' ? TYPE_SYM.na : '→' }}</span>
          </template>
        </div>
        <div v-if="g.folded" class="fold-row">
          <span class="eqk">≠</span>{{ $t('compare.grpFolded', { n: g.folded }) }}
          <button class="link-btn" @click="emit('show-na')">{{ $t('compare.show') }}</button>
        </div>
      </template>
    </div>
    <div v-if="!groups.length" class="empty" data-testid="diff-nomatch">
      <h3>{{ $t('compare.noMatch') }}</h3>
      <button class="btn btn-sm" @click="emit('reset')">{{ $t('compare.clearFilters') }}</button>
    </div>
  </div>
</template>

<style scoped>
.drow.cov-ai { box-shadow: inset 3px 0 0 var(--violet); }
.drow.uncov { background: color-mix(in srgb, var(--amber-soft) 50%, transparent); }
.dl-cols, .drow { display: grid; grid-template-columns: 92px minmax(0, 1.15fr) minmax(0, 1fr) 16px minmax(0, 1fr); gap: 10px; align-items: center; }
.dl-cols { padding: 7px 12px; border-bottom: 1px solid var(--line); background: var(--surface-2); font-size: 12px; font-weight: 600; color: var(--ink-2); }
.dl-cols .side-k { display: inline-flex; gap: 6px; align-items: center; min-width: 0; }
.dl-cols .side-k span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; color: var(--ink-3); }
.dlist { flex: 1; overflow: auto; min-height: 0; }
.dgrp-h { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 1; cursor: pointer; user-select: none; }
.dgrp-h:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.dgrp-h .tw { color: var(--ink-3); display: inline-flex; }
.dgrp-h .dn { font: 600 12.5px var(--font-mono); }
.dgrp-h .cnts { display: inline-flex; gap: 8px; font-size: 11.5px; color: var(--ink-3); margin-left: 4px; }
.dgrp-h .cnts b { font-weight: 600; }
.dgrp-h .cnts .c-add { color: var(--d-add-ink); }
.dgrp-h .cnts .c-del { color: var(--d-del-ink); }
.dgrp-h .cnts .c-mod { color: var(--d-mod-ink); }
.dgrp-h .cnts .c-ren { color: var(--d-ren-ink); }
.dgrp-h .cnts .c-na { color: var(--d-na-ink); }
.drow { padding: 7px 12px; border-bottom: 1px solid var(--line); cursor: pointer; position: relative; min-height: 38px; }
.drow::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bar, transparent); }
.drow.t-added { --bar: var(--d-add); }
.drow.t-removed { --bar: var(--d-del); }
.drow.t-modified { --bar: var(--d-mod); }
.drow.t-renamed { --bar: var(--d-ren); }
.drow.t-na { --bar: var(--d-na); color: var(--ink-2); }
.drow:hover { background: var(--surface-2); }
.drow:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.drow.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.drow.child .what { padding-left: 16px; position: relative; }
.drow.child .what::before { content: ""; position: absolute; left: 4px; top: -4px; width: 7px; height: 12px; border-left: 1px solid var(--line-strong); border-bottom: 1px solid var(--line-strong); }
.what { min-width: 0; }
.what .o { font: 12px var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.what .a { font-size: 11.5px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.arr { color: var(--ink-3); font-size: 12px; text-align: center; }
.fold-row { padding: 6px 12px 6px 114px; border-bottom: 1px solid var(--line); font-size: 12px; color: var(--ink-3); display: flex; gap: 6px; align-items: center; }
.fold-row .eqk { font: 700 12px var(--font-mono); }
.why-chip { font-size: 11px; color: var(--ink-3); border: 1px dashed var(--line-strong); border-radius: 3px; padding: 0 5px; white-space: nowrap; margin-left: 6px; }
.ev.hid-default, .ev.hid-derived { outline-offset: 0; padding: 1px 4px; border-radius: 4px; }
.tag.absent { border-style: dotted; background: transparent; color: var(--ink-3); }
</style>
