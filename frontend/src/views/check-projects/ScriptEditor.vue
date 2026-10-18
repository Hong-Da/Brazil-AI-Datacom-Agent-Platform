<script setup lang="ts">
/**
 * 脚本编辑器（CodeMirror 6）：行号槽按级别标点（错误 / 警告 / 提示，AI 来源空心），问题行行内波浪下划线，
 * 顺序核查开启时在“移动”槽标出重排后的行号；点槽里的点选中这一行的问题；hl 指定的行高亮并滚到中间。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { minimalSetup } from 'codemirror'
import { EditorState, RangeSetBuilder, StateEffect, StateField, type Extension } from '@codemirror/state'
import {
  Decoration, EditorView, GutterMarker, MatchDecorator, ViewPlugin, gutter, highlightActiveLine,
  highlightActiveLineGutter, lineNumbers, type DecorationSet, type ViewUpdate,
} from '@codemirror/view'
import type { GutterMark } from './logic'
import type { Severity } from './types'

const props = defineProps<{
  modelValue: string
  marks: Map<number, GutterMark>
  moves: Map<number, number>
  squiggles: { line: number; sev: Severity }[]
  hl: number | null
  /** hl 变化时递增，用来重复滚到同一行 */
  hlTick?: number
  moveTitle: (from: number, to: number) => string
  readOnly?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'pick-line', line: number): void }>()

interface Data { marks: Map<number, GutterMark>; moves: Map<number, number>; sq: { line: number; sev: Severity }[]; hl: number | null }
const setData = StateEffect.define<Data>()
const empty: Data = { marks: new Map(), moves: new Map(), sq: [], hl: null }

const dataField = StateField.define<Data>({
  create: () => empty,
  update(v, tr) {
    for (const e of tr.effects) if (e.is(setData)) return e.value
    return v
  },
})

class DotMarker extends GutterMarker {
  constructor(readonly m: GutterMark) { super() }
  eq(o: GutterMarker): boolean { return o instanceof DotMarker && o.m.sev === this.m.sev && o.m.hollow === this.m.hollow && o.m.title === this.m.title }
  toDOM(): Node {
    const s = document.createElement('span')
    s.className = `gdot ${this.m.sev}${this.m.hollow ? ' ring' : ''}`
    s.title = this.m.title
    return s
  }
}
class MoveMarker extends GutterMarker {
  constructor(readonly from: number, readonly to: number) { super() }
  eq(o: GutterMarker): boolean { return o instanceof MoveMarker && o.from === this.from && o.to === this.to }
  toDOM(): Node {
    const s = document.createElement('span')
    s.textContent = `${this.to > this.from ? '↓' : '↑'}${this.to}`
    s.title = props.moveTitle(this.from, this.to)
    s.className = 'mvmark'
    return s
  }
}

const dataChanged = (u: ViewUpdate) => u.docChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setData)))
const lineNo = (view: EditorView, pos: number) => view.state.doc.lineAt(pos).number

const dots = gutter({
  class: 'cm-r31-dots',
  lineMarker(view, line) {
    const m = view.state.field(dataField).marks.get(lineNo(view, line.from))
    return m ? new DotMarker(m) : null
  },
  lineMarkerChange: dataChanged,
  domEventHandlers: {
    mousedown(view, line) {
      const n = lineNo(view, line.from)
      if (!view.state.field(dataField).marks.has(n)) return false
      emit('pick-line', n)
      return true
    },
  },
})
const moveGutter = gutter({
  class: 'cm-r31-moves',
  lineMarker(view, line) {
    const n = lineNo(view, line.from)
    const to = view.state.field(dataField).moves.get(n)
    return to === undefined ? null : new MoveMarker(n, to)
  },
  lineMarkerChange: dataChanged,
})

