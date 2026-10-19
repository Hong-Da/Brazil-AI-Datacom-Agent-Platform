<script setup lang="ts">
/**
 * 配置分层视图：复用设备配置图的树状图（GraphCanvas，cytoscape + ELK）。华为风格按视图层级、Cisco 风格按功能域
 * （由调用方建 Model 时决定）；只在预算内展开，点选节点展开它的下一层；外部选中时展开祖先并居中。
 */
import { computed, onMounted, ref, watch } from 'vue'
import GraphCanvas from '@/views/device-graph/GraphCanvas.vue'
import {
  DEP_KINDS, aggregateEdges, ancestors, autoExpand, collapseSubtree, expandSubtree, shownChildren, visibleRep, visibleTree, type Model,
} from '@/views/device-graph/model'

const props = defineProps<{
  model: Model
  selected: string | null
  showDefault: boolean
  edgeName: (kind: string) => string
  moreText: (n: number) => string
}>()
const emit = defineEmits<{ (e: 'tap', id: string): void; (e: 'background'): void }>()

const expanded = ref(new Set<string>())
const limits = ref(new Map<string, number>())
const anchor = ref<string | null>(null)
const canvas = ref<InstanceType<typeof GraphCanvas>>()
const opts = computed(() => ({ showDefault: props.showDefault, domain: '' }))
const vis = computed(() => visibleTree(props.model, { ...opts.value, expanded: expanded.value, limits: limits.value }))
const visSet = computed(() => new Set(vis.value.map((v) => v.id)))
const selRep = computed(() => (props.selected ? visibleRep(props.model, props.selected, visSet.value) : null))
const kinds = new Set<string>(DEP_KINDS)
const edges = computed(() => aggregateEdges(props.model, visSet.value, kinds, props.selected))
const related = computed(() => {
  const out = new Set<string>()
  if (!props.selected) return out
  for (const e of props.model.deps) {
    const other = e.from === props.selected ? e.to : e.to === props.selected ? e.from : null
    const r = other ? visibleRep(props.model, other, visSet.value) : null
    if (r) out.add(r)
  }
  return out
})

function reveal(id: string): void {
  const e = new Set(expanded.value)
  for (const a of ancestors(props.model, id)) e.add(a)
  expanded.value = e
}
function onTap(id: string): void {
  const m = props.model
  if (!expanded.value.has(id) && shownChildren(m, id, { ...opts.value, expanded: expanded.value }).length) expanded.value = new Set([...expanded.value, id])
  anchor.value = id
  emit('tap', id)
}
function showMore(parent: string): void {
  const m = new Map(limits.value)
  m.set(parent, (m.get(parent) ?? 120) + 200)
  limits.value = m
  anchor.value = parent
}
/** 外部选中：展开祖先并居中。 */
function focus(id: string | null): void {
  if (!id || !props.model.nodes.has(id)) return
  reveal(id)
  anchor.value = null
  requestAnimationFrame(() => { if (selRep.value) canvas.value?.focus(selRep.value) })
}
function expandSel(): void {
  const base = selRep.value ?? props.model.root
  anchor.value = base
  expanded.value = expandSubtree(props.model, base, expanded.value, opts.value, 300)
}
function collapseAll(): void {
  expanded.value = collapseSubtree(props.model, props.model.root, expanded.value)
  anchor.value = props.model.root
}
defineExpose({ focus, fit: () => canvas.value?.fit(), expandSel, collapseAll })

function reset(): void {
  expanded.value = autoExpand(props.model, opts.value, 80)
  limits.value = new Map()
  if (props.selected) focus(props.selected)
}
watch(() => props.model, reset)
watch(() => props.showDefault, () => { if (props.selected) reveal(props.selected) })
onMounted(reset)
</script>

<template>
  <GraphCanvas
    ref="canvas"
    :model="model"
    :vis="vis"
    :edges="edges"
    :selected="selRep"
    :related="related"
    :matches="new Set<string>()"
    :dim-others="false"
    :show-contains="true"
    :anchor="anchor"
    :more-text="moreText"
    :edge-name="edgeName"
    data-testid="analysis-tree"
    @tap="onTap"
    @more="showMore"
    @background="emit('background')"
  />
</template>
