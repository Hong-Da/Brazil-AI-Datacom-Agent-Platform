<script setup lang="ts">
/**
 * 结构化脚本（REQ-034）：配置原文按视图块折叠，行号；关键字 / 参数 / 引用分色，点引用跳到定义；
 * 原文行 R、未识别行 ?、隐藏的默认值行（REQ-028 样式，可开关）分别标出；行首色条是所在层。
 * 只渲染滚动窗口内的行（虚拟滚动），现网约 2300 行的配置也流畅。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { formatValue } from '@/views/device-graph/model'
import {
  descendantCount, foldAll as foldAllOf, revealLine, rowIndex, segments, visibleRows, windowOf, type Row, type ScriptIndex,
} from './script'
import type { ScriptData, ScriptLine } from './types'

const ROW = 20

const props = defineProps<{
  script: ScriptData
  ix: ScriptIndex
  domain: string
  showDefaults: boolean
  /** 选中节点自身的行 */
  hl: Set<number>
  /** 选中对象子树的行（淡一些） */
  sub: Set<number>
  /** 选中的默认值节点 */
  selNode: string | null
  /** 节点名（引用的悬停提示） */
  labelOf: (id: string) => string
}>()
const emit = defineEmits<{
  (e: 'pick', line: number): void
  (e: 'pickNode', node: string): void
  (e: 'ref', target: string, line: number): void
}>()

const fold = ref(new Set<number>())
const box = ref<HTMLDivElement>()
const scrollTop = ref(0)
const height = ref(600)
const flash = ref<number | null>(null)

const rows = computed<Row[]>(() => visibleRows(props.script, props.ix, { fold: fold.value, domain: props.domain, showDefaults: props.showDefaults }))
const win = computed(() => windowOf(scrollTop.value, height.value, ROW, rows.value.length))
const slice = computed(() => rows.value.slice(win.value[0], win.value[1]).map((r, i) => ({ r, i: win.value[0] + i })))

function line(no: number): ScriptLine {
  return props.ix.byNo.get(no)!
}
function cls(no: number): string[] {
  const l = line(no)
  const c = ['r']
  if (l.kind === 'separator' || l.kind === 'end' || l.kind === 'comment' || l.kind === 'blank') c.push('c-sep')
  else if (l.kind === 'raw') c.push('raw')
  else if (l.kind === 'unknown') c.push('unknown')
  if (props.hl.has(no)) c.push('is-hl')
  else if (props.sub.has(no)) c.push('is-sub')
  if (flash.value === no) c.push('is-flash')
  return c
}
function defText(r: Extract<Row, { type: 'def' }>): string {
  const d = r.d
  return ' '.repeat(d.depth) + (d.text ?? `${d.schema.split('.').pop()} ${formatValue(d.value)}`)
}

function onScroll(): void {
  scrollTop.value = box.value?.scrollTop ?? 0
}
function toggle(no: number): void {
  const s = new Set(fold.value)
  if (s.has(no)) s.delete(no)
  else s.add(no)
  fold.value = s
}
function onClick(ev: MouseEvent): void {
  const t = ev.target as HTMLElement
  const f = t.closest<HTMLElement>('[data-fold]')
  if (f) {
    toggle(Number(f.dataset.fold))
    return
  }
  const rf = t.closest<HTMLElement>('[data-ref]')
  const row = t.closest<HTMLElement>('[data-row]')
  if (rf && row) {
    emit('ref', rf.dataset.ref!, Number(row.dataset.ln))
    return
  }
  if (!row) return
  if (row.dataset.def) emit('pickNode', row.dataset.def)
  else emit('pick', Number(row.dataset.ln))
}

/** 滚到某行（先展开它的上级、离开筛选范围时由调用方清空筛选）；force 时总是滚到上方三分之一。 */
function scrollToLine(no: number, opt: { force?: boolean; flash?: boolean } = {}): void {
  fold.value = revealLine(props.ix, no, fold.value)
  nextTick(() => {
    const i = rowIndex(rows.value, { line: no })
    if (i < 0 || !box.value) return
    const top = i * ROW
    const v = box.value
    if (opt.force || top < v.scrollTop || top + ROW > v.scrollTop + v.clientHeight) v.scrollTop = Math.max(0, top - v.clientHeight / 3)
    onScroll()
    if (opt.flash) {
      flash.value = no
      setTimeout(() => { if (flash.value === no) flash.value = null }, 1200)
    }
  })
}
function scrollToDefault(node: string): void {
  const d = props.ix.defaultByNode.get(node)
  if (!d || d.after === null) return
  fold.value = revealLine(props.ix, d.after, fold.value)
  nextTick(() => {
    const i = rowIndex(rows.value, { node })
    if (i >= 0 && box.value) box.value.scrollTop = Math.max(0, i * ROW - box.value.clientHeight / 3)
    onScroll()
  })
}
function foldAll(): void {
  // 折叠后滚到原先所在块的块头：大配置（华为顶层上千个块）滚动条停在深处时，看起来像只折了一个块（REQ-055-25）
  const first = rows.value[Math.floor((box.value?.scrollTop ?? 0) / ROW)]
  let top = first && first.type === 'line' ? first.no : null
  let hops = 0
  while (top !== null && props.ix.byNo.get(top)?.parent && hops++ < 64) top = props.ix.byNo.get(top)!.parent ?? null
  fold.value = foldAllOf(props.ix)
  nextTick(() => {
    const i = top === null ? 0 : Math.max(0, rowIndex(rows.value, { line: top }))
    if (box.value) box.value.scrollTop = i * ROW
    onScroll()
  })
}
function unfoldAll(): void {
  fold.value = new Set()
}
defineExpose({ scrollToLine, scrollToDefault, foldAll, unfoldAll })

