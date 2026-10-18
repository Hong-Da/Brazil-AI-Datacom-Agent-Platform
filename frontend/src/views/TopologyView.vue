<script setup lang="ts">
/**
 * 拓扑视图与跨设备一致性（预览 DevelopDocs/ui-preview/M4/topology.html，一致性是同一页的另一个视图）：
 * 选设备集（已导入设备，可加上传的配置文件）→ POST /consistency → 三层拓扑图（同网段链路、BGP 会话、伪线等）、
 * 一致性问题列表；点链路看推导依据、两端事实、问题与两端配置，点问题回到拓扑图并高亮两端设备与链路。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import { errorText, get, post } from '@/api'
import { useTerms } from '@/stores/terms'
import { saveText, toCsv } from '@/views/profiles/csv'
import type { Device } from '@/views/devices/logic'
import TopologyMap from './m4/TopologyMap.vue'
import { keyText } from './m4/texts'
import { blockOf, lines as splitLines, snippet, stamp } from './m4/common'
import {
  factRows, filterFindings, findingsCsv, groupLinks, groupOfLink, groupsOf, protocols, shortIf, statusOf,
  type ConsistencyResult, type Finding, type Group, type Link, type SevFilter, type TopoNode,
} from './m4/topology'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()

const view = computed<'map' | 'consistency'>(() => (route.name === 'consistency' ? 'consistency' : 'map'))
function setView(v: 'map' | 'consistency'): void {
  void router.replace({ name: v === 'map' ? 'topology' : 'consistency', query: route.query })
}

// ---------------------------------------------------------------- 设备集
const devices = ref<Device[]>([])
const picked = ref<Set<number>>(new Set())
const includeImported = ref(true)
const uploads = ref<{ name: string; text: string }[]>([])
const pickOpen = ref(false)
const loadError = ref('')
const allPicked = computed(() => devices.value.length > 0 && picked.value.size === devices.value.length)
const setLabel = computed(() => {
  if (!includeImported.value || !picked.value.size) return t('topology.noImported')
  return allPicked.value ? t('topology.allImported', { n: devices.value.length }) : t('topology.someImported', { n: picked.value.size, total: devices.value.length })
})
function toggle(id: number): void {
  const s = new Set(picked.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  picked.value = s
}
async function onFiles(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  const add = await Promise.all(files.map(async (f) => ({ name: f.name, text: await f.text() })))
  const keep = uploads.value.filter((u) => !add.some((a) => a.name === u.name))
  uploads.value = [...keep, ...add]
  input.value = ''
}

// ---------------------------------------------------------------- 推导
const running = ref(false)
const runError = ref('')
const result = ref<ConsistencyResult | null>(null)
const canRun = computed(() => uploads.value.length > 0 || (includeImported.value && picked.value.size > 0))

async function run(): Promise<void> {
  if (!canRun.value || running.value) return
  running.value = true
  runError.value = ''
  try {
    const ids = includeImported.value ? [...picked.value] : []
    result.value = await post<ConsistencyResult>('/consistency', { configs: uploads.value, device_ids: ids })
    texts.value = {}
    if (sel.value && !selValid()) sel.value = null
    const q: Record<string, string> = {}
    if (includeImported.value && !allPicked.value) q.devices = ids.join(',')
    void router.replace({ query: q })
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}

const nodes = computed<TopoNode[]>(() => result.value?.nodes ?? [])
const groups = computed<Group[]>(() => groupLinks(result.value?.links ?? []))
const byLink = computed(() => groupOfLink(groups.value))
const nodeOf = (id: string) => nodes.value.find((n) => n.id === id) ?? null
const findings = computed<Finding[]>(() => result.value?.findings ?? [])
const extra = computed(() => result.value?.texts)
const ftext = (f: Finding, k: 'message' | 'suggestion') => keyText(f[k], lang.value, extra.value)
const sev = computed(() => result.value?.summary.by_severity ?? { error: 0, warning: 0, info: 0 })
const topo = computed(() => result.value?.summary.topology)

// ---------------------------------------------------------------- 选择
const layers = reactive({ phy: true, bgp: true, l2: true, ifn: false, iso: false })
/** 图上的设备：默认不画没有任何链路的设备（它们仍在列表与统计中） */
const mapNodes = computed(() => (layers.iso ? nodes.value : nodes.value.filter((n) => groups.value.some((g) => g.a === n.id || g.b === n.id))))
const sel = ref<{ k: 'link' | 'dev'; id: string } | null>(null)
const selGroup = computed(() => (sel.value?.k === 'link' ? groups.value.find((g) => g.id === sel.value!.id) ?? null : null))
const selNode = computed(() => (sel.value?.k === 'dev' ? nodeOf(sel.value.id) : null))
function selValid(): boolean {
  if (!sel.value) return true
  return sel.value.k === 'link' ? groups.value.some((g) => g.id === sel.value!.id) : !!nodeOf(sel.value.id)
}
function pick(k: 'link' | 'dev', id: string): void {
  sel.value = { k, id }
}
function goFinding(f: Finding): void {
  const g = byLink.value.get(f.link)
  if (g) sel.value = { k: 'link', id: g.id }
  setView('map')
}
const groupFindings = computed(() => {
  const g = selGroup.value
  if (!g) return []
  const ids = new Set(g.links.map((l) => l.id))
  return filterFindings(findings.value.filter((f) => ids.has(f.link)), '')
})

