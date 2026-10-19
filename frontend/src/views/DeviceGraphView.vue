<script setup lang="ts">
/**
 * 设备配置图：左上图（树状图：cytoscape + ELK；关系图谱：cose 力导向）、右侧节点详情、左下原始配置，三者联动。
 * 树状图可按视图层级（对象的父子关系，华为风格默认）或按功能域组织；大图只在预算内展开，点选节点只展开它的下一层。
 * 节点名按当前显示风格（华为 / Cisco）写成命令，规范编号在详情里保留。
 */
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import Icon from '@/components/Icon.vue'
import { ApiError, errorText, get, post } from '@/api'
import { useStatus } from '@/stores/status'
import { useTerms } from '@/stores/terms'
import { useProject } from '@/stores/project'
import { rememberedChoice, rememberedFlag } from '@/stores/prefs'
import HiddenLegend from '@/components/hidden-legend.vue'
import ShowDefaultToggle from '@/components/show-default-toggle.vue'
import DevDelDialog from '@/components/devdel-dialog.vue'
import GraphCanvas from './device-graph/GraphCanvas.vue'
import ForceGraph from './device-graph/ForceGraph.vue'
import { buildForce, domainColorVar, domainCounts } from './device-graph/force'
import NodeDetail from './device-graph/NodeDetail.vue'
import ConfigText from './device-graph/ConfigText.vue'
import {
  DEP_KINDS, EDGE_KINDS, EDGE_SHORT, RAW_DOMAIN, aggregateEdges, ancestors, autoExpand, buildModel, collapseSubtree,
  domainResolver, expandSubtree, highlightLines, searchNodes, shownChildren, splitLines, stepLine, visibleRep, visibleTree,
  VIEW_TREE_STYLES, type Model,
} from './device-graph/model'
import type { ApiNode, DeviceRow, GraphData, RoundtripResult, SchemaNodeInfo, SchemaTree } from './device-graph/types'
import VendorBadge from '@/components/vendor-badge.vue'

const project = useProject() // 只读成员不显示修改操作（REQ-036）
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const status = useStatus()
const terms = useTerms()

// 删除设备（REQ-038）：删除后回到设备列表
const showDelete = ref(false)
function onDeviceDeleted(_r: unknown, msg: string): void {
  showDelete.value = false
  ElMessage.success(msg)
  void status.refresh()
  void router.push({ name: 'devices' })
}

const deviceId = computed(() => {
  const v = Number(route.params.id)
  return Number.isFinite(v) && v > 0 ? v : null
})

// ---------- 数据 ----------
const devices = ref<DeviceRow[] | null>(null)
const devicesErr = ref('')
const graph = shallowRef<GraphData | null>(null)
const loading = ref(false)
const loadErr = ref('')
const schema = shallowRef<SchemaTree | null>(null)
const device = computed(() => devices.value?.find((d) => d.id === deviceId.value) ?? null)

/** 服务器内部错误时稍后重试一次（后端并发请求偶发 500）。 */
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
  try { schema.value = await getRetry<SchemaTree>('/kb/schema') } catch { schema.value = null /* 取不到时按 Schema 前缀分域 */ }
}
async function loadGraph(): Promise<void> {
  if (!deviceId.value) return
  loading.value = true
  loadErr.value = ''
  try {
    graph.value = await getRetry<GraphData>(`/devices/${deviceId.value}/graph?raw=true`)
  } catch (e) {
    loadErr.value = errorText(e)
    graph.value = null
  } finally {
    loading.value = false
  }
}

// ---------- 图模型与视图状态 ----------
const groupRaw = ref(true)
const showDefault = rememberedFlag('graph-default')
/** 关系图谱里显示原文 / 未识别 / 扩展命令节点（默认隐藏） */
const showRaw = rememberedFlag('graph-raw')
/** 视图：树状图 / 关系图谱 */
const view = rememberedChoice<'tree' | 'force'>('graph-view', 'tree')
/** 树状图的组织方式：auto = 华为 / Nokia 风格按视图层级、Cisco 风格按功能域 */
const orgPref = rememberedChoice<'auto' | 'tree' | 'domain'>('graph-org', 'auto')
const org = computed<'tree' | 'domain'>(() => (orgPref.value === 'auto' ? (VIEW_TREE_STYLES.includes(terms.style) ? 'tree' : 'domain') : orgPref.value))
const hiddenDomains = ref(new Set<string>())
const domain = ref('')
const query = ref('')
const debouncedQuery = ref('')
const edgeOn = ref(new Set<string>(EDGE_KINDS))
const expanded = ref(new Set<string>())
const limits = ref(new Map<string, number>())
const selected = ref<string | null>(null)
const selLine = ref<number | null>(null)
const anchor = ref<string | null>(null)
const rt = ref<RoundtripResult | null>(null)
const busy = ref<'' | 'rebuild' | 'roundtrip'>('')

