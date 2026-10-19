<script setup lang="ts">
/**
 * 变更影响分析（预览 DevelopDocs/ui-preview/M4/impact.html）：选设备与起点节点（可从设备配置图、增量变更跳转过来），
 * 方向 up / down / both → POST /impact → 概况、关系图（cytoscape）、按类型 / 距离 / 功能域分组的列表，每项给出从起点出发的路径。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import FullscreenPane from '@/components/FullscreenPane.vue'
import FullscreenButton from '@/components/FullscreenButton.vue'
import DevChip from '@/components/m4-dev.vue'
import { errorText, get, post } from '@/api'
import { useTerms } from '@/stores/terms'
import type { Device } from '@/views/devices/logic'
import ImpactGraph from './m4/ImpactGraph.vue'
import {
  edgeClass, fromQuery, groupBy, listed, pathTo, presets, searchNodes, stripCounts, withinDepth,
  type Direction, type GNode, type ImpactResult, type Tab,
} from './m4/impact'

const route = useRoute()
const router = useRouter()
const terms = useTerms()
const q0 = fromQuery(route.query)

const devices = ref<Device[]>([])
const loadError = ref('')
const deviceId = ref<number | null>(q0.device)
const versionId = ref<number | null>(q0.version)
const starts = ref<string[]>(q0.nodes)
const dir = ref<Direction>(q0.dir)
const fromChange = ref(q0.fromChange)
const depth = ref(0)
const objectsOnly = ref(true)
const layout = ref<'force' | 'layer'>('force')
const tab = ref<Tab>('type')
const graph = ref<InstanceType<typeof ImpactGraph>>()

const device = computed(() => devices.value.find((d) => d.id === deviceId.value) ?? null)
const label = (id: string) => terms.describe(id)

// ---------------------------------------------------------------- 设备的节点（起点候选）
const gnodes = ref<GNode[]>([])
async function loadNodes(): Promise<void> {
  gnodes.value = []
  if (deviceId.value === null) return
  try {
    const qv = versionId.value !== null ? `?version_id=${versionId.value}` : ''
    gnodes.value = (await get<{ nodes: GNode[] }>(`/devices/${deviceId.value}/graph${qv}`)).nodes
  } catch { /* 取不到时只能手输编号 */ }
}
const kw = ref('')
const hits = computed(() => searchNodes(gnodes.value, kw.value, label, 30))
const common = computed(() => presets(gnodes.value))
function addStart(id: string, replace = false): void {
  starts.value = replace ? [id] : starts.value.includes(id) ? starts.value.filter((x) => x !== id) : [...starts.value, id]
  kw.value = ''
  fromChange.value = false
  void run()
}
function removeStart(id: string): void {
  starts.value = starts.value.filter((x) => x !== id)
  fromChange.value = false
  if (starts.value.length) void run()
  else result.value = null
}

// ---------------------------------------------------------------- 分析
const running = ref(false)
const runError = ref('')
const result = ref<ImpactResult | null>(null)
const focus = ref<string | null>(null)

async function run(): Promise<void> {
  if (deviceId.value === null || !starts.value.length) return
  running.value = true
  runError.value = ''
  focus.value = null
  const body: Record<string, unknown> = { device_id: deviceId.value, nodes: starts.value, direction: dir.value }
  if (versionId.value !== null) body.version_id = versionId.value
  try {
    result.value = await post<ImpactResult>('/impact', body)
    const q: Record<string, string | string[]> = { device: String(deviceId.value), node: starts.value, dir: dir.value }
    if (versionId.value !== null) q.version = String(versionId.value)
    if (fromChange.value) q.from = 'change'
    void router.replace({ query: q })
  } catch (e) {
    runError.value = errorText(e)
    result.value = null
  } finally {
    running.value = false
  }
}
watch(deviceId, (id, old) => {
  if (old === undefined || id === old) return
  versionId.value = null
  starts.value = []
  result.value = null
  fromChange.value = false
  void loadNodes()
})
watch(dir, () => { void run() })

