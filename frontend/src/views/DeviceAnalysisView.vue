<script setup lang="ts">
/**
 * 设备配置分析（REQ-034）：一个页面五个视图——结构化脚本、配置分层（树）、TCP/IP 模型、配置关系（关系图谱，可按层分带）、
 * 分析摘要；右侧“选中对象”常驻，选中的对象在各视图中同时定位。数据：GET /devices/{id}/analysis
 * （先取 graph,layers,script，摘要随后单独取）；计算全部在后端，前端只负责显示。
 */
import { computed, nextTick, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import Icon from '@/components/Icon.vue'
import HiddenLegend from '@/components/hidden-legend.vue'
import ShowDefaultToggle from '@/components/show-default-toggle.vue'
import { ApiError, errorText, get } from '@/api'
import { useTerms } from '@/stores/terms'
import { rememberedChoice, rememberedFlag } from '@/stores/prefs'
import ForceGraph from './device-graph/ForceGraph.vue'
import { buildForce, type FNode } from './device-graph/force'
import { EDGE_SHORT, buildModel, domainResolver, formatValue, type Model } from './device-graph/model'
import type { ApiNode, DeviceRow, SchemaTree } from './device-graph/types'
import AnalysisTree from './device-analysis/AnalysisTree.vue'
import ScriptView from './device-analysis/ScriptView.vue'
import SelectionPanel from './device-analysis/SelectionPanel.vue'
import SummaryView from './device-analysis/SummaryView.vue'
import TcpipView from './device-analysis/TcpipView.vue'
import { ownerObject } from './device-analysis/layers'
import { indexScript } from './device-analysis/script'
import { BAND_ORDER, VIEWS, type AnalysisData, type SummaryData, type ViewName } from './device-analysis/types'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const terms = useTerms()

const deviceId = computed(() => {
  const v = Number(route.params.id)
  return Number.isFinite(v) && v > 0 ? v : null
})

// ---------- 数据 ----------
const devices = ref<DeviceRow[] | null>(null)
const devicesErr = ref('')
const schema = shallowRef<SchemaTree | null>(null)
const data = shallowRef<AnalysisData | null>(null)
const loading = ref(false)
const loadErr = ref('')
const summary = shallowRef<SummaryData | null>(null)
const summaryLoading = ref(false)
const summaryErr = ref('')
const device = computed(() => devices.value?.find((d) => d.id === deviceId.value) ?? null)

async function getRetry<T>(path: string): Promise<T> {
  try {
    return await get<T>(path)
  } catch (e) {
    if (!(e instanceof ApiError) || e.status < 500) throw e
    await new Promise((r) => setTimeout(r, 400))
    return get<T>(path)
  }
}
async function loadDevices(): Promise<void> {
  devicesErr.value = ''
  try {
    devices.value = (await getRetry<{ devices: DeviceRow[] }>('/devices')).devices
  } catch (e) {
    devicesErr.value = errorText(e)
  }
}
async function loadSchema(): Promise<void> {
  try { schema.value = await getRetry<SchemaTree>('/kb/schema') } catch { schema.value = null }
}
async function loadMain(): Promise<void> {
  if (!deviceId.value) return
  loading.value = true
  loadErr.value = ''
  try {
    data.value = await getRetry<AnalysisData>(`/devices/${deviceId.value}/analysis?parts=graph,layers,script`)
  } catch (e) {
    loadErr.value = errorText(e)
    data.value = null
  } finally {
    loading.value = false
  }
}
async function loadSummary(): Promise<void> {
  if (!deviceId.value) return
  summaryLoading.value = true
  summaryErr.value = ''
  try {
    summary.value = (await getRetry<AnalysisData>(`/devices/${deviceId.value}/analysis?parts=summary`)).summary ?? null
  } catch (e) {
    summaryErr.value = errorText(e)
  } finally {
    summaryLoading.value = false
  }
}
async function loadAll(): Promise<void> {
  await Promise.all([loadMain(), loadSchema()])
  void loadSummary()
}

// ---------- 视图状态 ----------
const view = ref<ViewName>(VIEWS.includes(route.query.view as ViewName) ? (route.query.view as ViewName) : 'script')
const selected = ref<string | null>(null)
const showDefault = rememberedFlag('analysis-default')
const domain = ref('')
const relLayout = rememberedChoice<'cose' | 'bands'>('analysis-rel', 'bands')

const domainOf = computed(() => (schema.value ? domainResolver(schema.value.domains) : (s: string) => (s.startsWith('ext:') ? null : s.split('.')[0])))
const domainOrder = computed(() => schema.value?.domains.map((d) => d.domain) ?? [])
const style = computed(() => terms.style)
const labeler = computed(() => {
  const s = style.value
  void terms.terms
  return (a: ApiNode): string | null => {
    if (!a.schema || a.schema.startsWith('ext:')) return null
    if (a.kind === 'object') return terms.label(a.schema, a.key, s)
    if (a.kind === 'attr') return terms.attr(a.schema, s)
    return null
  }
})
/** 树：华为风格按视图层级，Cisco 风格按功能域（与设备配置图的“自动”一致）。 */
const model = computed<Model | null>(() =>
  data.value?.graph
    ? buildModel(data.value.graph, domainOf.value, { domainOrder: domainOrder.value, groupRaw: true, byDomain: style.value !== 'huawei', labeler: labeler.value })
    : null,
)
const ix = computed(() => (data.value?.script ? indexScript(data.value.script) : null))
const layersData = computed(() => data.value?.layers ?? null)
const layerInfo = computed(() => data.value?.layer_info ?? { layers: [], features: [] })

function pick(o: Record<string, string> | null | undefined): string {
  if (!o) return ''
  const l = String(locale.value)
  return o[l] || o.en || Object.values(o)[0] || ''
}
function lastSeg(s: string): string {
  return s.split('.').pop() ?? s
}
const labelOf = computed(() => {
  const s = style.value
  void terms.terms
  return (id: string): string => {
    const n = model.value?.nodes.get(id)
    const a = n?.api
    if (!n || !a) return id
    if (a.kind === 'object' && a.schema) return terms.label(a.schema, a.key, s)
    if (a.kind === 'attr' && a.schema) return `${terms.attr(a.schema, s) ?? lastSeg(a.schema)} ${formatValue(a.value)}`
    return n.label
  }
})
const typeName = computed(() => {
  const s = style.value
  void terms.terms
  void locale.value
  return (sch: string) => terms.name(sch, s)
})
const attrName = computed(() => {
  const s = style.value
  void terms.terms
  return (sch: string) => terms.attr(sch, s) ?? lastSeg(sch)
})
const domainOfFn = (sch: string) => domainOf.value(sch)

// 结构化脚本的高亮：选中节点自身的行；对象另淡显整棵子树的行
const hl = computed(() => new Set(selected.value ? model.value?.nodes.get(selected.value)?.lines ?? [] : []))
const sub = computed(() => {
  const out = new Set<number>()
  const m = model.value
  const n = selected.value ? m?.nodes.get(selected.value) : null
  if (!m || !n || n.kind !== 'object') return out
  const stack = [...n.children]
  while (stack.length && out.size < 4000) {
    const c = m.nodes.get(stack.pop()!)
    if (!c) continue
    c.lines.forEach((l) => out.add(l))
    stack.push(...c.children)
  }
  return out
})
const scriptDomains = computed(() => {
  const have = new Set((data.value?.script?.lines ?? []).map((l) => l.domain).filter((d): d is string => !!d))
  const order = domainOrder.value.filter((d) => have.has(d))
  return [...order, ...[...have].filter((d) => !order.includes(d)).sort()]
})

// 关系视图
const force = computed(() => (model.value && view.value === 'relation' ? buildForce(model.value, { showDefault: showDefault.value, showRaw: false }) : null))
const forceSel = computed(() => (force.value ? force.value.owner(selected.value) : null))
const allKinds = new Set<string>(['contains', 'reference', 'prerequisite', 'side_effect', 'mutex'])
const bandsCfg = computed(() => ({
  order: BAND_ORDER,
  of: (id: string) => layersData.value?.nodes[id] ?? null,
  label: (b: string) => pick(layerInfo.value.layers.find((l) => l.id === b)?.name) || b,
}))
const layerColor = (n: FNode) => `--ly-${layersData.value?.nodes[n.id] ?? 'unclassified'}`

// ---------- 联动 ----------
const scriptRef = ref<InstanceType<typeof ScriptView>>()
const treeRef = ref<InstanceType<typeof AnalysisTree>>()
const tcpRef = ref<InstanceType<typeof TcpipView>>()
const forceRef = ref<InstanceType<typeof ForceGraph>>()

function firstLine(id: string | null): number | null {
  const n = id ? model.value?.nodes.get(id) : null
  return n && n.lines.length ? n.lines[0] : null
}
/** 当前视图定位到选中的对象。 */
function locate(from: string): void {
  const id = selected.value
  if (!id) return
  nextTick(() => {
    if (view.value === 'script' && from !== 'script') {
      const n = model.value?.nodes.get(id)
      if (n?.origin === 'default' && showDefault.value) scriptRef.value?.scrollToDefault(id)
      else {
        const l = firstLine(id) ?? firstLine(ownerObject(model.value!, id))
        if (l) scriptRef.value?.scrollToLine(l)
      }
    } else if (view.value === 'tree' && from !== 'tree') treeRef.value?.focus(id)
    else if (view.value === 'tcpip' && from !== 'tcpip') tcpRef.value?.focus()
    else if (view.value === 'relation' && from !== 'relation' && forceSel.value) forceRef.value?.focus(forceSel.value)
  })
}
function select(id: string | null, from = 'other'): void {
  selected.value = id && model.value?.nodes.has(id) ? id : null
  syncQuery()
  locate(from)
}
function switchView(v: ViewName): void {
  if (view.value === v) return
  view.value = v
  syncQuery()
  // 新视图挂载后定位
  setTimeout(() => locate('tab'), v === 'relation' ? 450 : 0)
}
function syncQuery(): void {
  const q: Record<string, string> = { view: view.value }
  if (selected.value) q.node = selected.value
  void router.replace({ query: q })
}
function pickLine(no: number): void {
  const l = ix.value?.byNo.get(no)
  select(l?.node ?? null, 'script')
}
function onRef(target: string): void {
  select(target, 'script')
  const def = data.value?.script?.defs[target]
  if (def) scriptRef.value?.scrollToLine(def, { force: true, flash: true })
  else ElMessage.info(t('device-analysis.noDefLine'))
}
function gotoLine(no: number): void {
  if (view.value !== 'script') {
    view.value = 'script'
    syncQuery()
  }
  const l = ix.value?.byNo.get(no)
  if (domain.value && l?.domain !== domain.value) domain.value = ''
  if (l?.node) selected.value = l.node
  syncQuery()
  nextTick(() => scriptRef.value?.scrollToLine(no, { force: true, flash: true }))
}
function jump(tg: { node?: string; line?: number; view?: string; domain?: string; defaults?: boolean }): void {
  if (tg.defaults) showDefault.value = true
  if (tg.domain !== undefined) domain.value = tg.domain
  const v = (tg.view as ViewName) || view.value
  view.value = v
  if (tg.node && model.value?.nodes.has(tg.node)) selected.value = tg.node
  syncQuery()
  nextTick(() => {
    if (v !== 'script') return locate('tab')
    if (tg.defaults && tg.node) scriptRef.value?.scrollToDefault(tg.node)
    else if (tg.line) scriptRef.value?.scrollToLine(tg.line, { force: true, flash: true })
    else if (tg.node) locate('summary')
  })
}
function edgeName(kind: string): string {
  const s = EDGE_SHORT[kind]
  return s === 'contains' ? t('device-graph.e.contains') : t(`e.${s ?? 'ref'}`)
}
const moreText = (n: number) => t('device-graph.moreN', { n })
function switchDevice(ev: Event): void {
  const id = (ev.target as HTMLSelectElement).value
  if (id) router.push({ name: 'device-analysis', params: { id }, query: { view: view.value } })
}

const tabCount = computed<Record<ViewName, string>>(() => {
  const s = summary.value
  const objs = data.value?.graph?.nodes.filter((n) => n.kind === 'object').length ?? 0
  return {
    script: String(data.value?.script?.lines.length ?? ''),
    tree: String(objs || ''),
    tcpip: layersData.value ? t('device-analysis.crossShort', { n: layersData.value.cross.length }) : '',
    relation: String(objs || ''),
    summary: s?.check ? t('device-analysis.findingsShort', { n: s.check.summary.total - s.check.summary.ignored }) : '',
  }
})
const TAB_ICON: Record<ViewName, string> = { script: 'file', tree: 'tree', tcpip: 'layers', relation: 'graph', summary: 'report' }

// ---------- 生命周期 ----------
watch(deviceId, () => {
  data.value = null
  summary.value = null
  selected.value = null
  domain.value = ''
  if (deviceId.value) void loadAll()
})
watch(model, (m, old) => {
  if (!m || old) return
  const n = typeof route.query.node === 'string' ? route.query.node : ''
  const l = Number(route.query.line)
  if (n && m.nodes.has(n)) select(n)
  else if (l > 0) setTimeout(() => gotoLine(l), 0)
})
onMounted(async () => {
  void loadDevices()
  if (deviceId.value) await loadAll()
})
</script>

<template>
  <main class="main">
    <div v-if="!deviceId" class="page">
      <div class="crumbs"><router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link></div>
      <div class="ph"><div class="ph-text"><h1>{{ $t('device-analysis.title') }}</h1><p class="ph-sub">{{ $t('device-analysis.chooseHint') }}</p></div></div>
      <section class="panel" data-testid="analysis-device-picker">
        <div v-if="devicesErr" class="panel-b"><div class="notice err"><Icon name="err" /><div class="grow">{{ devicesErr }}</div><button class="btn btn-sm" @click="loadDevices">{{ $t('c.retry') }}</button></div></div>
        <div v-else-if="!devices" class="panel-b faint">{{ $t('c.loading') }}</div>
        <div v-else-if="!devices.length" class="empty"><h3>{{ $t('device-graph.noDevices') }}</h3><router-link class="btn btn-primary btn-sm" :to="{ name: 'devices' }">{{ $t('device-graph.goImport') }}</router-link></div>
        <table v-else class="tbl">
          <thead><tr><th>{{ $t('device-graph.col.name') }}</th><th>{{ $t('device-graph.col.vendor') }}</th><th>Profile</th><th class="num">{{ $t('device-graph.col.lines') }}</th><th class="num">{{ $t('device-graph.col.unknown') }}</th></tr></thead>
          <tbody>
            <tr v-for="d in devices" :key="d.id" class="clickable" @click="router.push({ name: 'device-analysis', params: { id: d.id } })">
              <td><router-link class="mono" :to="{ name: 'device-analysis', params: { id: d.id } }">{{ d.name }}</router-link></td>
              <td><span class="vendor"><i :class="d.vendor === 'huawei' ? 'hw' : 'cs'">{{ d.vendor === 'huawei' ? 'HW' : 'CS' }}</i>{{ d.vendor }}</span></td>
              <td class="mono">{{ d.profile }}</td>
              <td class="num">{{ d.lines }}</td>
              <td class="num">{{ d.unknown }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <div v-else class="page fill an-page">
      <div class="crumbs">
        <router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link><span class="sep">/</span>
        <span>{{ $t('device-analysis.title') }}</span>
      </div>
      <div class="an-head">
        <h1 data-testid="analysis-device">{{ device?.name ?? data?.device ?? `#${deviceId}` }}</h1>
        <div class="an-meta">
          <span v-if="device" class="vendor"><i :class="device.vendor === 'huawei' ? 'hw' : 'cs'">{{ device.vendor === 'huawei' ? 'HW' : 'CS' }}</i>{{ device.vendor }}</span>
          <span v-if="data?.profile" class="tag t-teal mono" title="Profile">{{ data.profile }}</span>
          <span v-if="data?.kb_version" class="tag mono">KB {{ data.kb_version }}</span>
          <span v-if="summary?.history" class="tag mono">{{ $t('device-analysis.versionN', { n: summary.history.current.seq }) }}</span>
        </div>
        <div class="row ml-auto" style="gap: 6px">
          <select v-if="devices && devices.length > 1" class="select dev-sel" :value="deviceId" :aria-label="$t('device-graph.switchDevice')" data-testid="analysis-device-select" @change="switchDevice">
            <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <router-link class="btn btn-sm" :to="{ name: 'device-graph', params: { id: deviceId }, query: selected ? { node: selected } : {} }"><Icon name="graph" small /><span>{{ $t('device-analysis.toGraph') }}</span></router-link>
          <router-link class="btn btn-sm" :to="{ name: 'history', params: { id: deviceId } }"><Icon name="history" small /><span>{{ $t('nav.history') }}</span></router-link>
          <button class="btn btn-sm btn-icon" :title="$t('c.refresh')" :disabled="loading" data-testid="analysis-refresh" @click="loadAll"><Icon name="refresh" small /></button>
        </div>
      </div>

      <div class="an-tabs" role="tablist" data-testid="analysis-tabs">
        <button v-for="v in VIEWS" :key="v" type="button" role="tab" :aria-selected="view === v" :data-view="v" @click="switchView(v)">
          <Icon :name="TAB_ICON[v]" small />{{ $t(`device-analysis.tab.${v}`) }}<span class="cnt">{{ tabCount[v] }}</span>
        </button>
      </div>

      <div v-if="loadErr" class="notice err" data-testid="analysis-error">
        <Icon name="err" /><div class="grow"><b>{{ $t('device-analysis.loadFail') }}</b><div class="small">{{ loadErr }}</div></div>
        <button class="btn btn-sm" @click="loadAll">{{ $t('c.retry') }}</button>
      </div>
      <div v-else-if="!model || !ix || !layersData || !data?.script" class="panel loading-box faint">{{ $t('device-analysis.loading') }}</div>

      <div v-else class="an-work">
        <section class="panel an-main" :data-view="view">
          <!-- 1 结构化脚本 -->
          <template v-if="view === 'script'">
            <div class="an-bar">
              <select v-model="domain" class="select" :aria-label="$t('device-analysis.domainFilter')" data-testid="script-domain">
                <option value="">{{ $t('device-graph.allDomains') }}</option>
                <option v-for="d in scriptDomains" :key="d" :value="d">{{ d }}</option>
              </select>
              <button class="btn btn-sm" data-testid="btn-fold-all" @click="scriptRef?.foldAll()"><Icon name="collapse" small /><span>{{ $t('device-analysis.foldAll') }}</span></button>
              <button class="btn btn-sm" data-testid="btn-unfold-all" @click="scriptRef?.unfoldAll()"><Icon name="expand" small /><span>{{ $t('device-analysis.unfoldAll') }}</span></button>
              <span class="sep" />
              <ShowDefaultToggle v-model="showDefault" :count="data.script.defaults.length" testid="script-defaults" />
              <span class="meta ml-auto">{{ $t('device-analysis.scriptMeta', { n: data.script.lines.length, r: Object.keys(data.script.refs).length }) }}</span>
            </div>
            <ScriptView
              ref="scriptRef"
              :script="data.script"
              :ix="ix"
              :domain="domain"
              :show-defaults="showDefault"
              :hl="hl"
              :sub="sub"
              :sel-node="selected"
              :label-of="labelOf"
              @pick="pickLine"
              @pick-node="(n) => select(n, 'script')"
              @ref="onRef"
            />
            <div class="an-foot">
              <span class="key-sw"><b class="kw">interface</b>{{ $t('device-analysis.k.kw') }}</span>
              <span class="key-sw"><b class="pa">GE0/2/1</b>{{ $t('device-analysis.k.param') }}</span>
              <span class="key-sw"><b class="rf">RAN</b>{{ $t('device-analysis.k.ref') }}</span>
              <span class="key-sw"><span class="gmark raw">R</span>{{ $t('device-graph.rawLegend') }}</span>
              <span class="key-sw"><span class="gmark unk">?</span>{{ $t('device-graph.k.unknown') }}</span>
              <HiddenLegend :derived="false" />
              <span class="small faint ml-auto">{{ $t('device-analysis.stripTip') }}</span>
            </div>
          </template>
          <!-- 2 配置分层 -->
          <template v-else-if="view === 'tree'">
            <div class="an-bar">
              <span class="meta">{{ style === 'huawei' ? $t('device-analysis.treeByView') : $t('device-analysis.treeByDomain') }}</span>
              <button class="btn btn-sm ml-auto" @click="treeRef?.collapseAll()"><Icon name="collapse" small /><span>{{ $t('device-graph.collapseAll') }}</span></button>
              <button class="btn btn-sm" @click="treeRef?.expandSel()"><Icon name="expand" small /><span>{{ $t('device-graph.expandSel') }}</span></button>
              <button class="btn btn-sm btn-icon" :title="$t('device-graph.fit')" @click="treeRef?.fit()"><Icon name="target" small /></button>
              <ShowDefaultToggle v-model="showDefault" testid="tree-defaults" />
            </div>
            <div class="an-canvas"><AnalysisTree ref="treeRef" :model="model" :selected="selected" :show-default="showDefault" :edge-name="edgeName" :more-text="moreText" @tap="(id) => select(id, 'tree')" @background="select(null, 'tree')" /></div>
            <div class="an-foot"><HiddenLegend /></div>
          </template>
          <!-- 3 TCP/IP -->
          <template v-else-if="view === 'tcpip'">
            <div class="an-bar">
              <span class="meta">{{ $t('device-analysis.tcpTip') }}</span>
              <ShowDefaultToggle v-model="showDefault" class="ml-auto" testid="tcp-defaults" />
            </div>
            <TcpipView
              ref="tcpRef"
              :model="model"
              :layers="layersData"
              :info="layerInfo"
              :selected="selected"
              :show-default="showDefault"
              :label-of="labelOf"
              :type-name="typeName"
              :attr-name="attrName"
              :pick="pick"
              @tap="(id) => select(id, 'tcpip')"
            />
            <div class="an-foot">
              <span v-for="l in layerInfo.layers" :key="l.id" class="ly" :class="{ mpls: l.id === 'mpls' }" :data-ly="l.id"><i />{{ pick(l.name) }}</span>
              <span class="xkey">━ {{ $t('device-analysis.crossLegend') }}</span>
              <span v-if="layersData.unclassified.length" class="tag t-amber" :title="layersData.unclassified.join(', ')">{{ $t('device-analysis.unclassifiedN', { n: layersData.unclassified.length }) }}</span>
            </div>
          </template>
          <!-- 4 关系 -->
          <template v-else-if="view === 'relation'">
            <div class="an-bar">
              <div class="seg" role="group" data-testid="rel-layout">
                <button type="button" data-layout="cose" :aria-pressed="relLayout === 'cose'" @click="relLayout = 'cose'">{{ $t('device-analysis.layoutForce') }}</button>
                <button type="button" data-layout="bands" :aria-pressed="relLayout === 'bands'" @click="relLayout = 'bands'">{{ $t('device-analysis.layoutBands') }}</button>
              </div>
              <button class="btn btn-sm" @click="forceRef?.relayout()"><Icon name="refresh" small /><span>{{ $t('device-graph.relayout') }}</span></button>
              <button class="btn btn-sm btn-icon" :title="$t('device-graph.fit')" @click="forceRef?.fit()"><Icon name="target" small /></button>
              <ShowDefaultToggle v-model="showDefault" class="ml-auto" testid="rel-defaults" />
            </div>
            <div class="an-canvas">
              <ForceGraph
                v-if="force"
                ref="forceRef"
                :data="force"
                :domain-order="domainOrder"
                :hidden-domains="new Set<string>()"
                :kinds="allKinds"
                :selected="forceSel"
                :matches="new Set<string>()"
                :dim-others="false"
                :edge-name="edgeName"
                :layout="relLayout"
                :bands="bandsCfg"
                :color-of="layerColor"
                @tap="(id) => select(id, 'relation')"
                @background="select(null, 'relation')"
              />
            </div>
            <div class="an-foot">
              <span v-for="l in layerInfo.layers" :key="l.id" class="ly" :class="{ mpls: l.id === 'mpls' }" :data-ly="l.id"><i />{{ pick(l.name) }}</span>
              <span v-if="relLayout === 'bands'" class="xkey">━ {{ $t('device-analysis.crossLegend') }}</span>
              <span class="small faint ml-auto">{{ $t('device-analysis.relTip') }}</span>
            </div>
          </template>
          <!-- 5 摘要 -->
          <SummaryView
            v-else
            :summary="summary"
            :loading="summaryLoading"
            :error="summaryErr"
            :layers="layersData"
            :layer-info="layerInfo.layers"
            :device-id="deviceId"
            :label-of="labelOf"
            :attr-name="attrName"
            :pick="pick"
            @jump="jump"
            @retry="loadSummary"
          />
        </section>

        <SelectionPanel
          :model="model"
          :selected="selected"
          :layers="layersData"
          :ix="ix"
          :info="layerInfo"
          :defs="data.script.defs"
          :label-of="labelOf"
          :type-name="typeName"
          :domain-of="domainOfFn"
          :pick="pick"
          :view="view"
          @line="gotoLine"
          @select="(id) => select(id, 'side')"
          @view="switchView"
        />
      </div>
    </div>
  </main>
</template>

<style>
/* 层的颜色（REQ-034）：借用功能域分类色（明暗两套已在 app.css 定义）；ForceGraph 从根元素读取这些变量。 */
:root {
  --ly-physical: var(--dom-9);
  --ly-datalink: var(--dom-2);
  --ly-mpls: var(--dom-4);
  --ly-network: var(--dom-1);
  --ly-transport: var(--dom-3);
  --ly-application: var(--dom-6);
  --ly-unclassified: var(--dom-10);
}
[data-ly="physical"] { --c: var(--ly-physical); }
[data-ly="datalink"] { --c: var(--ly-datalink); }
[data-ly="mpls"] { --c: var(--ly-mpls); }
[data-ly="network"] { --c: var(--ly-network); }
[data-ly="transport"] { --c: var(--ly-transport); }
[data-ly="application"] { --c: var(--ly-application); }
[data-ly="unclassified"] { --c: var(--ly-unclassified); }
.ly { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--ink-2); white-space: nowrap; }
.ly i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; background: var(--c, var(--ly-unclassified)); }
.ly.mpls i { background: repeating-linear-gradient(135deg, var(--c) 0 2px, transparent 2px 4px); outline: 1px solid var(--c); outline-offset: -1px; }
</style>