const domainOf = computed(() => {
  if (schema.value) return domainResolver(schema.value.domains)
  return (s: string) => (s.startsWith('ext:') ? null : s.split('.')[0])
})
const domainOrder = computed(() => schema.value?.domains.map((d) => d.domain) ?? [])
const schemaInfo = computed(() => {
  const m = new Map<string, SchemaNodeInfo>()
  for (const d of schema.value?.domains ?? []) for (const n of d.nodes) m.set(n.id, n)
  return m
})
/** 节点名：对象用当前风格的命令写法，属性用命令关键字（没有登记时用 Schema 名）。 */
const labeler = computed(() => {
  const style = terms.style
  void terms.terms
  return (a: ApiNode): string | null => {
    if (!a.schema || a.schema.startsWith('ext:')) return null
    if (a.kind === 'object') return terms.label(a.schema, a.key, style)
    if (a.kind === 'attr') return terms.attr(a.schema, style)
    return null
  }
})
/** Nokia 风格按视图层级时，顶层对象挂到配置上下文分组下（port、router Base、service › vprn X…） */
const contextOf = computed(() => {
  const t = terms.terms
  if (terms.style !== 'nokia') return undefined
  return (a: ApiNode, attrs: Record<string, unknown>) => (a.schema ? t.context(a.schema, a.key, attrs, 'nokia') : [])
})
const model = computed<Model | null>(() =>
  graph.value
    ? buildModel(graph.value, domainOf.value, { domainOrder: domainOrder.value, groupRaw: groupRaw.value, byDomain: org.value === 'domain', labeler: labeler.value, contextOf: contextOf.value })
    : null,
)
const force = computed(() => (model.value && view.value === 'force' ? buildForce(model.value, { showDefault: showDefault.value, showRaw: showRaw.value }) : null))
const forceSel = computed(() => (force.value ? force.value.owner(selected.value) : null))
const forceMatches = computed(() => {
  const out = new Set<string>()
  const f = force.value
  if (!f) return out
  for (const id of matchIds.value) {
    const o = f.owner(id)
    if (o) out.add(o)
  }
  return out
})
const forceKinds = computed(() => new Set<string>(EDGE_KINDS.filter((k) => edgeOn.value.has(k))))
const forceDomains = computed(() => {
  const c = force.value ? domainCounts(force.value.nodes) : new Map<string, number>()
  const order = [...domainOrder.value.filter((d) => c.has(d)), ...[...c.keys()].filter((d) => !domainOrder.value.includes(d))]
  return order.map((d) => ({ d, n: c.get(d) ?? 0, color: `var(${domainColorVar(d, domainOrder.value)})` }))
})
function toggleDomain(d: string): void {
  const s = new Set(hiddenDomains.value)
  if (s.has(d)) s.delete(d)
  else s.add(d)
  hiddenDomains.value = s
}
const viewOpts = computed(() => ({ showDefault: showDefault.value, domain: domain.value }))
const vis = computed(() => (model.value ? visibleTree(model.value, { ...viewOpts.value, expanded: expanded.value, limits: limits.value }) : []))
const visSet = computed(() => new Set(vis.value.map((v) => v.id)))
const selRep = computed(() => (model.value && selected.value ? visibleRep(model.value, selected.value, visSet.value) : null))
const depKinds = computed(() => new Set<string>(DEP_KINDS.filter((k) => edgeOn.value.has(k))))
const aggEdges = computed(() => (model.value ? aggregateEdges(model.value, visSet.value, depKinds.value, selected.value) : []))
const related = computed(() => {
  const out = new Set<string>()
  const m = model.value
  if (!m || !selected.value) return out
  for (const e of m.deps) {
    if (!depKinds.value.has(e.kind)) continue
    const other = e.from === selected.value ? e.to : e.to === selected.value ? e.from : null
    const r = other ? visibleRep(m, other, visSet.value) : null
    if (r) out.add(r)
  }
  return out
})
const matchIds = computed(() => (model.value ? searchNodes(model.value, debouncedQuery.value) : []))
const matches = computed(() => {
  const out = new Set<string>()
  for (const id of matchIds.value) if (visSet.value.has(id)) out.add(id)
  return out
})
const textLines = computed(() => splitLines(graph.value?.text))
const hl = computed(() => (model.value ? highlightLines(model.value, selected.value) : new Set<number>()))
const unknownSet = computed(() => new Set(model.value?.unknownLines ?? []))
const defaultCount = computed(() => {
  let n = 0
  for (const x of model.value?.nodes.values() ?? []) if (x.origin === 'default') n++
  return n
})
const realCount = computed(() => graph.value?.nodes.length ?? 0)
const visibleReal = computed(() => vis.value.filter((v) => !v.more && model.value?.nodes.get(v.id)?.api).length)
const domainOptions = computed(() => {
  const present = new Set(model.value?.domains ?? [])
  const order = domainOrder.value.length ? domainOrder.value : [...present].filter((d) => d !== RAW_DOMAIN)
  return [...order.filter((d) => present.has(d) || !schema.value), ...(present.has(RAW_DOMAIN) ? [RAW_DOMAIN] : [])]
})

