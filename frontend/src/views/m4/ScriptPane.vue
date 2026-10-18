<script setup lang="ts">
/**
 * 变更脚本面板（预览 change.html 的 .scr）：行号 + 依赖弧线槽 + 按视图层级缩进的文本 + 右侧序号与原因。
 * 下发脚本：命令行按原因着色，选中一条时它的前置命令高亮，并在槽里画弧线连到前置。
 * 回滚脚本：命令行右侧标出对应的下发命令序号，高亮与选中命令对应的回滚行。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { REASON, edgeOf, matches, type Filter, type Op, type Row } from './change'

const props = defineProps<{
  rows: Row[]
  ops: Map<number, Op>
  side: 'f' | 'r'
  /** 选中的下发命令序号 */
  sel: number | null
  /** 高亮的前置命令（下发脚本） */
  deps?: number[]
  /** 弧线：[前置序号, 依赖类型] */
  arcs?: [number, string][]
  filter?: Filter
  /** 回滚脚本中要高亮的回滚命令序号 */
  pairs?: number[]
  /** 回滚命令 → 对应的下发命令序号 */
  pairOf?: Map<number, number[]>
  actionName: (a: string) => string
  testid?: string
}>()
const emit = defineEmits<{ (e: 'pick', seq: number): void }>()

const box = ref<HTMLDivElement>()
const svgH = ref(0)
const paths = ref<{ d: string; cls: string; cx: number; cy: number }[]>([])
const head = ref('')

const lineCls = (r: Row) => {
  const c = [`k-${r.kind}`]
  if (r.kind !== 'cmd' || r.seq === null) return c
  const op = props.ops.get(r.seq)
  if (props.side === 'f') {
    if (op) c.push(`r-${REASON[op.action]}`)
    if (op?.risk === 'high') c.push('has-risk')
    if (r.seq === props.sel) c.push('is-sel')
    if (props.deps?.includes(r.seq)) c.push('is-dep')
    if (op && props.filter && !matches(op, props.filter) && r.seq !== props.sel) c.push('is-dim')
  } else {
    c.push('rb')
    if (props.pairs?.includes(r.seq)) c.push('is-pair')
  }
  return c
}
const undoSplit = (t: string): [string, string] => {
  const m = /^(undo|no)\b/.exec(t)
  return m ? [m[1], t.slice(m[1].length)] : ['', t]
}
const rowsView = computed(() => props.rows.map((r, i) => ({ r, i, cls: lineCls(r), parts: undoSplit(r.text) })))

function yOf(seq: number): number | null {
  const el = box.value?.querySelector<HTMLElement>(`.sl[data-seq="${seq}"]`)
  return el ? el.offsetTop + el.offsetHeight / 2 : null
}
function draw(): void {
  if (props.side !== 'f' || !box.value) return
  svgH.value = box.value.scrollHeight
  paths.value = []
  head.value = ''
  if (props.sel === null) return
  const y2 = yOf(props.sel)
  if (y2 === null) return
  const out: { d: string; cls: string; cx: number; cy: number }[] = []
  ;(props.arcs ?? []).forEach(([s, kind], n) => {
    const y1 = yOf(s)
    if (y1 === null) return
    const bend = Math.max(4, 26 - Math.min(20, Math.abs(y2 - y1) / 22) - n * 2)
    const e = edgeOf(kind)
    out.push({ d: `M32 ${y1} C ${bend} ${y1}, ${bend} ${y2}, 32 ${y2}`, cls: e === 'mutex' ? 'k-mutex' : e === 'side' ? 'k-side' : '', cx: 31, cy: y1 })
  })
  paths.value = out
  head.value = `M26 ${y2 - 4} L32 ${y2} L26 ${y2 + 4}`
}

/** 把序号对应的行滚到可见区域。 */
function reveal(seq: number): void {
  const el = box.value?.querySelector<HTMLElement>(`.sl[data-seq="${seq}"]`)
  const pane = box.value
  if (!el || !pane) return
  const top = el.offsetTop
  if (top < pane.scrollTop + 10 || top > pane.scrollTop + pane.clientHeight - 40) pane.scrollTop = Math.max(0, top - pane.clientHeight / 3)
}
defineExpose({ reveal })

function onClick(r: Row): void {
  if (r.kind !== 'cmd' || r.seq === null) return
  if (props.side === 'f') emit('pick', r.seq)
  else {
    const f = props.pairOf?.get(r.seq)
    if (f?.length) emit('pick', f[0])
  }
}

watch(() => [props.rows, props.sel, props.arcs], () => { void nextTick(draw) })
let ro: ResizeObserver | null = null
onMounted(() => {
  void nextTick(draw)
  ro = new ResizeObserver(() => draw())
  if (box.value) ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())
</script>

<template>
  <div ref="box" class="scr" :data-testid="testid">
    <div
      v-for="v in rowsView" :key="v.i" class="sl" :class="v.cls"
      :data-seq="v.r.kind === 'cmd' && v.r.seq !== null ? v.r.seq : undefined" :data-kind="v.r.kind"
      @click="onClick(v.r)"
    >
      <span class="no">{{ v.i + 1 }}</span><span class="arc" />
      <span class="tx" style="padding-left: 6px"><i v-for="k in v.r.depth" :key="k" class="rail" :style="{ left: `calc(${(k - 1) * 2}ch + 6px)` }" /><span class="ind">{{ ' '.repeat(v.r.depth * 2) }}</span><span v-if="v.parts[0]" class="kw-undo">{{ v.parts[0] }}</span>{{ v.parts[1] }}</span>
      <span class="rx">
        <template v-if="v.r.kind === 'cmd' && v.r.seq !== null">
          <template v-if="side === 'f'">
            <span class="pairref">#{{ v.r.seq }}</span>
            <span v-if="ops.get(v.r.seq)" class="rs" :class="REASON[ops.get(v.r.seq)!.action]">{{ actionName(ops.get(v.r.seq)!.action) }}</span>
          </template>
          <span v-else-if="pairOf?.get(v.r.seq)?.length" class="pairref">↩ {{ pairOf.get(v.r.seq)!.map((s) => `#${s}`).join(' ') }}</span>
        </template>
      </span>
    </div>
    <svg v-if="side === 'f'" class="arcs" :height="svgH" :style="{ height: `${svgH}px` }" aria-hidden="true">
      <template v-for="(p, i) in paths" :key="i"><path :class="p.cls" :d="p.d" /><circle :cx="p.cx" :cy="p.cy" r="2.6" /></template>
      <path v-if="head" :d="head" style="stroke: var(--amber)" />
    </svg>
  </div>
</template>

<style scoped>
.scr .tx .ind { color: transparent; }
.scr .sl.k-cmd.rb { cursor: pointer; }
.scr .sl .pairref { font: 11px var(--font-ui); color: var(--ink-3); white-space: nowrap; }
</style>