// 两端配置：已导入设备取版本原文，上传的取上传文本
const texts = ref<Record<string, string[]>>({})
async function loadText(n: TopoNode | null): Promise<void> {
  if (!n || texts.value[n.id]) return
  let txt = ''
  if (n.device_id !== null && n.version_id !== null) {
    try { txt = (await get<{ text: string }>(`/devices/${n.device_id}/versions/${n.version_id}/text`)).text } catch { txt = '' }
  } else txt = uploads.value.find((u) => u.name === n.source)?.text ?? ''
  texts.value = { ...texts.value, [n.id]: splitLines(txt) }
}
watch(selGroup, (g) => {
  if (!g) return
  void loadText(nodeOf(g.a))
  void loadText(nodeOf(g.b))
})
/** 一端的配置片段：接口块（有接口时），再加上问题涉及的行。 */
function endLines(dev: string, iface: string): ({ no: number; text: string; bad: boolean } | null)[] {
  const all = texts.value[dev]
  if (!all) return []
  const bad = new Set<number>()
  for (const f of groupFindings.value) for (const e of f.ends) if (e.device === dev) e.lines.forEach((l) => bad.add(l))
  const blk = iface ? blockOf(all, `interface ${iface}`) : []
  const inBlk = new Set(blk.map((b) => b.no))
  const extraLines = snippet(all, [...bad].filter((n) => !inBlk.has(n)), 0)
  const out: ({ no: number; text: string; bad: boolean } | null)[] = blk.map((b) => ({ ...b, bad: bad.has(b.no) }))
  if (extraLines.length) {
    if (out.length) out.push(null)
    for (const x of extraLines) out.push(x ? { ...x, bad: bad.has(x.no) } : null)
  }
  return out
}

// ---------------------------------------------------------------- 一致性列表
const sevFilter = ref<SevFilter>('')
const devFilter = ref('')
const rows = computed(() => filterFindings(findings.value, sevFilter.value, devFilter.value))
function exportCsv(): void {
  saveText(`consistency-${stamp()}.csv`, toCsv(findingsCsv(rows.value, ftext)))
}

const linkTitle = (l: Link) => `${t(`topology.type.${l.type}`)}${l.segment ? ` · ${l.segment}` : ''}`
const sevIcon = (s: string) => (s === 'error' ? 'err' : s === 'warning' ? 'warn' : 'info')
const bgpCount = computed(() => groups.value.filter((g) => g.kind === 'bgp').length)
const phyCount = computed(() => groups.value.filter((g) => g.kind === 'phy').length)
const map = ref<InstanceType<typeof TopologyMap>>()

