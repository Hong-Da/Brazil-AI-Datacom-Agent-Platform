<script setup lang="ts">
/** 配置对比（预览 DevelopDocs/ui-preview/M2/compare.html）：选对比对象 → POST /compare → 计数、差异列表 / 差异图、详情、两侧原文、未识别行、报告导出。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import type { Device } from '@/views/devices/logic'
import SetupPanel from './compare/SetupPanel.vue'
import DiffList from './compare/DiffList.vue'
import DiffGraph from './compare/DiffGraph.vue'
import DiffDetail from './compare/DiffDetail.vue'
import RawPane from './compare/RawPane.vue'
import ExportDialog from './compare/ExportDialog.vue'
import {
  buildRows, countTypes, domainsOf, filterRows, groupRows, lineClass, ROW_TYPES, sideOf, stepRow, TYPE_SYM,
  type RowFilter, type RowType,
} from './compare/logic'
import { buildTree, countDesc, extrasFromGraph, initialCollapsed, prefixMap, type Extra, type GSide } from './compare/tree'
import { initialRows, mergePairs, toInterfaceMap, type MapRow } from './compare/ifmap'
import { compareBody, defaultOptions, emptySide, fromQuery, ready, swapSides, toQuery, type Mode, type Setup } from './compare/setup'
import type { CompareResult, DeviceGraph, VersionInfo } from './compare/types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// ---------------------------------------------------------------- 基础数据
const devices = ref<Device[]>([])
const profiles = ref<string[]>([])
const domains = ref<string[]>([])
const schemaDomain = ref(new Map<string, string>())
const loadError = ref('')
const versions = reactive<Record<number, VersionInfo[]>>({})
const graphs = reactive<Record<number, DeviceGraph | 'loading' | 'error'>>({})

async function loadBase(): Promise<void> {
  loadError.value = ''
  try {
    const [d, p, s] = await Promise.all([
      get<{ devices: Device[] }>('/devices'),
      get<{ profiles: { id: string }[] }>('/kb/profiles'),
      get<{ domains: { domain: string; nodes: { id: string }[] }[] }>('/kb/schema'),
    ])
    devices.value = d.devices
    profiles.value = p.profiles.map((x) => x.id)
    domains.value = s.domains.map((x) => x.domain)
    const m = new Map<string, string>()
    for (const dm of s.domains) for (const n of dm.nodes) m.set(n.id, dm.domain)
    schemaDomain.value = m
  } catch (e) {
    loadError.value = errorText(e)
  }
}
async function ensureVersions(id: number | null): Promise<void> {
  if (id === null || versions[id]) return
  try {
    versions[id] = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions
  } catch {
    versions[id] = []
  }
}
async function ensureGraph(id: number | null): Promise<void> {
  if (id === null || graphs[id]) return
  graphs[id] = 'loading'
  try {
    graphs[id] = await get<DeviceGraph>(`/devices/${id}/graph?raw=true`)
  } catch {
    graphs[id] = 'error'
  }
}
/** 对比结果两侧的配置图与原文：按版本取（不一定是设备的最新版本） */
const verGraphs = reactive<Record<number, DeviceGraph | 'loading' | 'error'>>({})
async function ensureVerGraph(id: number, vid: number | null): Promise<void> {
  if (vid === null || verGraphs[vid]) return
  verGraphs[vid] = 'loading'
  try {
    verGraphs[vid] = await get<DeviceGraph>(`/devices/${id}/graph?raw=true&version_id=${vid}`)
  } catch {
    verGraphs[vid] = 'error'
  }
}
const graphOf = (id: number | null | undefined): DeviceGraph | null => {
  const g = id === null || id === undefined ? undefined : graphs[id]
  return g && typeof g === 'object' ? g : null
}

// ---------------------------------------------------------------- 对比对象
const setup = reactive<Setup>({ mode: 'devices', a: emptySide(), b: emptySide(), opts: defaultOptions() })
const mapRows = ref<MapRow[]>([])
const mapShown = ref(false)
let mapPair = ''