let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(() => { height.value = box.value?.clientHeight ?? 600 })
  if (box.value) ro.observe(box.value)
  height.value = box.value?.clientHeight ?? 600
})
onBeforeUnmount(() => ro?.disconnect())
watch(() => [props.domain, props.showDefaults], () => nextTick(onScroll))
</script>

<template>
  <div ref="box" class="ss" data-testid="script" :data-rows="rows.length" @scroll.passive="onScroll" @click="onClick">
    <div class="ss-in" :style="{ height: `${rows.length * ROW}px` }">
      <div class="ss-win" :style="{ transform: `translateY(${win[0] * ROW}px)` }">
        <template v-for="{ r } in slice" :key="r.type === 'line' ? r.no : `d:${r.d.node}`">
          <div v-if="r.type === 'line'" :class="cls(r.no)" :data-row="1" :data-ln="r.no" :data-ly="line(r.no).layer || ''">
            <span class="n">{{ r.no }}</span>
            <span class="f">
              <button v-if="ix.kids.has(r.no)" type="button" :data-fold="r.no" :aria-label="$t('device-analysis.fold')" :aria-expanded="!fold.has(r.no)">
                <Icon :name="fold.has(r.no) ? 'chevR' : 'chevD'" small />
              </button>
            </span>
            <span class="g">
              <span v-if="line(r.no).kind === 'unknown'" class="gmark unk">?</span>
              <span v-else-if="line(r.no).kind === 'raw'" class="gmark raw">R</span>
            </span>
            <span class="lys" />
            <span class="t"><template v-for="(sg, k) in segments(line(r.no))" :key="k"><span v-if="sg.ref" class="rf" :data-ref="sg.ref" :title="$t('device-analysis.gotoDef', { name: labelOf(sg.ref) })">{{ sg.text }}</span><span v-else-if="sg.cls" :class="sg.cls">{{ sg.text }}</span><template v-else>{{ sg.text }}</template></template><span v-if="fold.has(r.no) && ix.kids.has(r.no)" class="fold-more">… {{ descendantCount(ix, r.no) }}</span></span>
          </div>
          <div v-else class="r dflt" :class="{ 'is-hl': selNode === r.d.node }" :data-row="1" :data-def="r.d.node" :data-ln="r.d.after ?? ''" data-testid="default-row">
            <span class="n" />
            <span class="f" />
            <span class="g"><span class="gm-def">D</span></span>
            <span class="lys" />
            <span class="t">{{ defText(r) }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ss { flex: 1; min-height: 0; overflow: auto; font: 12.5px/20px var(--font-mono); background: var(--surface); position: relative; }
.ss-in { position: relative; min-width: max-content; }
.ss-win { position: absolute; left: 0; right: 0; top: 0; will-change: transform; }
.r { display: flex; white-space: pre; height: 20px; cursor: pointer; position: relative; }
.r:hover { background: color-mix(in srgb, var(--blue-soft) 55%, transparent); }
.n { flex: none; width: 54px; padding-right: 8px; text-align: right; color: var(--ink-3); user-select: none; background: var(--surface-2); border-right: 1px solid var(--line); }
.f { flex: none; width: 18px; display: inline-flex; align-items: center; justify-content: center; color: var(--ink-3); }
.f button { all: unset; width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; border-radius: 3px; cursor: pointer; }
.f button:hover { background: var(--surface-3); color: var(--ink); }
.f button:focus-visible { outline: 2px solid var(--focus); }
.g { flex: none; width: 20px; display: inline-flex; align-items: center; justify-content: center; }
.lys { flex: none; width: 3px; background: var(--c, transparent); opacity: .85; }
.t { padding: 0 24px 0 8px; }
.kw { color: var(--blue); }
.pa { color: var(--teal-ink); font-weight: 600; }
.rf { color: var(--e-cross); font-weight: 600; text-decoration: underline dotted; text-underline-offset: 3px; cursor: pointer; border-radius: 2px; }
.rf:hover { background: color-mix(in srgb, var(--amber-soft) 80%, transparent); text-decoration-style: solid; }
.r.c-sep .t, .r.raw .t { color: var(--ink-3); }
.r.unknown { background: color-mix(in srgb, var(--red-soft) 70%, transparent); }
.r.unknown .t { text-decoration: underline wavy color-mix(in srgb, var(--red) 60%, transparent); text-underline-offset: 4px; text-decoration-thickness: 1px; }
.r.dflt { color: var(--ink-2); font-style: italic; }
.r.dflt .t { outline: 1.2px dashed var(--ink-3); outline-offset: -3px; line-height: 20px; }
.gm-def { width: 14px; height: 14px; border-radius: 3px; border: 1px dashed var(--ink-3); color: var(--ink-3); font: 700 9px/12px var(--font-ui); text-align: center; font-style: normal; }
.r.is-hl { background: var(--hl-line); }
.r.is-hl .n { background: var(--hl-line); color: var(--amber-ink); font-weight: 600; box-shadow: inset 3px 0 0 var(--hl-line-edge); }
.r.is-sub { background: color-mix(in srgb, var(--hl-line) 45%, transparent); }
.r.is-flash .t { animation: flash 1.1s ease-out; }
@keyframes flash { 0% { background: var(--amber); } 100% { background: transparent; } }
.fold-more { color: var(--ink-3); font-style: italic; padding-left: 6px; }
</style>