onMounted(async () => {
  try {
    devices.value = [...(await get<{ devices: Device[] }>('/devices')).devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  } catch (e) {
    loadError.value = errorText(e)
  }
  const want = String(route.query.devices ?? '').split(',').filter((x) => /^\d+$/.test(x)).map(Number)
  picked.value = new Set(want.length ? want.filter((id) => devices.value.some((d) => d.id === id)) : devices.value.map((d) => d.id))
  if (canRun.value) void run()
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.ana') }}</span><span class="sep">/</span><span>{{ view === 'map' ? $t('nav.topology') : $t('nav.consistency') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ view === 'map' ? $t('topology.title') : $t('topology.titleCons') }}</h1>
          <p class="ph-sub">{{ $t('topology.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-sm" type="button" :disabled="!result" data-testid="topo-csv" @click="exportCsv"><Icon name="download" small />{{ $t('topology.exportCsv') }}</button>
        </div>
      </div>
      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div></div>

      <section class="panel setbar" data-testid="topo-setup">
        <span class="lbl">{{ $t('topology.deviceSet') }}</span>
        <div class="pickwrap">
          <button class="btn btn-sm" type="button" data-testid="topo-pick" @click="pickOpen = !pickOpen"><Icon name="server" small />{{ setLabel }}<Icon :name="pickOpen ? 'chevD' : 'chevR'" small /></button>
          <div v-if="pickOpen" class="pickpop" data-testid="topo-pickpop">
            <label class="check"><input v-model="includeImported" type="checkbox" data-testid="topo-include"><span>{{ $t('topology.allImported', { n: devices.length }) }}</span></label>
            <div class="row" style="gap: 8px"><button class="link-btn" type="button" @click="picked = new Set(devices.map((d) => d.id))">{{ $t('topology.pickAll') }}</button><button class="link-btn" type="button" @click="picked = new Set()">{{ $t('topology.pickNone') }}</button></div>
            <div class="picklist">
              <label v-for="d in devices" :key="d.id" class="check"><input type="checkbox" :checked="picked.has(d.id)" :disabled="!includeImported" @change="toggle(d.id)"><DevChip :name="d.name" :vendor="d.vendor" /></label>
            </div>
          </div>
        </div>
        <label class="btn btn-sm upl"><Icon name="upload" small />{{ $t('topology.upload') }}<input type="file" multiple accept=".cfg,.txt,.conf,.log" data-testid="topo-upload" @change="onFiles"></label>
        <span v-for="u in uploads" :key="u.name" class="stchip">{{ u.name }}<button type="button" :aria-label="u.name" @click="uploads = uploads.filter((x) => x.name !== u.name)"><Icon name="x" small /></button></span>
        <span v-if="uploads.length" class="small faint">{{ $t('topology.uploadHint') }}</span>
        <button class="btn btn-primary btn-sm ml-auto" type="button" :disabled="!canRun || running" data-testid="topo-run" @click="run"><Icon name="refresh" small />{{ running ? $t('topology.running') : result ? $t('topology.rebuild') : $t('topology.run') }}</button>
      </section>

      <div v-if="runError" class="notice err mt12" data-testid="topo-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
      <div v-if="!result && !runError" class="empty mt16"><Icon name="network" /><h3>{{ running ? $t('c.loading') : $t('topology.emptyTitle') }}</h3><p v-if="!running">{{ $t('topology.emptyText') }}</p></div>

      <template v-if="result">
        <div class="tabs mt12" role="tablist">
          <button type="button" role="tab" :aria-selected="view === 'map'" data-testid="topo-tab-map" @click="setView('map')"><Icon name="network" small />{{ $t('topology.tabMap') }}</button>
          <button type="button" role="tab" :aria-selected="view === 'consistency'" data-testid="topo-tab-cons" @click="setView('consistency')"><Icon name="link" small />{{ $t('topology.tabCons') }}<span v-if="sev.error" class="count bad">{{ sev.error }}</span></button>
        </div>
        <div class="tstrip" data-testid="topo-strip">
          <div><div class="v">{{ nodes.length }}</div><div class="k">{{ $t('topology.s.devices') }}<span v-if="topo?.unresolved" class="faint">{{ $t('topology.s.unresolved', { n: topo.unresolved }) }}</span></div></div>
          <div><div class="v">{{ phyCount }}</div><div class="k">{{ $t('topology.s.links') }}</div></div>
          <div><div class="v">{{ bgpCount }}</div><div class="k">{{ $t('topology.s.bgp') }}</div></div>
          <div><div class="v" style="color: var(--red-ink)">{{ sev.error }}</div><div class="k">{{ $t('topology.s.errors') }}</div></div>
          <div><div class="v" style="color: var(--amber-ink)">{{ sev.warning + sev.info }}</div><div class="k">{{ $t('topology.s.warnings') }}<span class="faint">{{ $t('topology.s.rules', { n: result.rules_loaded }) }}</span></div></div>
        </div>

        <!-- ===================== 拓扑图 ===================== -->
        <div v-show="view === 'map'" class="tw">
          <section class="panel mapp" aria-label="Topology map">
            <div class="tbar2">
              <span class="lbl">{{ $t('topology.layers') }}</span>
              <div class="layers">
                <label v-for="k in (['phy', 'bgp', 'l2', 'ifn', 'iso'] as const)" :key="k" class="check"><input v-model="layers[k]" type="checkbox" :data-testid="`topo-layer-${k}`"><span>{{ $t(`topology.l.${k}`) }}</span></label>
              </div>
              <button class="btn btn-xs btn-ghost ml-auto" type="button" @click="map?.fit()"><Icon name="expand" small />{{ $t('topology.fit') }}</button>
            </div>
            <TopologyMap ref="map" :nodes="mapNodes" :groups="groups" :layers="layers" :sel="sel" @pick="pick" @clear="sel = null" />
            <div class="mapf">
              <span><svg viewBox="0 0 26 10"><path d="M1 5h24" class="topo-link st-ok" style="stroke-width: 3" /></svg>{{ $t('topology.lg.ok') }}</span>
              <span><svg viewBox="0 0 26 10"><path d="M1 5h24" class="topo-link st-warn" style="stroke-width: 3" /></svg>{{ $t('topology.lg.warn') }}</span>
              <span><svg viewBox="0 0 26 10"><path d="M1 5h24" class="topo-link st-bad" style="stroke-width: 3" /></svg>{{ $t('topology.lg.bad') }}</span>
              <span><svg viewBox="0 0 26 10"><path d="M1 5h24" class="topo-bgp" /></svg>{{ $t('topology.lg.bgp') }}</span>
              <span><svg viewBox="0 0 26 10"><path d="M1 5h24" class="topo-link st-na" style="stroke-width: 1.6" /></svg>{{ $t('topology.lg.l2') }}</span>
              <span class="ml-auto faint">{{ $t('topology.lg.hint') }}</span>
            </div>
          </section>

          <section class="panel side" aria-label="Details" data-testid="topo-side">
            <!-- 链路 -->
            <template v-if="selGroup">
              <div class="panel-h"><h3>{{ $t('topology.link') }}</h3><span class="ls" :class="selGroup.status">{{ $t(`topology.lg.${selGroup.status}`) }}</span><span class="meta mono">{{ selGroup.segment }}</span></div>
              <div class="sb" data-testid="topo-link">
                <div class="ends">
                  <div class="e"><DevChip :name="selGroup.a" :vendor="nodeOf(selGroup.a)?.family" /><code>{{ selGroup.ai || '—' }}</code><code>{{ selGroup.links[0].a.address }}</code></div>
                  <div class="mid">⟷</div>
                  <div class="e"><DevChip :name="selGroup.b" :vendor="nodeOf(selGroup.b)?.family" /><code>{{ selGroup.bi || '—' }}</code><code>{{ selGroup.links[0].b.address }}</code></div>
                </div>
                <div>
                  <div class="sec-k">{{ $t('topology.basis') }}</div>
                  <div class="basisrow">
                    <span v-for="l in selGroup.links" :key="l.id" class="basis" :title="l.basis.detail">{{ linkTitle(l) }} <b>{{ l.basis.rule }}</b> · {{ $t(`topology.conf.${l.confidence}`) }}<span v-if="l.severity" class="dot" :class="statusOf(l.severity)" /></span>
                  </div>
                  <p v-if="selGroup.links[0].basis.detail" class="small faint mt8 mono">{{ selGroup.links[0].basis.detail }}</p>
                </div>
                <div>
                  <div class="sec-k">{{ $t('topology.issues') }} {{ groupFindings.length }}</div>
                  <p v-if="!groupFindings.length" class="small muted">{{ $t('topology.noIssues') }}</p>
                  <div v-for="f in groupFindings" :key="f.id" class="fitem" :class="f.severity">
                    <div class="fh"><span class="sev" :class="f.severity"><Icon :name="sevIcon(f.severity)" small />{{ $t(`topology.sev.${f.severity}`) }}</span><code class="small faint">{{ f.rule }}</code></div>
                    <div class="ft">{{ ftext(f, 'message') }}</div>
                    <div class="fs">{{ ftext(f, 'suggestion') }}</div>
                  </div>
                </div>
                <div v-for="l in selGroup.links.filter((x) => factRows(x).length)" :key="l.id + 'f'">
                  <div class="sec-k">{{ $t('topology.facts') }} · {{ $t(`topology.type.${l.type}`) }}</div>
                  <table class="ck">
                    <thead><tr><th>{{ $t('topology.fact') }}</th><th>{{ l.a.device }}</th><th>{{ l.b.device }}</th></tr></thead>
                    <tbody><tr v-for="r in factRows(l)" :key="r.k" :class="{ 'st-bad': r.diff }"><td>{{ r.k }}</td><td class="v">{{ r.a }}</td><td class="v">{{ r.b }}</td></tr></tbody>
                  </table>
                </div>
                <div>
                  <div class="sec-k">{{ $t('topology.ends') }}</div>
                  <div class="cfg2">
                    <div v-for="end in [{ d: selGroup.a, i: selGroup.ai }, { d: selGroup.b, i: selGroup.bi }]" :key="end.d">
                      <div class="cap"><DevChip :name="end.d" :vendor="nodeOf(end.d)?.family" /><span v-if="nodeOf(end.d)?.device_id === null" class="faint">{{ $t('topology.notImported') }}</span></div>
                      <div class="code" :data-testid="`topo-end-${end.d}`">
                        <template v-for="(x, i) in endLines(end.d, end.i)" :key="i">
                          <div v-if="x" class="l" :class="{ bad: x.bad }"><span class="n">{{ x.no }}</span><span class="g" /><span class="t">{{ x.text }}</span></div>
                          <div v-else class="l gap"><span class="n">⋯</span><span class="g" /><span class="t" /></div>
                        </template>
                        <div v-if="!endLines(end.d, end.i).length" class="empty" style="padding: 14px"><p>{{ $t('topology.noBlock') }}</p></div>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="acts">
                  <template v-for="d in [selGroup.a, selGroup.b]" :key="d">
                    <router-link v-if="nodeOf(d)?.device_id" class="btn btn-sm" :to="{ name: 'device-graph', params: { id: String(nodeOf(d)!.device_id) } }"><Icon name="graph" small />{{ $t('topology.openGraph', { d }) }}</router-link>
                    <router-link v-if="nodeOf(d)?.device_id && selGroup.status !== 'ok'" class="btn btn-sm" :to="{ name: 'change', query: { device: String(nodeOf(d)!.device_id), mode: 'paste' } }"><Icon name="branch" small />{{ $t('topology.toChange', { d }) }}</router-link>
                  </template>
                </div>
              </div>
            </template>
            <!-- 设备 -->
            <template v-else-if="selNode">
              <div class="panel-h"><h3><DevChip :name="selNode.id" :vendor="selNode.family" /></h3><span class="meta">{{ $t('topology.interfacesN', { n: selNode.interfaces }) }}</span></div>
              <div class="sb" data-testid="topo-dev">
                <dl class="kvs">
                  <dt>{{ $t('topology.profile') }}</dt><dd>{{ selNode.profile }}</dd>
                  <dt>{{ $t('topology.loopbacks') }}</dt><dd>{{ selNode.loopbacks.join(', ') || '—' }}</dd>
                  <dt>{{ $t('topology.lsrId') }}</dt><dd>{{ selNode.lsr_id ?? '—' }}</dd>
                  <dt>{{ $t('topology.asn') }}</dt><dd>{{ selNode.asn ?? '—' }}</dd>
                  <dt>{{ $t('topology.source') }}</dt><dd>{{ selNode.source }}</dd>
                </dl>
                <div>
                  <div class="sec-k">{{ $t('topology.linksOf', { n: groupsOf(groups, selNode.id).length }) }}</div>
                  <div v-for="g in groupsOf(groups, selNode.id)" :key="g.id" class="lrow" @click="pick('link', g.id)">
                    <span class="ls" :class="g.status">{{ $t(`topology.lg.${g.status}`) }}</span>
                    <code>{{ shortIf(g.a === selNode.id ? g.ai : g.bi) || $t(`topology.type.${g.links[0].type}`) }}</code><span>→</span>{{ g.a === selNode.id ? g.b : g.a }}
                    <code class="ml-auto">{{ g.kind === 'phy' ? g.segment : $t(`topology.type.${g.links[0].type}`) }}{{ protocols(g).length ? ` · ${protocols(g).length}` : '' }}</code>
                  </div>
                </div>
                <div v-if="result.unresolved.some((u) => u.device === selNode!.id)">
                  <div class="sec-k">{{ $t('topology.unresolved') }}</div>
                  <div v-for="(u, i) in result.unresolved.filter((x) => x.device === selNode!.id)" :key="i" class="small mono">{{ $t(`topology.type.${u.type}`) }} · {{ u.address }} · {{ terms.describe(u.node) }}</div>
                </div>
                <div class="acts">
                  <router-link v-if="selNode.device_id" class="btn btn-sm btn-primary" :to="{ name: 'device-graph', params: { id: String(selNode.device_id) } }"><Icon name="graph" small />{{ $t('topology.openGraph', { d: selNode.id }) }}</router-link>
                  <router-link v-if="selNode.device_id" class="btn btn-sm" :to="{ name: 'baseline', query: { device: String(selNode.device_id) } }"><Icon name="shield" small />{{ $t('topology.toBaseline') }}</router-link>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="panel-h"><h3>{{ $t('topology.details') }}</h3></div>
              <div class="sb"><div class="empty"><h3>{{ $t('topology.pickTitle') }}</h3><p>{{ $t('topology.pickText') }}</p></div></div>
            </template>
          </section>
        </div>

        <!-- ===================== 一致性 ===================== -->
        <section v-show="view === 'consistency'" class="panel" data-testid="topo-cons">
          <div class="panel-b">
            <div class="cfilters">
              <div class="seg" role="group">
                <button type="button" :aria-pressed="sevFilter === ''" @click="sevFilter = ''">{{ $t('topology.f.all') }} {{ findings.length }}</button>
                <button v-for="s in (['error', 'warning', 'info'] as const)" :key="s" type="button" :aria-pressed="sevFilter === s" :data-testid="`topo-f-${s}`" @click="sevFilter = s">{{ $t(`topology.f.${s}`) }} {{ sev[s] }}</button>
              </div>
              <select v-model="devFilter" class="select" style="width: auto">
                <option value="">{{ $t('topology.allDev') }}</option>
                <option v-for="n in nodes" :key="n.id" :value="n.id">{{ n.id }}</option>
              </select>
              <span class="small muted">{{ $t('topology.consNote') }}</span>
            </div>
            <p v-if="result.rules_skipped.length" class="small faint" style="margin: 0 0 8px">{{ $t('topology.skipped', { list: result.rules_skipped.map((r) => r.id).join(', ') }) }}</p>
            <div v-if="!rows.length" class="empty"><p>{{ $t('topology.noFindings') }}</p></div>
            <div v-else class="tbl-wrap">
              <table class="tbl ctbl">
                <thead><tr><th>{{ $t('topology.col.sev') }}</th><th>{{ $t('topology.col.rule') }}</th><th>{{ $t('topology.col.where') }}</th><th>A</th><th>B</th><th>{{ $t('topology.col.why') }}</th></tr></thead>
                <tbody>
                  <tr v-for="f in rows" :key="f.id" data-testid="topo-finding" @click="goFinding(f)">
                    <td><span class="sev" :class="f.severity"><Icon :name="sevIcon(f.severity)" small />{{ $t(`topology.sev.${f.severity}`) }}</span></td>
                    <td><code class="small">{{ f.rule }}</code></td>
                    <td class="small">{{ $t(`topology.type.${f.link_type}`) }}<br><span class="lk">{{ f.ends[0]?.device }} <code>{{ shortIf(f.ends[0]?.end ?? '') }}</code> ⟷ {{ f.ends[1]?.device }} <code>{{ shortIf(f.ends[1]?.end ?? '') }}</code></span></td>
                    <td class="mono small">{{ String(f.ends[0]?.value ?? '—') }}</td>
                    <td class="mono small">{{ String(f.ends[1]?.value ?? '—') }}</td>
                    <td class="why">{{ ftext(f, 'message') }}<div class="faint">{{ ftext(f, 'suggestion') }}</div></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </template>
    </div>
  </main>
</template>

<style scoped>
.setbar { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 10px 14px; }
.setbar .lbl { font-size: 12px; color: var(--ink-2); }
.pickwrap { position: relative; }
.pickpop { position: absolute; z-index: 30; top: 32px; left: 0; width: 340px; max-height: 420px; overflow: auto; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 6px; box-shadow: var(--shadow-pop); padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.picklist { display: flex; flex-direction: column; gap: 4px; }
.upl { position: relative; overflow: hidden; cursor: pointer; }
.upl input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.stchip { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 4px 0 8px; border-radius: 11px; background: var(--hl-line); border: 1px solid var(--hl-line-edge); font: 12px var(--font-mono); color: var(--ink); }
.stchip button { border: 0; background: transparent; color: var(--ink-3); cursor: pointer; width: 18px; height: 18px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.tabs .count.bad { background: var(--red-soft); color: var(--red-ink); border: 1px solid var(--red-line); border-radius: 9px; padding: 0 6px; font-weight: 600; }
.tstrip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-bottom: 10px; }
.tstrip > div { padding: 10px 14px; border-left: 1px solid var(--line); min-width: 0; }
.tstrip > div:first-child { border-left: 0; }
.tstrip .v { font: 600 21px/1.25 var(--font-display); }
.tstrip .k { font-size: 12px; color: var(--ink-2); display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.tw { display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 10px; height: min(74vh, 800px); min-height: 540px; }
.mapp { display: flex; flex-direction: column; overflow: hidden; }
.tbar2 { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--line); }
.tbar2 .lbl { font-size: 12px; color: var(--ink-2); }
.layers { display: flex; gap: 12px; flex-wrap: wrap; }
.mapf { display: flex; gap: 6px 16px; flex-wrap: wrap; align-items: center; padding: 7px 12px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--ink-2); }
.mapf span { display: inline-flex; align-items: center; gap: 6px; }
.mapf svg { width: 26px; height: 10px; }
.side { display: flex; flex-direction: column; overflow: hidden; }
.side .panel-h { gap: 8px; }
.side .sb { flex: 1; overflow: auto; padding: 12px 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.sec-k { font-size: 12px; font-weight: 600; color: var(--ink-2); margin: 0 0 6px; }
.ends { display: grid; grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr); gap: 6px; align-items: center; }
.ends .e { border: 1px solid var(--line); border-radius: 6px; padding: 7px 9px; background: var(--surface-2); min-width: 0; }
.ends .e code { display: block; font-size: 11.5px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ends .mid { text-align: center; color: var(--ink-3); }
.basisrow { display: flex; flex-wrap: wrap; gap: 6px; }
.basis .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-left: 2px; }
.basis .dot.bad { background: var(--red); }
.basis .dot.warn { background: var(--amber); }
.fitem { border: 1px solid var(--line); border-left: 3px solid var(--amber); border-radius: 6px; padding: 7px 10px; margin-bottom: 6px; }
.fitem.error { border-left-color: var(--red); }
.fitem .fh { display: flex; gap: 8px; align-items: center; }
.fitem .ft { font-size: 12.5px; margin-top: 4px; }
.fitem .fs { font-size: 12px; color: var(--ink-2); margin-top: 3px; }
.ck { width: 100%; border-collapse: collapse; font-size: 12px; }
.ck th { text-align: left; font-weight: 600; color: var(--ink-2); font-size: 11.5px; padding: 5px 6px; border-bottom: 1px solid var(--line); background: var(--surface-2); }
.ck td { padding: 5px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
.ck td.v { font: 11.5px var(--font-mono); overflow-wrap: anywhere; }
.ck tr.st-bad td { background: color-mix(in srgb, var(--amber-soft) 55%, transparent); }
.cfg2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.cfg2 .code { border: 1px solid var(--line); border-radius: 6px; max-height: 260px; overflow: auto; }
.cfg2 .code .l .n { width: 30px; padding-right: 6px; }
.cfg2 .code .l.bad { background: color-mix(in srgb, var(--red-soft) 70%, transparent); }
.cfg2 .code .l.bad .n { box-shadow: inset 3px 0 0 var(--red); }
.cfg2 .code .l.gap .n { color: var(--ink-3); }
.cfg2 .cap { font-size: 11.5px; color: var(--ink-2); margin-bottom: 4px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.acts { display: flex; flex-wrap: wrap; gap: 8px; }
.kvs { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; font-size: 12px; margin: 0; }
.kvs dt { color: var(--ink-3); }
.kvs dd { margin: 0; font-family: var(--font-mono); font-size: 11.5px; overflow-wrap: anywhere; }
.lrow { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border: 1px solid var(--line); border-radius: 5px; cursor: pointer; font-size: 12px; margin-bottom: 4px; }
.lrow:hover { background: var(--surface-2); }
.lrow code { font-size: 11.5px; color: var(--ink-2); }
.cfilters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
.ctbl td { vertical-align: top; }
.ctbl tr { cursor: pointer; }
.ctbl .why { color: var(--ink); font-size: 12px; max-width: 520px; }
.ctbl .lk { font: 11.5px var(--font-mono); color: var(--ink-2); }
@media (max-width: 1300px) {
  .tw { grid-template-columns: minmax(0, 1fr); height: auto; grid-template-rows: 560px auto; }
  .tw .side { max-height: 760px; }
  .tstrip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .cfg2 { grid-template-columns: minmax(0, 1fr); }
  .tstrip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