const devById = (id: number | null) => devices.value.find((d) => d.id === id) ?? null
const crossVendor = computed(() => {
  const a = devById(setup.a.device)
  const b = devById(setup.b.device)
  return setup.mode === 'devices' && !!a?.vendor && !!b?.vendor && a.vendor !== b.vendor
})
const useMap = computed(() => crossVendor.value || (setup.mode === 'paste' && mapShown.value))
const interfacesOf = (id: number | null): string[] =>
  (graphOf(id)?.nodes ?? []).filter((n) => n.kind === 'object' && n.schema === 'interface').map((n) => String(n.key ?? ''))
const aIfs = computed(() => (crossVendor.value ? interfacesOf(setup.a.device) : []))
const bIfs = computed(() => (crossVendor.value ? interfacesOf(setup.b.device) : []))
const mapLoading = computed(() => crossVendor.value && [setup.a.device, setup.b.device].some((id) => id !== null && graphs[id] === 'loading'))

function setMode(m: Mode): void {
  if (setup.mode === m) return
  const keep = setup.a.device
  setup.mode = m
  setup.a = { ...emptySide(), text: setup.a.text, profile: setup.a.profile, device: m === 'paste' ? null : keep }
  setup.b = { ...emptySide(), text: setup.b.text, profile: setup.b.profile, device: m === 'versions' ? keep : null }
  if (m !== 'paste') mapRows.value = []
}
function swap(): void {
  Object.assign(setup, swapSides(setup))
  if (setup.mode === 'paste') mapRows.value = mapRows.value.map((r) => ({ ...r, a: r.b, b: r.a }))
}

// 设备变化：取版本列表；同设备两版本时默认 A = 上一版本、B = 最新；跨厂商时取两边的接口
watch(() => [setup.mode, setup.a.device, setup.b.device] as const, async ([mode, a, b]) => {
  await Promise.all([ensureVersions(a), mode === 'devices' ? ensureVersions(b) : Promise.resolve()])
  if (mode === 'versions' && a !== null && setup.a.version === null && setup.b.version === null) {
    const vs = versions[a] ?? []
    if (vs.length >= 2) {
      setup.b.version = vs[0].id
      setup.a.version = vs[1].id
    }
  }
}, { immediate: true })

watch(crossVendor, async (cv) => {
  if (!cv) return
  await Promise.all([ensureGraph(setup.a.device), ensureGraph(setup.b.device)])
}, { immediate: true })

watch(() => [crossVendor.value, aIfs.value, bIfs.value] as const, ([cv, ai, bi]) => {
  if (!cv || !ai.length) return
  const key = `${setup.a.device}>${setup.b.device}`
  if (key === mapPair) return
  const reversed = mapPair === `${setup.b.device}>${setup.a.device}`
  const carry: [string, string][] = reversed ? mapRows.value.filter((r) => r.how === 'manual').map((r) => [r.b, r.a]) : []
  mapRows.value = mergePairs(initialRows(ai, bi), carry)
  mapPair = key
})

const canRun = computed(() => ready(setup))
const currentBody = computed(() => compareBody(setup, useMap.value ? toInterfaceMap(mapRows.value) : {}))

// ---------------------------------------------------------------- 运行
interface Ran { body: Record<string, unknown>; bodyJson: string; mode: Mode; texts: { a: string; b: string }; ms: number; ifmap: number }
const result = ref<CompareResult | null>(null)
const ran = ref<Ran | null>(null)
const running = ref(false)
const runError = ref('')
const stale = computed(() => !!ran.value && ran.value.bodyJson !== JSON.stringify(currentBody.value))

