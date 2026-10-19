<script setup lang="ts">
/**
 * 选中对象（REQ-034 右侧面板，五个视图共用）：命令写法（随显示风格）、规范编号、类型、层与跨层特性、功能域、
 * 配置行、被引用处（点一行跳回脚本）、定义行、跨层依赖（点对端继续追）、在其他视图中查看。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { formatValue, type Model } from '@/views/device-graph/model'
import { crossOf, ownerObject } from './layers'
import type { ScriptIndex } from './script'
import type { FeatureInfo, LayerInfo, LayersData, ViewName } from './types'

const props = defineProps<{
  model: Model
  selected: string | null
  layers: LayersData | null
  ix: ScriptIndex | null
  info: { layers: LayerInfo[]; features: FeatureInfo[] }
  defs: Record<string, number | null>
  labelOf: (id: string) => string
  typeName: (schema: string) => string
  domainOf: (schema: string) => string | null
  pick: (o: Record<string, string> | null | undefined) => string
  view: ViewName
}>()
const emit = defineEmits<{ (e: 'line', no: number): void; (e: 'select', id: string): void; (e: 'view', v: ViewName): void }>()

const node = computed(() => (props.selected ? props.model.nodes.get(props.selected) ?? null : null))
const obj = computed(() => ownerObject(props.model, props.selected))
const layer = computed(() => (props.selected ? props.layers?.nodes[props.selected] ?? null : null))
const feat = computed(() => {
  if (!props.selected || !props.layers) return null
  const id = props.layers.features_of[props.selected] ?? (obj.value ? props.layers.features_of[obj.value] : undefined)
  return props.info.features.find((f) => f.id === id) ?? null
})
const refs = computed(() => (obj.value ? props.ix?.refs.get(obj.value) ?? [] : []))
const def = computed(() => (obj.value ? props.defs[obj.value] ?? null : null))
const cross = computed(() => crossOf(props.layers?.cross ?? [], obj.value))
function layerName(id: string | null | undefined): string {
  const x = props.info.layers.find((l) => l.id === id)
  return x ? props.pick(x.name) : id || '—'
}
function lineText(no: number): string {
  return props.ix?.byNo.get(no)?.text.trim() ?? ''
}
const kindKey = (k: string) => `device-analysis.kind.${k}`
const { t } = useI18n()
function edgeText(kind: string): string {
  return kind === 'reference' ? t('e.ref') : kind === 'prerequisite' ? t('e.pre') : t('device-graph.e.contains')
}
const VIEWS: { v: ViewName; icon: string }[] = [
  { v: 'script', icon: 'file' },
  { v: 'tree', icon: 'tree' },
  { v: 'tcpip', icon: 'layers' },
  { v: 'relation', icon: 'graph' },
]
</script>

<template>
  <aside class="panel side" data-testid="selection-panel">
    <div class="panel-h"><h3>{{ $t('device-analysis.selection') }}</h3><span class="meta">{{ $t('device-analysis.linked') }}</span></div>
    <div v-if="!node" class="panel-b empty-sel"><Icon name="target" /><p>{{ $t('device-analysis.pickHint') }}</p></div>
    <div v-else class="panel-b">
      <div class="sec">
        <div class="cmd" data-testid="sel-label">{{ labelOf(node.id) }}</div>
        <div class="canon">{{ node.id }}</div>
      </div>
      <dl class="kv">
        <dt>{{ $t('device-analysis.type') }}</dt>
        <dd>
          {{ node.kind === 'object' && node.schema ? typeName(node.schema) : node.schema || $t(kindKey(node.kind)) }}
          <span v-if="node.origin === 'default'" class="tag default">{{ $t('hid.default') }}</span>
          <span v-else-if="node.origin === 'derived'" class="tag derived">{{ $t('hid.derived') }}</span>
        </dd>
        <dt>{{ $t('device-analysis.layer') }}</dt>
        <dd data-testid="sel-layer"><span class="ly" :class="{ mpls: layer === 'mpls' }" :data-ly="layer || ''"><i />{{ layer ? layerName(layer) : $t('device-analysis.noLayer') }}</span><span v-if="feat" class="tag">{{ pick(feat.name) }}</span></dd>
        <dt>{{ $t('device-analysis.domain') }}</dt>
        <dd>{{ (node.schema && domainOf(node.schema)) || node.domain || '—' }}</dd>
        <template v-if="node.kind === 'attr'">
          <dt>{{ $t('device-analysis.value') }}</dt>
          <dd class="mono">{{ formatValue(node.api?.value) }}</dd>
        </template>
        <dt>{{ $t('device-analysis.lines') }}</dt>
        <dd>
          <template v-if="node.lines.length">
            <template v-for="(l, i) in node.lines.slice(0, 12)" :key="l"><a href="#" @click.prevent="emit('line', l)">{{ l }}</a><span v-if="i < Math.min(node.lines.length, 12) - 1">, </span></template>
            <span v-if="node.lines.length > 12" class="faint"> …</span>
          </template>
          <span v-else class="faint">{{ $t('device-analysis.hiddenNoLine') }}</span>
        </dd>
      </dl>
      <div class="sec">
        <h4><Icon name="link" small />{{ $t('device-analysis.refBy', { n: refs.length }) }}<a v-if="def" href="#" class="def" data-testid="sel-def" @click.prevent="emit('line', def)">{{ $t('device-analysis.defLine', { n: def }) }}</a></h4>
        <div v-if="refs.length" class="rl" data-testid="sel-refs">
          <button v-for="l in refs.slice(0, 200)" :key="l" type="button" @click="emit('line', l)"><span class="no">{{ l }}</span><span class="tx">{{ lineText(l) }}</span></button>
        </div>
        <p v-else class="small faint">{{ $t('device-analysis.noRefs') }}</p>
      </div>
      <div class="sec">
        <h4><Icon name="layers" small />{{ $t('device-analysis.crossTitle', { n: cross.length }) }}</h4>
        <div v-if="cross.length" class="xl" data-testid="sel-cross">
          <button v-for="(x, i) in cross" :key="i" type="button" @click="emit('select', x.other)">
            <span class="arrow">{{ x.out ? '→' : '←' }}</span>
            <span class="ly" :class="{ mpls: (x.out ? x.edge.to_layer : x.edge.from_layer) === 'mpls' }" :data-ly="x.out ? x.edge.to_layer : x.edge.from_layer"><i />{{ layerName(x.out ? x.edge.to_layer : x.edge.from_layer) }}</span>
            <code :title="x.other">{{ labelOf(x.other) }}</code>
            <span class="small faint">{{ edgeText(x.edge.kind) }}</span>
          </button>
        </div>
        <p v-else class="small faint">{{ $t('device-analysis.noCross') }}</p>
      </div>
      <div class="sec">
        <h4>{{ $t('device-analysis.showIn') }}</h4>
        <div class="row wrap" style="gap: 6px">
          <button v-for="x in VIEWS" :key="x.v" class="btn btn-xs" :aria-pressed="view === x.v" :disabled="view === x.v" @click="emit('view', x.v)"><Icon :name="x.icon" small />{{ $t(`device-analysis.tab.${x.v}`) }}</button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.side { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.side .panel-b { overflow: auto; display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.empty-sel { color: var(--ink-3); font-size: 12.5px; text-align: center; padding: 30px 10px; align-items: center; }
.sec h4 { font-size: 11.5px; color: var(--ink-3); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; margin: 0 0 6px; display: flex; align-items: center; gap: 6px; }
.sec h4 .def { margin-left: auto; text-transform: none; font-weight: 400; letter-spacing: 0; }
.cmd { font: 600 13px var(--font-mono); overflow-wrap: anywhere; }
.kv { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 4px 8px; font-size: 12px; margin: 0; }
.kv dt { color: var(--ink-3); }
.kv dd { margin: 0; overflow-wrap: anywhere; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.rl { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 5px; overflow: auto; max-height: 260px; }
.rl button { all: unset; box-sizing: border-box; display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 6px; padding: 4px 8px; font: 11.5px var(--font-mono); cursor: pointer; border-top: 1px solid var(--line); }
.rl button:first-child { border-top: 0; }
.rl button:hover { background: var(--surface-2); }
.rl button:focus-visible, .xl button:focus-visible { outline: 2px solid var(--focus); }
.rl .no { color: var(--blue-ink); text-align: right; }
.rl .tx { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.xl { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
.xl button { all: unset; box-sizing: border-box; cursor: pointer; display: grid; grid-template-columns: 14px auto minmax(0, 1fr) auto; align-items: center; gap: 6px; padding: 3px 4px; border-radius: 4px; width: 100%; }
.xl button:hover { background: var(--surface-2); }
.xl .arrow { color: var(--e-cross); }
.xl code { font: 11.5px var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xl .small { white-space: nowrap; }
</style>