/** 问题行背景、波浪线、高亮行 */
const issueDeco = EditorView.decorations.compute([dataField, 'doc'], (state) => {
  const d = state.field(dataField)
  const b = new RangeSetBuilder<Decoration>()
  const total = state.doc.lines
  const items: { from: number; to: number; deco: Decoration }[] = []
  const bySev = new Map(d.sq.map((s) => [s.line, s.sev]))
  const lines = new Set<number>([...bySev.keys(), ...(d.hl ? [d.hl] : [])])
  for (const n of [...lines].sort((x, y) => x - y)) {
    if (n < 1 || n > total) continue
    const line = state.doc.line(n)
    const cls = [bySev.get(n) === 'error' ? 'cm-r31-err' : '', n === d.hl ? 'cm-r31-hl' : ''].filter(Boolean).join(' ')
    if (cls) items.push({ from: line.from, to: line.from, deco: Decoration.line({ class: cls }) })
    const sev = bySev.get(n)
    const lead = line.text.length - line.text.trimStart().length
    if (sev && line.text.trim()) items.push({ from: line.from + lead, to: line.to, deco: Decoration.mark({ class: `cm-r31-sq ${sev}` }) })
  }
  for (const it of items) b.add(it.from, it.to, it.deco)
  return b.finish()
})

/** 命令着色：undo / no 关键字、IPv4 地址、会话命令与分隔行（淡色）、注释 */
const syntax = new MatchDecorator({
  regexp: /^(\s*)(undo|no)\b|\b\d{1,3}(?:\.\d{1,3}){3}\b|^\s*(?:system-view|commit|return|quit|exit|end|configure terminal|#|!)\s*$|^\s*!.*$/g,
  decoration: (m) => {
    if (m[2]) return Decoration.mark({ class: 'k-undo' })
    if (/^\d/.test(m[0])) return Decoration.mark({ class: 'k-ip' })
    if (/^\s*!\S/.test(m[0])) return Decoration.mark({ class: 'k-cmt' })
    return Decoration.mark({ class: 'k-dim' })
  },
})
const syntaxPlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet
  constructor(view: EditorView) { this.decorations = syntax.createDeco(view) }
  update(u: ViewUpdate) { this.decorations = syntax.updateDeco(u, this.decorations) }
}, { decorations: (v) => v.decorations })

const host = ref<HTMLDivElement>()
let view: EditorView | null = null

function extensions(): Extension[] {
  return [
    minimalSetup,
    dataField,
    dots,
    lineNumbers(),
    moveGutter,
    highlightActiveLine(),
    highlightActiveLineGutter(),
    issueDeco,
    syntaxPlugin,
    EditorState.readOnly.of(!!props.readOnly),
    EditorView.contentAttributes.of({ spellcheck: 'false', 'data-testid': 'cp-editor-content' }),
    EditorView.updateListener.of((u) => {
      if (u.docChanged) emit('update:modelValue', u.state.doc.toString())
    }),
  ]
}

function pushData(scroll: boolean): void {
  if (!view) return
  const effects: StateEffect<unknown>[] = [setData.of({ marks: props.marks, moves: props.moves, sq: props.squiggles, hl: props.hl })]
  if (scroll && props.hl && props.hl <= view.state.doc.lines) {
    effects.push(EditorView.scrollIntoView(view.state.doc.line(props.hl).from, { y: 'center' }))
  }
  view.dispatch({ effects })
}

onMounted(() => {
  view = new EditorView({ state: EditorState.create({ doc: props.modelValue, extensions: extensions() }), parent: host.value! })
  pushData(false)
})
onBeforeUnmount(() => { view?.destroy(); view = null })

// 外部替换内容（切换脚本、恢复修订、采用重排）
watch(() => props.modelValue, (v) => {
  if (!view || v === view.state.doc.toString()) return
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } })
})
watch(() => [props.marks, props.moves, props.squiggles], () => pushData(false))
watch(() => [props.hl, props.hlTick], () => pushData(true))

/** 把光标放到某一行并聚焦。 */
function focusLine(n: number): void {
  if (!view || n < 1 || n > view.state.doc.lines) return
  const pos = view.state.doc.line(n).from
  view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
  view.focus()
}
defineExpose({ focusLine })
</script>

<template>
  <div ref="host" class="cmhost" data-testid="cp-editor" />
</template>