const shown = computed(() => withinDepth(result.value?.nodes ?? [], depth.value))
const graphNodes = computed(() => (objectsOnly.value ? shown.value.filter((n) => n.kind !== 'attr' || n.depth === 0) : shown.value))
// 只列对象时，属性节点从图上去掉，边改为连到最近的可见祖先
const graphView = computed(() => {
  if (!objectsOnly.value) return graphNodes.value
  const all = new Map(shown.value.map((n) => [n.node, n]))
  const vis = new Set(graphNodes.value.map((n) => n.node))
  return graphNodes.value.map((n) => {
    let via = n.via
    let edge = n.edge
    while (via && !vis.has(via)) {
      const p = all.get(via)
      if (p && edge === 'contains') edge = p.edge
      via = p?.via ?? null
    }
    return { ...n, via, edge }
  })
})
const items = computed(() => listed(shown.value, objectsOnly.value))
const groups = computed(() => groupBy(items.value, tab.value))
const strip = computed(() => stripCounts(result.value, shown.value))
const path = computed(() => (focus.value && result.value ? pathTo(result.value.nodes, focus.value) : []))
const nodeById = computed(() => new Map((result.value?.nodes ?? []).map((n) => [n.node, n])))
const pathOf = (id: string) => {
  const p = result.value ? pathTo(result.value.nodes, id) : [id]
  // 只列对象时，路径中间的属性节点省略
  return objectsOnly.value ? p.filter((x, i) => i === 0 || i === p.length - 1 || nodeById.value.get(x)?.kind !== 'attr') : p
}
const EDGE_VAR: Record<string, string> = { ref: 'var(--e-ref)', pre: 'var(--e-pre)', alias: 'var(--violet)', contains: 'var(--ink-3)', seed: 'var(--amber)' }
const grpName = (k: string) => (tab.value === 'hop' ? `distance:${k}` : k)

function onTap(id: string, shift: boolean): void {
  if (shift) addStart(id)
  else if (!starts.value.includes(id) || starts.value.length > 1) addStart(id, true)
}