<style scoped>
.an-page { min-height: 0; }
.an-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.an-head h1 { font: 600 18px var(--font-mono); letter-spacing: 0; overflow-wrap: anywhere; }
.an-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dev-sel { width: auto; height: 28px; max-width: 220px; }
.an-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin-bottom: 10px; overflow-x: auto; flex: none; }
.an-tabs button { all: unset; box-sizing: border-box; position: relative; display: inline-flex; align-items: center; gap: 7px; padding: 8px 12px 9px; font-size: 13px; color: var(--ink-2); cursor: pointer; white-space: nowrap; }
.an-tabs button:hover { color: var(--ink); }
.an-tabs button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; border-radius: 4px; }
.an-tabs button[aria-selected="true"] { color: var(--ink); font-weight: 600; }
.an-tabs button[aria-selected="true"]::after { content: ""; position: absolute; left: 8px; right: 8px; bottom: -1px; height: 2px; background: var(--amber); border-radius: 2px; }
.an-tabs .cnt { font-size: 11px; color: var(--ink-3); font-weight: 400; }
.an-work { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 10px; }
@media (max-width: 1150px) { .an-work { grid-template-columns: minmax(0, 1fr) 270px; } }
.an-main { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.an-bar { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; font-size: 12px; flex: none; }
.an-bar .select { width: auto; height: 28px; }
.an-bar .btn { height: 28px; }
.an-bar .sep { width: 1px; height: 16px; background: var(--line); }
.an-bar .meta { color: var(--ink-3); }
.an-canvas { flex: 1; min-height: 0; display: flex; position: relative; }
.an-foot { display: flex; gap: 6px 14px; padding: 6px 12px; border-top: 1px solid var(--line); flex-wrap: wrap; align-items: center; font-size: 11.5px; color: var(--ink-2); flex: none; }
.key-sw { display: inline-flex; align-items: center; gap: 5px; }
.key-sw b { font: 600 11.5px var(--font-mono); }
.key-sw .kw { color: var(--blue); font-weight: 400; }
.key-sw .pa { color: var(--teal-ink); }
.key-sw .rf { color: var(--e-cross); text-decoration: underline dotted; }
.xkey { color: var(--e-cross); }
.loading-box { flex: 1; display: flex; align-items: center; justify-content: center; }
.tbl tr.clickable { cursor: pointer; }
.tbl tr.clickable:hover td { background: var(--surface-2); }
</style>