const canvas = ref<InstanceType<typeof GraphCanvas>>()
const forceCanvas = ref<InstanceType<typeof ForceGraph>>()
const text = ref<InstanceType<typeof ConfigText>>()

function resetView(): void {
  const m = model.value
  if (!m) return
  limits.value = new Map()
  expanded.value = autoExpand(m, viewOpts.value, 80)
  anchor.value = null
  if (selected.value && !m.nodes.has(selected.value)) selected.value = null
  if (selected.value) reveal(selected.value)
}

/** 展开祖先，使节点可见。 */
function reveal(id: string): void {
  const m = model.value
  if (!m) return
  const e = new Set(expanded.value)
  for (const a of ancestors(m, id)) e.add(a)
  const n = m.nodes.get(id)
  if (n && n.ctxDomains) {
    if (domain.value && !n.ctxDomains.has(domain.value)) domain.value = ''
  } else if (n && domain.value && n.domain !== domain.value && n.kind !== 'device') domain.value = ''
  expanded.value = e
}

function select(id: string | null, from: 'graph' | 'text' | 'other' = 'other', line: number | null = null): void {
  selected.value = id
  selLine.value = line
  const m = model.value
  if (!id || !m) return
  anchor.value = from === 'graph' ? id : anchor.value
  reveal(id)
  const n = m.nodes.get(id)
  // 点选收起的节点时展开它的下一层
  if (from === 'graph' && n && !expanded.value.has(id) && shownChildren(m, id, { ...viewOpts.value, expanded: expanded.value }).length) {
    expanded.value = new Set([...expanded.value, id])
  }
  if (from !== 'text' && n && n.lines.length && n.kind !== 'device') {
    requestAnimationFrame(() => text.value?.scrollTo(n.lines[0]))
  }
  if (from !== 'graph') {
    anchor.value = null
    requestAnimationFrame(() => {
      if (view.value === 'force') {
        if (forceSel.value) forceCanvas.value?.focus(forceSel.value)
        return
      }
      const r = selRep.value
      if (r) canvas.value?.focus(r)
    })
  }
}

function pickLine(n: number): void {
  const owner = model.value?.lineOwner.get(n) ?? null
  select(owner, 'text', n)
  selLine.value = n
}
function gotoLine(n: number): void {
  text.value?.scrollTo(n, true)
}
function jumpUnknown(dir: 1 | -1): void {
  const l = stepLine(model.value?.unknownLines ?? [], selLine.value, dir)
  if (l === null) return
  pickLine(l)
  requestAnimationFrame(() => text.value?.scrollTo(l, true))
}
function showMore(parent: string): void {
  const m = new Map(limits.value)
  m.set(parent, (m.get(parent) ?? 120) + 200)
  limits.value = m
  anchor.value = parent
}
function toggleEdge(k: string): void {
  const s = new Set(edgeOn.value)
  if (s.has(k)) s.delete(k)
  else s.add(k)
  edgeOn.value = s
}
function collapseAll(): void {
  const m = model.value
  if (!m) return
  expanded.value = new Set([m.root])
  limits.value = new Map()
  anchor.value = m.root
}
function expandSelected(): void {
  const m = model.value
  if (!m) return
  const base = selRep.value ?? m.root
  anchor.value = base
  expanded.value = expandSubtree(m, base, expanded.value, viewOpts.value, 300)
}
function collapseSelected(): void {
  const m = model.value
  if (!m || !selRep.value) return
  anchor.value = selRep.value
  expanded.value = collapseSubtree(m, selRep.value, expanded.value)
}