onMounted(async () => {
  try {
    devices.value = [...(await get<{ devices: Device[] }>('/devices')).devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  } catch (e) {
    loadError.value = errorText(e)
  }
  if (deviceId.value === null && devices.value.length) deviceId.value = devices.value[0].id
  await loadNodes()
  if (starts.value.length) void run()
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.ana') }}</span><span class="sep">/</span><span>{{ $t('nav.impact') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('impact.title') }}</h1>
          <p class="ph-sub">{{ $t('impact.sub') }}</p>
        </div>
      </div>
      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div></div>

      <section class="panel" aria-label="Query" data-testid="imp-query">
        <div class="qbar">
          <span class="lbl">{{ $t('impact.device') }}</span>
          <select v-model="deviceId" class="select" style="width: auto" data-testid="imp-device">
            <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <span class="lbl">{{ $t('impact.direction') }}</span>
          <div class="seg" role="group" data-testid="imp-dir">
            <button v-for="d in (['up', 'down', 'both'] as const)" :key="d" type="button" :aria-pressed="dir === d" :data-testid="`imp-dir-${d}`" @click="dir = d">{{ $t(`impact.dir.${d}`) }}</button>
          </div>
          <span class="lbl">{{ $t('impact.depth') }}</span>
          <select v-model="depth" class="select" style="width: auto" data-testid="imp-depth">
            <option :value="0">{{ $t('impact.depthAll') }}</option>
            <option v-for="n in 4" :key="n" :value="n">{{ n }}</option>
          </select>
          <label class="check"><input v-model="objectsOnly" type="checkbox"><span>{{ $t('impact.objectsOnly') }}</span></label>
        </div>
        <div class="qbar" style="padding-top: 0">
          <span class="lbl">{{ $t('impact.starts') }}</span>
          <div class="starts" data-testid="imp-starts">
            <span v-for="s in starts" :key="s" class="stchip" :title="s"><small>{{ terms.name(nodeById.get(s)?.schema ?? gnodes.find((n) => n.id === s)?.schema ?? '') }}</small>{{ label(s) }}<button type="button" :aria-label="$t('impact.remove')" @click="removeStart(s)"><Icon name="x" small /></button></span>
            <div class="addwrap">
              <input v-model="kw" type="search" :placeholder="$t('impact.addPh')" data-testid="imp-add" @keydown.enter.prevent="hits[0] && addStart(hits[0].id)">
              <div v-if="hits.length" class="sugg" data-testid="imp-sugg">
                <button v-for="h in hits" :key="h.id" type="button" @click="addStart(h.id)"><span>{{ label(h.id) }}</span><small>{{ terms.name(h.schema ?? '') }}</small></button>
              </div>
            </div>
          </div>
          <button class="btn btn-primary btn-sm" type="button" :disabled="!starts.length || running" data-testid="imp-run" @click="run"><Icon name="target" small />{{ running ? $t('impact.running') : $t('impact.run') }}</button>
        </div>
        <div v-if="common.length" class="presets">
          <span class="k">{{ $t('impact.presets') }}</span>
          <button v-for="p in common" :key="p.id" type="button" class="preset" :aria-pressed="starts.length === 1 && starts[0] === p.id" data-testid="imp-preset" @click="addStart(p.id, true)">{{ terms.name(p.schema ?? '') }} {{ label(p.id) }}</button>
        </div>
        <div v-if="fromChange" class="fromchg"><Icon name="branch" small /><span>{{ $t('impact.fromChange') }}</span><router-link class="ml-auto" :to="{ name: 'change', query: { device: String(deviceId) } }">{{ $t('impact.openChange') }}</router-link></div>
      </section>

      <div v-if="runError" class="notice err mt12" data-testid="imp-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
      <div v-if="!result && !runError" class="empty mt16" data-testid="imp-empty"><Icon name="target" /><h3>{{ running ? $t('c.loading') : $t('impact.emptyTitle') }}</h3><p v-if="!running">{{ $t('impact.emptyText') }}</p></div>

      <FullscreenPane v-if="result" class="imp-fs" :title="$t('impact.title')" data-testid="imp-fs">
        <div class="istrip" data-testid="imp-strip">
          <div><div class="v">{{ strip.objects }}</div><div class="k">{{ $t(`impact.s.objects.${result.direction}`) }}</div></div>
          <div v-for="k in ['peer', 'vrf', 'interface', 'l2vpn', 'domains']" :key="k"><div class="v">{{ strip[k] }}</div><div class="k">{{ $t(`impact.s.${k}`) }}</div></div>
        </div>

        <div class="iw">
          <section class="panel gpane" aria-label="Relationship graph">
            <div class="tbar">
              <b>{{ $t('impact.graph') }}</b>
              <DevChip v-if="device" :name="device.name" :vendor="device.vendor" />
              <div class="seg" role="group">
                <button type="button" :aria-pressed="layout === 'force'" @click="layout = 'force'">{{ $t('impact.lay.force') }}</button>
                <button type="button" :aria-pressed="layout === 'layer'" @click="layout = 'layer'">{{ $t('impact.lay.layer') }}</button>
              </div>
              <button class="btn btn-xs btn-ghost ml-auto" type="button" @click="graph?.fit()"><Icon name="expand" small />{{ $t('impact.fit') }}</button>
              <FullscreenButton size="xs" />
            </div>
            <ImpactGraph ref="graph" :nodes="graphView" :label="label" :path="path" :layout="layout" @tap="onTap" />
            <div class="gfoot">
              <span><i class="rg" style="background: var(--amber); border-color: var(--amber-ink)" />{{ $t('impact.lg.start') }}</span>
              <span><i class="rg" style="background: var(--amber-soft); border-color: var(--ring1)" />{{ $t('impact.lg.h1') }}</span>
              <span><i class="rg" style="border-color: var(--ring2)" />{{ $t('impact.lg.h2') }}</span>
              <span><i class="rg sq" style="border-color: var(--line-strong); border-style: dashed" />{{ $t('impact.lg.biz') }}</span>
              <span v-for="k in ['reference', 'prerequisite', 'contains', 'alias']" :key="k"><i class="edge-sw" :style="{ background: EDGE_VAR[edgeClass(k)] }" />{{ $t(`impact.e.${k}`) }}</span>
              <span class="ml-auto faint">{{ $t('impact.hint') }}</span>
            </div>
          </section>

          <section class="panel ilist" aria-label="Affected objects">
            <div class="tabs" role="tablist">
              <button v-for="tb in (['type', 'hop', 'domain'] as const)" :key="tb" type="button" role="tab" :aria-selected="tab === tb" @click="tab = tb">{{ $t(`impact.tab.${tb}`) }}</button>
              <span class="ml-auto small muted" style="align-self: center; padding-right: 6px">{{ items.length }}</span>
            </div>
            <div class="ibody" data-testid="imp-list">
              <div v-if="!items.length" class="empty"><h3>{{ $t('impact.noneTitle') }}</h3><p>{{ result.direction === 'down' ? $t('impact.noneDown') : $t('impact.noneText') }}</p></div>
              <template v-for="g in groups" :key="g.key">
                <div class="igrp-h">{{ tab === 'hop' ? $t('impact.distance', { n: g.key }) : tab === 'type' ? $t(`impact.grp.${g.key}`) : g.key }}<span class="cnt">{{ g.items.length }}</span></div>
                <div v-for="n in g.items" :key="grpName(g.key) + n.node" class="ii" :class="{ 'is-sel': focus === n.node }" data-testid="imp-item" @click="focus = focus === n.node ? null : n.node">
                  <span class="hop" :class="n.depth === 1 ? 'h1' : ''">{{ n.depth }}</span>
                  <div class="nm"><code :title="n.node">{{ label(n.node) }}</code><span class="kd">{{ terms.name(n.schema ?? '') }}</span><span v-if="n.direction === 'down' && result.direction === 'both'" class="tag t-blue">{{ $t('impact.dir.down') }}</span></div>
                  <div class="chain">
                    <template v-for="(x, i) in pathOf(n.node)" :key="x">
                      <code :class="{ cur: i === 0 }">{{ label(x) }}</code>
                      <span v-if="i < pathOf(n.node).length - 1" class="lk"><i :style="{ background: EDGE_VAR[edgeClass(nodeById.get(pathOf(n.node)[i + 1])?.edge ?? '')] }" />→</span>
                    </template>
                  </div>
                  <div v-if="focus === n.node && deviceId !== null" class="note"><router-link :to="{ name: 'device-graph', params: { id: String(deviceId) }, query: { node: n.node } }" @click.stop>{{ $t('impact.toGraph') }}</router-link></div>
                </div>
              </template>
            </div>
          </section>
        </div>
      </FullscreenPane>
    </div>
  </main>
</template>

<style scoped>
.qbar { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; padding: 10px 14px; }
.qbar .lbl { font-size: 12px; color: var(--ink-2); }
.starts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-height: 30px; padding: 3px 6px; border: 1px solid var(--line-strong); border-radius: var(--r-ctl); background: var(--surface); flex: 1; min-width: 280px; }
.stchip { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 4px 0 8px; border-radius: 11px; background: var(--hl-line); border: 1px solid var(--hl-line-edge); font: 12px var(--font-mono); color: var(--ink); max-width: 100%; }
.stchip small { font: 11px var(--font-ui); color: var(--ink-3); }
.stchip button { border: 0; background: transparent; color: var(--ink-3); cursor: pointer; width: 18px; height: 18px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.stchip button:hover { background: var(--surface); color: var(--ink); }
.addwrap { position: relative; flex: 1; min-width: 200px; }
.addwrap input { border: 0; outline: 0; background: transparent; font: inherit; color: var(--ink); width: 100%; }
.sugg { position: absolute; left: 0; top: 26px; z-index: 30; width: min(560px, 80vw); max-height: 320px; overflow: auto; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 6px; box-shadow: var(--shadow-pop); }
.sugg button { all: unset; box-sizing: border-box; display: flex; gap: 10px; width: 100%; padding: 6px 10px; cursor: pointer; font: 12px var(--font-mono); color: var(--ink); align-items: baseline; }
.sugg button:hover { background: var(--surface-2); }
.sugg small { margin-left: auto; font: 11px var(--font-ui); color: var(--ink-3); white-space: nowrap; }
.presets { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 0 14px 12px; }
.presets .k { font-size: 12px; color: var(--ink-3); margin-right: 2px; }
.preset { border: 1px dashed var(--line-strong); background: transparent; color: var(--ink-2); border-radius: 4px; height: 24px; padding: 0 8px; font: inherit; font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.preset:hover { border-color: var(--blue); color: var(--blue-ink); }
.preset[aria-pressed="true"] { border-style: solid; border-color: var(--amber); background: var(--amber-soft); color: var(--amber-ink); font-weight: 600; }
.fromchg { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 0 14px 12px; padding: 8px 10px; border-radius: 6px; border: 1px solid var(--amber-line); background: color-mix(in srgb, var(--amber-soft) 55%, var(--surface)); font-size: 12.5px; }
.istrip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-top: 12px; }
.istrip > div { padding: 10px 14px; border-left: 1px solid var(--line); min-width: 0; }
.istrip > div:first-child { border-left: 0; }
.istrip .v { font: 600 21px/1.25 var(--font-display); }
.istrip .k { font-size: 12px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.iw { display: grid; grid-template-columns: minmax(0, 1fr) 420px; gap: 10px; margin-top: 10px; height: min(72vh, 780px); min-height: 520px; }
.gpane { display: flex; flex-direction: column; overflow: hidden; }
.gpane .tbar { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.gfoot { display: flex; gap: 6px 16px; align-items: center; flex-wrap: wrap; padding: 7px 10px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--ink-2); }
.gfoot span { display: inline-flex; align-items: center; gap: 5px; }
.gfoot .rg { width: 12px; height: 12px; border-radius: 50%; display: inline-block; border: 2px solid; }
.gfoot .rg.sq { border-radius: 3px; }
.ilist { display: flex; flex-direction: column; overflow: hidden; }
.ilist .tabs { margin: 0; padding: 0 8px; }
.ibody { flex: 1; overflow: auto; }
.igrp-h { display: flex; align-items: center; gap: 8px; padding: 7px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 1; font-size: 12px; color: var(--ink-2); font-weight: 600; }
.igrp-h .cnt { margin-left: auto; font-weight: 400; color: var(--ink-3); }
.ii { padding: 9px 12px; border-bottom: 1px solid var(--line); cursor: pointer; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 10px; }
.ii:hover { background: var(--surface-2); }
.ii.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.ii .nm { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
.ii .nm code { font-size: 12px; font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }
.ii .kd { font-size: 11.5px; color: var(--ink-3); }
.ii .chain, .ii .note { grid-column: 2; }
.ii .note { font-size: 12px; }
.imp-fs.is-fs .istrip, .imp-fs.is-fs .iw { margin-top: 0; }
.imp-fs.is-fs .iw { flex: 1; height: auto; min-height: 0; }
@media (max-width: 1300px) {
  .iw { grid-template-columns: minmax(0, 1fr); height: auto; grid-template-rows: 560px 560px; }
  .istrip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .istrip > div:nth-child(4) { border-left: 0; }
  .istrip > div:nth-child(n+4) { border-top: 1px solid var(--line); }
}
@media (max-width: 760px) {
  .istrip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