async function run(): Promise<void> {
  if (!canRun.value || running.value) return
  running.value = true
  runError.value = ''
  const body = currentBody.value
  const t0 = performance.now()
  try {
    const r = await post<CompareResult>('/compare', body)
    ran.value = {
      body,
      bodyJson: JSON.stringify(body),
      mode: setup.mode,
      texts: { a: setup.a.text, b: setup.b.text },
      ms: Math.round(performance.now() - t0),
      ifmap: Object.keys((body.interface_map as Record<string, string> | undefined) ?? {}).length,
    }
    result.value = r
    filter.type = ''
    filter.q = ''
    filter.domain = ''
    filter.showNa = false
    groupCollapsed.value = new Set()
    sel.value = rows.value[0]?.id ?? null
    void router.replace({ query: toQuery(setup) })
    for (const s of [r.a, r.b]) if (s.device_id !== null) {
      void ensureVerGraph(s.device_id, s.version_id)
      void ensureVersions(s.device_id)
    }
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}

// ---------------------------------------------------------------- 结果：筛选、分组、选择
const rows = computed(() => (result.value ? buildRows(result.value) : []))
const filter = reactive<RowFilter>({ type: '', domain: '', q: '', showNa: false })
const visible = computed(() => filterRows(rows.value, filter))
const groups = computed(() => groupRows(visible.value, rows.value.filter((r) => (!filter.domain || r.domain === filter.domain)), filter.showNa || filter.type !== ''))
const counts = computed(() => countTypes(rows.value))
const resultDomains = computed(() => domainsOf(rows.value))
const groupCollapsed = ref(new Set<string>())
const sel = ref<string | null>(null)
const selRow = computed(() => rows.value.find((r) => r.id === sel.value) ?? null)
const hiddenIdentity = computed(() => result.value?.summary.hidden_identity ?? result.value?.options.hidden_identity ?? 0)
const nUnknown = computed(() => (result.value ? result.value.unknown.a.length + result.value.unknown.b.length : 0))

function pickType(tp: RowType): void {
  filter.type = filter.type === tp ? '' : tp
  if (!visible.value.some((r) => r.id === sel.value)) sel.value = visible.value[0]?.id ?? null
}
function resetFilters(): void {
  filter.type = ''
  filter.domain = ''
  filter.q = ''
}
function toggleGroup(d: string): void {
  const s = new Set(groupCollapsed.value)
  if (s.has(d)) s.delete(d)
  else s.add(d)
  groupCollapsed.value = s
}
function step(delta: number): void {
  const flat = groups.value.filter((g) => !groupCollapsed.value.has(g.domain)).flatMap((g) => g.rows)
  sel.value = stepRow(flat, sel.value, delta)
}

const VIEW_KEY = 'lmesh-compare-view'
const view = ref<'list' | 'graph'>((() => { try { return localStorage.getItem(VIEW_KEY) === 'graph' ? 'graph' : 'list' } catch { return 'list' } })())
watch(view, (v) => { try { localStorage.setItem(VIEW_KEY, v) } catch { /* 忽略 */ } })

// ---------------------------------------------------------------- 两侧名称与原文
type K = 'a' | 'b'
function sideName(k: K): string {
  const s = result.value?.[k]
  if (!s) return k.toUpperCase()
  if (s.device_id === null) return `${t('compare.raw.pasted')} ${k.toUpperCase()}`
  const v = (versions[s.device_id] ?? []).find((x) => x.id === s.version_id)
  return v ? `${s.device} #${v.seq}` : s.device ?? k.toUpperCase()
}
function fileName(k: K): string {
  const s = result.value?.[k]
  if (!s || s.device_id === null) return k === 'a' ? 'paste-a.txt' : 'paste-b.txt'
  return (versions[s.device_id] ?? []).find((x) => x.id === s.version_id)?.source_name ?? ''
}
/** 该侧（设备的某个版本）的配置图与原文 */
function latestGraph(k: K): DeviceGraph | null {
  const s = result.value?.[k]
  if (!s || s.device_id === null || s.version_id === null) return null
  const g = verGraphs[s.version_id]
  return g && typeof g === 'object' ? g : null
}
function rawText(k: K): string | null {
  if (!result.value) return null
  if (result.value[k].device_id === null) return ran.value?.texts[k] ?? null
  return latestGraph(k)?.text ?? null
}
function rawLoading(k: K): boolean {
  const s = result.value?.[k]
  if (!s || s.device_id === null || s.version_id === null) return false
  return verGraphs[s.version_id] === undefined || verGraphs[s.version_id] === 'loading'
}
function hlLines(k: K): number[] {
  return selRow.value ? sideOf(selRow.value, k).lines : []
}
function ghost(k: K): string {
  const r = selRow.value
  if (!r) return ''
  const v = sideOf(r, k)
  if (v.origin === 'default') return t('compare.raw.default', { v: v.text })
  if (v.origin === 'absent') return t('compare.raw.none')
  if (v.origin === 'derived') return t('compare.raw.derived')
  return ''
}
const unknownLines = (k: K) => (result.value?.unknown[k] ?? []).map((u) => u.line)
const rawA = ref<InstanceType<typeof RawPane>>()
const rawB = ref<InstanceType<typeof RawPane>>()
function jump(k: K, line: number): void {
  ;(k === 'a' ? rawA : rawB).value?.scrollTo(line, true)
}

// ---------------------------------------------------------------- 差异图
const gSide = ref<GSide>('both')
const gOnly = ref<'diff' | 'all'>('diff')
const treeCollapsed = ref(new Set<string>())
const graphLoading = computed(() => gOnly.value === 'all' && (['a', 'b'] as K[]).some((k) => rawLoading(k)))
const extras = computed<Extra[]>(() => {
  if (gOnly.value !== 'all' || !result.value) return []
  const pm = prefixMap(rows.value)
  const dom = (ran.value?.body.domain as string | undefined) ?? ''
  const out: Extra[] = []
  for (const k of ['a', 'b'] as K[]) {
    if ((gSide.value === 'a' && k === 'b') || (gSide.value === 'b' && k === 'a')) continue
    const g = latestGraph(k)
    if (g) out.push(...extrasFromGraph(g.nodes, schemaDomain.value, pm, filter.domain || dom))
  }
  return out
})
const graphNote = computed(() => {
  if (gOnly.value !== 'all') return ''
  if (graphLoading.value) return t('compare.graph.loadingAll')
  const need = (['a', 'b'] as K[]).filter((k) => !((gSide.value === 'a' && k === 'b') || (gSide.value === 'b' && k === 'a')))
  return need.some((k) => !latestGraph(k)) ? t('compare.graph.allNoGraph') : ''
})
const tree = computed(() => buildTree(visible.value, `${sideName('a')} ⇢ ${sideName('b')}`, extras.value))
watch(tree, (tr) => { treeCollapsed.value = initialCollapsed(tr) })
const bigTree = computed(() => treeCollapsed.value.size > 0 && tree.value.root.children.every((c) => treeCollapsed.value.has(c.key)))
function toggleTree(key: string): void {
  const s = new Set(treeCollapsed.value)
  if (s.has(key)) {
    s.delete(key)
    // 展开的分支很大时，下一级先收起，逐级展开
    const n = tree.value.byKey.get(key)
    if (n && countDesc(n) > 120) for (const c of n.children) if (c.children.length) s.add(c.key)
  } else s.add(key)
  treeCollapsed.value = s
}
// 选中项在收起的分支里时展开它的上级
watch(sel, (id) => {
  const key = id ? tree.value.byRow.get(id) : undefined
  let n = key ? tree.value.byKey.get(key)?.parent : null
  if (!n) return
  const s = new Set(treeCollapsed.value)
  let changed = false
  while (n) {
    if (s.delete(n.key)) changed = true
    n = n.parent
  }
  if (changed) treeCollapsed.value = s
})

// ---------------------------------------------------------------- 报告
const showExport = ref(false)

// ---------------------------------------------------------------- 启动：URL 参数
onMounted(async () => {
  await loadBase()
  const q = fromQuery(route.query)
  if (!q) return
  Object.assign(setup, q.setup)
  if (q.complete) {
    await ensureVersions(setup.a.device)
    if (ready(setup)) await run()
  }
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.dev') }}</span><span class="sep">/</span><span>{{ $t('nav.compare') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.compare') }}</h1>
          <p class="ph-sub">{{ $t('compare.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" :disabled="!result" data-testid="open-export" @click="showExport = true"><Icon name="report" small /><span>{{ $t('compare.export') }}</span></button>
        </div>
      </div>

      <div v-if="loadError" class="notice err" data-testid="load-error">
        <Icon name="err" /><div class="grow">{{ loadError }}</div>
        <button class="btn btn-sm" @click="loadBase">{{ $t('c.retry') }}</button>
      </div>

      <SetupPanel
        v-model:map-rows="mapRows"
        :setup="setup" :devices="devices" :versions="versions" :profiles="profiles" :domains="domains"
        :map-shown="mapShown" :map-loading="mapLoading" :a-ifs="aIfs" :b-ifs="bIfs" :running="running" :can-run="canRun"
        @run="run" @swap="swap" @mode="setMode" @toggle-map="mapShown = !mapShown"
      />

      <div v-if="runError" class="notice err mt12" data-testid="run-error"><Icon name="err" /><div class="grow">{{ runError }}</div></div>

      <template v-if="result">
        <div class="res-head">
          <h2>{{ $t('compare.res.title') }}</h2>
          <span class="mono lbl">{{ sideName('a') }} ⇢ {{ sideName('b') }}</span>
          <span class="meta">
            <span v-if="result.a.kb_version">{{ $t('compare.res.kb', { v: result.a.kb_version }) }}</span>
            <span>{{ result.a.profile === result.b.profile ? result.a.profile : `${result.a.profile} / ${result.b.profile}` }}</span>
            <span v-if="ran?.body.domain">{{ $t('compare.res.domain', { d: ran.body.domain }) }}</span>
            <span v-if="ran?.ifmap">{{ $t('compare.res.ifmap', { n: ran.ifmap }) }}</span>
            <span v-if="hiddenIdentity" data-testid="hidden-identity">{{ $t('compare.res.hidden', { n: hiddenIdentity }) }}</span>
            <span>{{ $t('compare.res.ms', { n: ran?.ms ?? 0 }) }}</span>
          </span>
        </div>
        <div v-if="stale" class="notice info" data-testid="stale-result"><Icon name="info" /><div class="grow">{{ $t('compare.res.stale') }}</div></div>

        <section v-if="result.equal && !result.default_only.length" class="panel" data-testid="compare-equal">
          <div class="empty cmp-empty">
            <svg class="art" viewBox="0 0 120 84" aria-hidden="true"><rect x="10" y="14" width="42" height="56" rx="5" fill="var(--surface-2)" stroke="var(--line-strong)" /><rect x="68" y="14" width="42" height="56" rx="5" fill="var(--surface-2)" stroke="var(--line-strong)" /><path d="M54 36h12M54 46h12" stroke="var(--teal)" stroke-width="2.5" stroke-linecap="round" /><path d="M18 26h26M18 34h20M18 42h24M76 26h26M76 34h20M76 42h24" stroke="var(--line-strong)" stroke-width="2" stroke-linecap="round" /></svg>
            <h3>{{ $t('compare.equalTitle') }}</h3>
            <p>{{ $t('compare.equalText') }}</p>
          </div>
        </section>

        <template v-else>
          <div class="tally" role="group" aria-label="Summary" data-testid="tally">
            <button
              v-for="tp in ROW_TYPES" :key="tp" type="button" :class="{ eqv: tp === 'na' }" :aria-pressed="filter.type === tp"
              :style="{ '--c': `var(--d-${{ added: 'add', removed: 'del', modified: 'mod', renamed: 'ren', na: 'na' }[tp]})` }"
              :data-testid="'tally-' + tp" @click="pickType(tp)"
            >
              <span class="n">{{ counts[tp] }}</span><span class="k" :data-sym="TYPE_SYM[tp]">{{ $t('compare.type.' + tp) }}</span>
            </button>
          </div>

          <div class="fold" data-testid="fold-notice">
            <span class="eqsign">=</span>
            <p>{{ $t('compare.fold.text') }}<template v-if="result.default_only.length"> {{ $t('compare.fold.na', { n: result.default_only.length }) }}</template></p>
            <button v-if="result.default_only.length" class="btn btn-sm" data-testid="fold-toggle" @click="filter.showNa = !filter.showNa">
              {{ filter.showNa ? $t('compare.fold.hide') : $t('compare.fold.show', { n: result.default_only.length }) }}
            </button>
          </div>

          <div class="rbar">
            <div class="tabs" role="tablist">
              <button role="tab" :aria-selected="view === 'list'" data-testid="view-list" @click="view = 'list'"><Icon name="filter" small />{{ $t('compare.view.list') }}</button>
              <button role="tab" :aria-selected="view === 'graph'" data-testid="view-graph" @click="view = 'graph'"><Icon name="graph" small />{{ $t('compare.view.graph') }}</button>
            </div>
            <select v-model="filter.domain" class="select" data-testid="filter-domain">
              <option value="">{{ $t('compare.allDomains') }}</option>
              <option v-for="d in resultDomains" :key="d" :value="d">{{ d }}</option>
            </select>
            <label class="input-wrap"><Icon name="search" small /><input v-model="filter.q" class="input" type="search" :placeholder="$t('compare.search')" data-testid="filter-q"></label>
            <button v-if="filter.type" class="btn btn-ghost btn-sm" @click="filter.type = ''"><Icon name="x" small />{{ $t('compare.clearType') }}</button>
          </div>

          <div class="work">
            <section class="panel p-main">
              <DiffList
                v-if="view === 'list'"
                :groups="groups" :sel="sel" :collapsed="groupCollapsed" :a-label="sideName('a')" :b-label="sideName('b')"
                @select="sel = $event" @step="step" @toggle="toggleGroup" @show-na="filter.showNa = true" @reset="resetFilters"
              />
              <DiffGraph
                v-else
                v-model:side="gSide" v-model:only="gOnly"
                :tree="tree" :sel="sel" :collapsed="treeCollapsed" :note="graphNote" :big="bigTree"
                @select="sel = $event" @toggle="toggleTree"
                @expand-all="treeCollapsed = new Set()" @collapse-all="treeCollapsed = new Set(tree.root.children.map((c) => c.key))"
              />
            </section>
            <aside class="panel p-detail">
              <DiffDetail
                :row="selRow" :rows="rows" :a-label="sideName('a')" :b-label="sideName('b')"
                :a-profile="result.a.profile ?? ''" :b-profile="result.b.profile ?? ''"
                :a-graph="latestGraph('a') ? result.a.device_id : null" :b-graph="latestGraph('b') ? result.b.device_id : null"
                @select="sel = $event" @jump="jump"
              />
            </aside>
            <section class="panel p-raw" aria-label="Original text">
              <RawPane
                ref="rawA" k="A" :label="sideName('a')" :fname="fileName('a')" :text="rawText('a')" :loading="rawLoading('a')"
                :missing="$t('compare.raw.noText')" :hl="hlLines('a')" :cls="selRow ? lineClass(selRow.type, 'a') : ''" :ghost="ghost('a')" :unknown="unknownLines('a')"
              />
              <RawPane
                ref="rawB" k="B" :label="sideName('b')" :fname="fileName('b')" :text="rawText('b')" :loading="rawLoading('b')"
                :missing="$t('compare.raw.noText')" :hl="hlLines('b')" :cls="selRow ? lineClass(selRow.type, 'b') : ''" :ghost="ghost('b')" :unknown="unknownLines('b')"
              />
            </section>
          </div>
        </template>

        <section v-if="nUnknown" class="panel mt12" data-testid="unknown-block">
          <div class="panel-h">
            <h3>{{ $t('compare.unknown.title') }}</h3>
            <span class="meta">
              <span v-for="k in (['a', 'b'] as const)" :key="k">{{ $t('compare.unknown.side', { s: k.toUpperCase(), n: result.unknown[k].length }) }}</span>
            </span>
            <router-link class="btn btn-sm ml-auto" :to="{ name: 'unknown-lines' }">{{ $t('compare.unknown.goto') }}</router-link>
          </div>
          <div class="panel-b">
            <p class="small muted unk-sub">{{ $t('compare.unknown.sub') }}</p>
            <div class="unk-grid">
              <div v-for="k in (['a', 'b'] as const)" :key="k" class="unk-col">
                <div v-for="u in result.unknown[k]" :key="k + u.line" class="unk-line" role="button" tabindex="0" @click="jump(k, u.line)" @keydown.enter="jump(k, u.line)">
                  <span class="mono faint">{{ k.toUpperCase() }}:{{ u.line }}</span><span class="mono">{{ u.text }}</span>
                  <span v-if="u.owner" class="faint small trunc" :title="u.owner">{{ u.owner }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>

    <ExportDialog
      v-if="showExport" :body="ran?.body ?? null" :a-name="result?.a.label ?? 'A'" :b-name="result?.b.label ?? 'B'"
      @close="showExport = false"
    />
  </main>
</template>

<style scoped>
.mt12 { margin-top: 12px; }
.res-head { display: flex; align-items: center; gap: 12px; margin: 18px 0 10px; flex-wrap: wrap; }
.res-head h2 { font-size: 15px; }
.res-head .lbl { font-size: 12.5px; }
.res-head .meta { color: var(--ink-3); font-size: 12px; display: flex; gap: 10px; flex-wrap: wrap; }
.tally { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; }
.tally button { all: unset; box-sizing: border-box; padding: 10px 14px; border-left: 1px solid var(--line); cursor: pointer; display: flex; flex-direction: column; gap: 2px; position: relative; min-width: 0; }
.tally button:first-child { border-left: 0; }
.tally button:hover { background: var(--surface-2); }
.tally button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.tally button[aria-pressed="true"] { background: var(--surface-3); }
.tally button[aria-pressed="true"]::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--c); }
.tally .n { font: 600 22px/1.2 var(--font-display); color: var(--ink); }
.tally .k { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tally .k::before { content: attr(data-sym); font: 700 12px var(--font-mono); color: var(--c); width: 10px; }
.tally .eqv { background: repeating-linear-gradient(135deg, transparent 0 6px, color-mix(in srgb, var(--line) 45%, transparent) 6px 7px); }
.tally .eqv .n { color: var(--ink-2); }
.fold { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 12px; align-items: center; margin-top: 10px; padding: 10px 14px; border: 1px dashed var(--line-strong); border-radius: 6px; background: var(--surface); }
.fold .eqsign { width: 30px; height: 30px; border-radius: 6px; border: 1.5px dashed var(--ink-3); display: inline-flex; align-items: center; justify-content: center; font: 700 16px var(--font-mono); color: var(--ink-2); }
.fold p { color: var(--ink-2); }
.rbar { display: flex; align-items: center; gap: 8px; margin: 12px 0 10px; flex-wrap: wrap; }
.rbar .tabs { margin: 0; border: 0; }
.rbar .input-wrap { width: 220px; }
.rbar .select { width: auto; height: 30px; }
.work { display: grid; gap: 10px; grid-template-columns: minmax(0, 1fr) 380px; grid-template-rows: minmax(360px, 56vh) 300px; grid-template-areas: "main detail" "raw raw"; }
.p-main { grid-area: main; display: flex; flex-direction: column; overflow: hidden; }
.p-detail { grid-area: detail; display: flex; flex-direction: column; overflow: hidden; }
.p-raw { grid-area: raw; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); overflow: hidden; }
.p-raw > .rawcol + .rawcol { border-left: 1px solid var(--line); }
.cmp-empty { padding: 50px 20px; }
.unk-sub { margin-bottom: 8px; }
.unk-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.unk-col { min-width: 0; max-height: 240px; overflow: auto; }
.unk-line { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 8px; padding: 3px 6px; font-size: 12px; border-radius: 4px; cursor: pointer; align-items: center; }
.unk-line:hover { background: var(--surface-2); }
.unk-line .trunc { max-width: 200px; }
@media (max-width: 1300px) { .work { grid-template-columns: minmax(0, 1fr) 320px; } }
@media (max-width: 1100px) {
  .work { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(360px, 56vh) auto 300px; grid-template-areas: "main" "detail" "raw"; }
  .tally { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .tally button:nth-child(4) { border-left: 0; }
  .tally button:nth-child(n+4) { border-top: 1px solid var(--line); }
  .unk-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