// ---------- 工具栏动作 ----------
async function rebuild(): Promise<void> {
  if (!deviceId.value || busy.value) return
  busy.value = 'rebuild'
  try {
    await post(`/devices/${deviceId.value}/rebuild`)
    rt.value = null
    await Promise.all([loadGraph(), loadDevices()])
    status.refresh()
    ElMessage.success(t('device-graph.rebuilt'))
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    busy.value = ''
  }
}
async function roundtrip(): Promise<void> {
  if (!graph.value?.text || busy.value) return
  busy.value = 'roundtrip'
  try {
    rt.value = await post<RoundtripResult>('/roundtrip', { text: graph.value.text, profile: device.value?.profile || graph.value.profile || undefined })
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    busy.value = ''
  }
}
function exportJson(): void {
  const g = graph.value
  if (!g) return
  const blob = new Blob([JSON.stringify(g, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(g.device || `device-${deviceId.value}`).replace(/[^\w.-]+/g, '_')}-graph.json`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function switchDevice(ev: Event): void {
  const id = (ev.target as HTMLSelectElement).value
  if (id) router.push({ name: 'device-graph', params: { id } })
}
function edgeName(kind: string): string {
  const s = EDGE_SHORT[kind]
  return s === 'contains' ? t('device-graph.e.contains') : t(`e.${s ?? 'ref'}`)
}
const moreText = (n: number) => t('device-graph.moreN', { n })

// ---------- 生命周期 ----------
let qTimer: ReturnType<typeof setTimeout> | undefined
watch(query, (q) => {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => { debouncedQuery.value = q.trim() }, 220)
})
watch(debouncedQuery, () => {
  const m = model.value
  if (!m || !matchIds.value.length) return
  const e = new Set(expanded.value)
  for (const id of matchIds.value.slice(0, 30)) for (const a of ancestors(m, id)) e.add(a)
  anchor.value = null
  expanded.value = e
})
watch(model, (m, old) => {
  if (!m) return
  if (!old) {
    resetView()
    applyRouteSelection()
  } else {
    const keep = new Set([...expanded.value].filter((id) => m.nodes.has(id)))
    keep.add(m.root)
    expanded.value = keep.size > 1 ? keep : autoExpand(m, viewOpts.value, 80)
    if (selected.value && !m.nodes.has(selected.value)) selected.value = selected.value.startsWith('rawgroup:') ? null : selected.value
    if (selected.value && m.nodes.has(selected.value)) reveal(selected.value)
  }
})
watch(domain, () => {
  if (!model.value) return
  expanded.value = autoExpand(model.value, viewOpts.value, 80)
  anchor.value = null
})
watch(deviceId, () => {
  graph.value = null
  selected.value = null
  selLine.value = null
  rt.value = null
  domain.value = ''
  query.value = ''
  loadGraph()
})

function applyRouteSelection(): void {
  const n = typeof route.query.node === 'string' ? route.query.node : ''
  const l = Number(route.query.line)
  if (n && model.value?.nodes.has(n)) select(n)
  else if (l > 0) {
    pickLine(l)
    requestAnimationFrame(() => text.value?.scrollTo(l, true))
  }
}

onMounted(async () => {
  // 依次请求：先 Schema（决定功能域分组），再图，再设备列表
  await loadSchema()
  await loadGraph()
  await loadDevices()
})
</script>

<template>
  <main class="main">
    <!-- 没有设备 id：先选设备 -->
    <div v-if="!deviceId" class="page">
      <div class="crumbs"><router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('device-graph.title') }}</h1>
          <p class="ph-sub">{{ $t('device-graph.chooseHint') }}</p>
        </div>
      </div>
      <section class="panel" data-testid="device-picker">
        <div class="panel-h"><h3>{{ $t('device-graph.chooseTitle') }}</h3></div>
        <div v-if="devicesErr" class="panel-b">
          <div class="notice err"><Icon name="err" /><div class="grow">{{ devicesErr }}</div><button class="btn btn-sm" @click="loadDevices">{{ $t('c.retry') }}</button></div>
        </div>
        <div v-else-if="!devices" class="panel-b faint">{{ $t('c.loading') }}</div>
        <div v-else-if="!devices.length" class="empty">
          <h3>{{ $t('device-graph.noDevices') }}</h3>
          <router-link class="btn btn-primary btn-sm" :to="{ name: 'devices' }">{{ $t('device-graph.goImport') }}</router-link>
        </div>
        <table v-else class="tbl" data-testid="device-picker-table">
          <thead>
            <tr>
              <th>{{ $t('device-graph.col.name') }}</th><th>{{ $t('device-graph.col.vendor') }}</th><th>Profile</th>
              <th class="num">{{ $t('device-graph.col.lines') }}</th><th class="num">{{ $t('device-graph.col.unknown') }}</th><th>{{ $t('device-graph.col.roundtrip') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in devices" :key="d.id" class="clickable" @click="router.push({ name: 'device-graph', params: { id: d.id } })">
              <td><router-link class="mono" :to="{ name: 'device-graph', params: { id: d.id } }">{{ d.name }}</router-link></td>
              <td><VendorBadge :of="d.vendor">{{ d.vendor }}</VendorBadge></td>
              <td class="mono">{{ d.profile }}</td>
              <td class="num">{{ d.lines }}</td>
              <td class="num">{{ d.unknown }}</td>
              <td>
                <span v-if="d.roundtrip === true" class="tag pass">{{ $t('rt.pass') }}</span>
                <span v-else-if="d.roundtrip === false" class="tag fail">{{ $t('rt.fail') }}</span>
                <span v-else class="faint">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <div v-else class="page fill">
      <div class="crumbs">
        <router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link><span class="sep">/</span>
        <span>{{ device?.name ?? graph?.device ?? `#${deviceId}` }}</span>
      </div>
      <div class="dg-head">
        <div class="dg-title"><h1>{{ device?.name ?? graph?.device ?? `#${deviceId}` }}</h1></div>
        <div class="dg-meta">
          <VendorBadge v-if="device" :of="device.vendor || device.profile">{{ device.vendor }}</VendorBadge>
          <span v-if="device?.sw_version" class="tag mono">{{ device.sw_version }}</span>
          <span v-if="graph?.profile" class="tag t-teal mono" title="Profile">{{ graph.profile }}</span>
          <span v-if="graph?.kb_version" class="tag mono" :title="$t('device-graph.kbTip')">KB {{ graph.kb_version }}</span>
          <span v-if="device?.roundtrip === true" class="tag pass"><Icon name="check" small />{{ $t('rt.pass') }}</span>
          <span v-else-if="device?.roundtrip === false" class="tag fail"><Icon name="x" small />{{ $t('rt.fail') }}</span>
          <span v-if="device?.stale" class="tag t-amber" :title="$t('device-graph.staleTip')">{{ $t('device-graph.stale') }}</span>
        </div>
        <div class="row ml-auto">
          <select v-if="devices && devices.length > 1" class="select dev-sel" :value="deviceId" :aria-label="$t('device-graph.switchDevice')" data-testid="device-select" @change="switchDevice">
            <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <button v-if="project.canWrite" class="btn btn-sm" :disabled="!!busy" data-testid="btn-rebuild" @click="rebuild">
            <Icon name="refresh" small /><span>{{ busy === 'rebuild' ? $t('c.running') : $t('device-graph.rebuild') }}</span>
          </button>
          <button class="btn btn-sm" :disabled="!!busy || !graph?.text" data-testid="btn-roundtrip" @click="roundtrip">
            <Icon name="play" small /><span>{{ busy === 'roundtrip' ? $t('c.running') : $t('device-graph.roundtrip') }}</span>
          </button>
          <router-link class="btn btn-sm" :to="{ name: 'device-analysis', params: { id: deviceId }, query: selected ? { node: selected } : {} }" data-testid="btn-analysis">
            <Icon name="strata" small /><span>{{ $t('nav.device-analysis') }}</span>
          </router-link>
          <button class="btn btn-sm" :disabled="!graph" data-testid="btn-export" @click="exportJson">
            <Icon name="download" small /><span>{{ $t('device-graph.exportJson') }}</span>
          </button>
          <button v-if="project.canWrite" class="btn btn-sm btn-danger" data-testid="btn-delete-device" @click="showDelete = true">
            <Icon name="trash" small /><span>{{ $t('devdel.deleteDeviceEllipsis') }}</span>
          </button>
        </div>
      </div>

      <!-- 往返测试结果 -->
      <div v-if="rt" class="notice rt" :class="rt.ok ? 'ok' : 'err'" data-testid="roundtrip-result">
        <Icon :name="rt.ok ? 'ok' : 'err'" />
        <div class="grow">
          <b>{{ rt.ok ? $t('device-graph.rtOk', { n: textLines.length }) : $t('device-graph.rtFail', { n: rt.diffs.length }) }}</b>
          <span class="small muted rt-meta">{{ $t('device-graph.rtMeta', { u: rt.unknown, c: Math.round(rt.coverage * 1000) / 10 }) }}</span>
          <div v-if="!rt.ok && rt.diffs.length" class="code diff rt-diff">
            <template v-for="(d, i) in rt.diffs" :key="i">
              <div class="l hunk"><span class="n" /><span class="g" /><span class="t">{{ $t('device-graph.rtLine', { n: d.line }) }}</span></div>
              <div v-for="(s, j) in d.original" :key="`o${j}`" class="l del"><span class="n">{{ d.line + j }}</span><span class="g" /><span class="t">{{ s }}</span></div>
              <div v-for="(s, j) in d.rendered" :key="`r${j}`" class="l add"><span class="n" /><span class="g" /><span class="t">{{ s }}</span></div>
            </template>
          </div>
        </div>
        <button class="btn btn-xs btn-icon" :title="$t('c.close')" @click="rt = null"><Icon name="x" small /></button>
      </div>

      <div v-if="loadErr" class="notice err" data-testid="graph-error">
        <Icon name="err" /><div class="grow"><b>{{ $t('device-graph.loadFail') }}</b><div class="small">{{ loadErr }}</div></div>
        <button class="btn btn-sm" @click="loadGraph">{{ $t('c.retry') }}</button>
        <router-link class="btn btn-sm" :to="{ name: 'device-graph' }">{{ $t('device-graph.chooseTitle') }}</router-link>
      </div>
      <div v-else-if="!model" class="panel loading-box faint">{{ $t('c.loading') }}</div>

      <div v-else class="work">
        <section class="panel p-graph" aria-label="Graph">
          <div class="gbar">
            <div class="seg" role="group" :aria-label="$t('device-graph.viewMode')" data-testid="view-switch">
              <button type="button" data-view="tree" :aria-pressed="view === 'tree'" @click="view = 'tree'"><Icon name="tree" small /><span>{{ $t('device-graph.viewTree') }}</span></button>
              <button type="button" data-view="force" :aria-pressed="view === 'force'" @click="view = 'force'"><Icon name="graph" small /><span>{{ $t('device-graph.viewForce') }}</span></button>
            </div>
            <label class="input-wrap">
              <Icon name="search" small />
              <input v-model="query" class="input" style="height: 28px" type="search" :placeholder="$t('device-graph.searchPh')" data-testid="graph-search">
            </label>
            <span v-if="debouncedQuery" class="small faint" data-testid="search-count">{{ $t('device-graph.matchN', { n: matchIds.length }) }}</span>
            <div v-if="view === 'tree'" class="seg" role="group" :aria-label="$t('device-graph.org')" :title="$t('device-graph.orgTip')" data-testid="org-switch">
              <button type="button" data-org="tree" :aria-pressed="org === 'tree'" @click="orgPref = 'tree'"><span>{{ $t('device-graph.orgTree') }}</span></button>
              <button type="button" data-org="domain" :aria-pressed="org === 'domain'" @click="orgPref = 'domain'"><span>{{ $t('device-graph.orgDomain') }}</span></button>
            </div>
            <select v-if="view === 'tree'" v-model="domain" class="select" :aria-label="$t('device-graph.domain')" data-testid="domain-filter">
              <option value="">{{ $t('device-graph.allDomains') }}</option>
              <option v-for="d in domainOptions" :key="d" :value="d">{{ d === 'raw' ? $t('device-graph.rawDomain') : d }}</option>
            </select>
            <span class="divider" />
            <template v-if="view === 'tree'">
              <button class="btn btn-sm" data-testid="btn-collapse-all" @click="collapseAll"><Icon name="collapse" small /><span>{{ $t('device-graph.collapseAll') }}</span></button>
              <button class="btn btn-sm" data-testid="btn-expand-sel" @click="expandSelected"><Icon name="expand" small /><span>{{ $t('device-graph.expandSel') }}</span></button>
              <button class="btn btn-sm" :disabled="!selRep" data-testid="btn-collapse-sel" @click="collapseSelected"><Icon name="minus" small /><span>{{ $t('device-graph.collapseSel') }}</span></button>
              <button class="btn btn-sm btn-icon" :title="$t('device-graph.fit')" data-testid="btn-fit" @click="canvas?.fit()"><Icon name="target" small /></button>
            </template>
            <template v-else>
              <button class="btn btn-sm" data-testid="btn-relayout" @click="forceCanvas?.relayout()"><Icon name="refresh" small /><span>{{ $t('device-graph.relayout') }}</span></button>
              <button class="btn btn-sm btn-icon" :title="$t('device-graph.fit')" data-testid="btn-fit" @click="forceCanvas?.fit()"><Icon name="target" small /></button>
            </template>
          </div>
          <ForceGraph
            v-if="view === 'force' && force"
            ref="forceCanvas"
            :data="force"
            :domain-order="domainOrder"
            :hidden-domains="hiddenDomains"
            :kinds="forceKinds"
            :selected="forceSel"
            :matches="forceMatches"
            :dim-others="!!debouncedQuery"
            :edge-name="edgeName"
            @tap="(id) => select(id, 'graph')"
            @background="select(null)"
          />
          <GraphCanvas
            v-else
            ref="canvas"
            :model="model"
            :vis="vis"
            :edges="aggEdges"
            :selected="selRep"
            :related="related"
            :matches="matches"
            :dim-others="!!debouncedQuery"
            :show-contains="edgeOn.has('contains')"
            :anchor="anchor"
            :more-text="moreText"
            :edge-name="edgeName"
            @tap="(id) => select(id, 'graph')"
            @more="showMore"
            @background="select(null)"
          />
          <div class="glegend">
            <span class="grp" data-testid="edge-filter">
              <button v-for="k in EDGE_KINDS" :key="k" class="ekey" type="button" :aria-pressed="edgeOn.has(k)" @click="toggleEdge(k)">
                <svg viewBox="0 0 26 10" :class="`ek ${EDGE_SHORT[k]}`"><path class="ln" d="M1 5H22" /><path v-if="k === 'mutex'" class="tee" d="M2 1v8M24 1v8" /><path v-else-if="k !== 'contains'" class="hd" d="M19 1.5L25 5l-6 3.5z" /></svg>
                {{ edgeName(k) }}<span v-if="graph?.summary.edge_kinds[k]" class="faint">{{ graph.summary.edge_kinds[k] }}</span>
              </button>
            </span>
            <span class="sep" />
            <span v-if="view === 'force'" class="grp" data-testid="domain-legend">
              <button v-for="x in forceDomains" :key="x.d" class="ekey dkey" type="button" :aria-pressed="!hiddenDomains.has(x.d)" :data-domain="x.d" @click="toggleDomain(x.d)">
                <i class="dsw" :style="{ background: x.color }" />{{ x.d === 'raw' ? $t('device-graph.rawDomainShort') : x.d }}<span class="faint">{{ x.n }}</span>
              </button>
            </span>
            <span v-else class="grp nodes-key">
              <span class="nkey"><svg viewBox="0 0 24 10"><rect class="nk-exp" x="1" y="1" width="22" height="8" rx="2" /></svg>{{ $t('src.explicit') }}</span>
              <span class="nkey"><svg viewBox="0 0 24 10"><rect class="nk-raw" x="1" y="1" width="22" height="8" rx="2" /></svg>{{ $t('device-graph.k.raw') }}</span>
              <span class="nkey"><svg viewBox="0 0 24 10"><rect class="nk-unk" x="1" y="1" width="22" height="8" rx="2" /></svg>{{ $t('device-graph.hasUnknown') }}</span>
            </span>
            <span class="sep" />
            <HiddenLegend />
            <span class="dg-stats ml-auto" data-testid="visible-count">
              <span v-if="view === 'force'">{{ $t('device-graph.dots') }} <b>{{ force?.nodes.length ?? 0 }}</b></span>
              <span v-else>{{ $t('device-graph.visible') }} <b>{{ visibleReal }}</b> / {{ realCount }}</span>
              <span>{{ $t('device-graph.defaultNodes') }} <b>{{ defaultCount }}</b></span>
            </span>
            <label v-if="view === 'tree'" class="check small"><input v-model="groupRaw" type="checkbox" data-testid="toggle-group-raw"><span>{{ $t('device-graph.groupRaw') }}</span></label>
            <label v-else class="check small"><input v-model="showRaw" type="checkbox" data-testid="toggle-raw"><span>{{ $t('device-graph.showRaw') }}</span></label>
            <ShowDefaultToggle v-model="showDefault" />
          </div>
        </section>

        <NodeDetail :model="model" :id="selected" :schema="schemaInfo" :profile="graph?.profile ?? null" @pick="(id) => select(id)" @line="gotoLine" />

        <section class="panel p-text" aria-label="Config text">
          <div class="tbar">
            <h3 :title="device?.source_name">{{ $t('device-graph.textTitle') }}</h3>
            <span class="dg-stats">
              <span>{{ $t('device-graph.linesN', { n: textLines.length }) }}</span>
              <span>{{ $t('device-graph.rawN') }} <b>{{ model.rawLines.size }}</b></span>
              <span class="unk">{{ $t('device-graph.unknownN') }} <b>{{ model.unknownLines.length }}</b></span>
            </span>
            <span class="lk"><i class="sw" />{{ $t('device-graph.selLines') }}</span>
            <span class="lk"><span class="gmark raw">R</span>{{ $t('device-graph.rawLegend') }}</span>
            <span class="lk"><span class="gmark unk">?</span>{{ $t('device-graph.k.unknown') }}</span>
            <span class="ml-auto row" style="gap: 4px">
              <button class="btn btn-xs btn-icon" :disabled="!model.unknownLines.length" :title="$t('device-graph.prevUnk')" data-testid="prev-unknown" @click="jumpUnknown(-1)"><Icon name="chevL" small /></button>
              <button class="btn btn-xs btn-icon" :disabled="!model.unknownLines.length" :title="$t('device-graph.nextUnk')" data-testid="next-unknown" @click="jumpUnknown(1)"><Icon name="chevR" small /></button>
            </span>
          </div>
          <ConfigText
            v-if="textLines.length"
            ref="text"
            :lines="textLines"
            :raw-lines="model.rawLines"
            :unknown-lines="unknownSet"
            :owned="model.lineOwner"
            :hl="hl"
            :sel-line="selLine"
            @pick="pickLine"
          />
          <div v-else class="empty"><p>{{ $t('device-graph.noText') }}</p></div>
        </section>
      </div>
    </div>
    <DevDelDialog v-if="showDelete && deviceId" :device-id="deviceId" @close="showDelete = false" @deleted="onDeviceDeleted" />
  </main>
</template>

<style scoped>
.dg-head { display: flex; align-items: center; gap: 14px; margin-bottom: 10px; flex-wrap: wrap; }
.dg-title { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.dg-title h1 { font-family: var(--font-mono); font-size: 18px; font-weight: 600; letter-spacing: 0; overflow-wrap: anywhere; }
.dg-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dg-stats { display: flex; gap: 14px; color: var(--ink-2); font-size: 12px; }
.dg-stats b { color: var(--ink); font-weight: 600; }
.dg-stats .unk b { color: var(--red-ink); }
.dev-sel { width: auto; height: 28px; max-width: 220px; }
.work {
  flex: 1; min-height: 0; display: grid; gap: 10px;
  grid-template-columns: minmax(0, 1fr) 348px;
  grid-template-rows: minmax(0, 1fr) 248px;
  grid-template-areas: "graph detail" "text detail";
}
@media (max-width: 1300px) { .work { grid-template-columns: minmax(0, 1fr) 300px; } }
@media (max-width: 1100px) {
  .work { grid-template-columns: minmax(0, 1fr) 270px; grid-template-rows: minmax(0, 1fr) 180px; }
  .gbar .btn span, .gbar .seg span, .glegend .grp.nodes-key, .glegend .sep { display: none; }
  .gbar .input-wrap { width: 170px; }
}
.loading-box { flex: 1; display: flex; align-items: center; justify-content: center; }
.p-graph { grid-area: graph; display: flex; flex-direction: column; overflow: hidden; }
.p-text { grid-area: text; display: flex; flex-direction: column; overflow: hidden; }
.gbar { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.gbar .input-wrap { width: 220px; }
.gbar .select { width: auto; height: 28px; }
.gbar .btn { height: 28px; }
.gbar .divider { width: 1px; height: 18px; background: var(--line); }
.glegend { display: flex; gap: 6px 14px; padding: 7px 12px; border-top: 1px solid var(--line); flex-wrap: wrap; align-items: center; font-size: 11.5px; color: var(--ink-2); background: var(--surface); }
.glegend .grp { display: inline-flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.glegend .sep { width: 1px; height: 14px; background: var(--line); }
.ekey { display: inline-flex; align-items: center; gap: 5px; border: 1px solid transparent; border-radius: 4px; padding: 1px 5px; cursor: pointer; background: none; font: inherit; color: inherit; }
.ekey:hover { border-color: var(--line); }
.ekey[aria-pressed="false"] { opacity: .4; text-decoration: line-through; }
.ekey svg, .nkey svg { width: 24px; height: 10px; }
.nkey { display: inline-flex; align-items: center; gap: 5px; }
.dkey .dsw { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.ek .ln { stroke-width: 2; fill: none; }
.ek .tee { stroke-width: 2; }
.ek.contains .ln { stroke: var(--line-strong); stroke-width: 1.4; }
.ek.ref .ln { stroke: var(--e-ref); } .ek.ref .hd { fill: var(--e-ref); }
.ek.pre .ln { stroke: var(--e-pre); } .ek.pre .hd { fill: var(--e-pre); }
.ek.side .ln { stroke: var(--e-side); stroke-dasharray: 2 3; } .ek.side .hd { fill: var(--e-side); }
.ek.mutex .ln, .ek.mutex .tee { stroke: var(--e-mutex); }
.nk-exp { fill: var(--surface); stroke: var(--line-strong); }
.nk-raw { fill: var(--surface-3); stroke: var(--line-strong); stroke-dasharray: 2 2; }
.nk-unk { fill: var(--red-soft); stroke: var(--red); }
.tbar { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--line); font-size: 12px; flex-wrap: nowrap; overflow: hidden; white-space: nowrap; }
.tbar h3 { font-size: 12.5px; }
.tbar .lk { display: inline-flex; gap: 5px; align-items: center; color: var(--ink-2); }
.tbar .sw { width: 12px; height: 12px; border-radius: 2px; display: inline-block; border: 1px solid var(--amber-line); background: var(--hl-line); }
.rt { margin-bottom: 10px; }
.rt-meta { margin-left: 10px; }
.rt-diff { margin-top: 8px; max-height: 220px; border: 1px solid var(--line); border-radius: 5px; }
.rt-diff .hunk .t { color: var(--ink-3); font-family: var(--font-ui); }
.tbl tr.clickable { cursor: pointer; }
.tbl tr.clickable:hover td { background: var(--surface-2); }
</style>
