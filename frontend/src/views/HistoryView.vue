<script setup lang="ts">
/**
 * 版本历史（预览 DevelopDocs/ui-preview/M5/history.html，REQ-021）：设备的快照时间线 → 选 A（较早）/ B（较晚）→
 * 图差异 / 配置差异 / 对象历史三个标签页；知识库版本不同时提示并可按当前知识库重建；标签；回到 A 的变更脚本；中英文差异报告。
 * 差异由后端在图上计算（GET /devices/{id}/history/diff）；对象名按显示风格（华为 / Cisco）写成命令路径。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import FullscreenPane from '@/components/FullscreenPane.vue'
import FullscreenButton from '@/components/FullscreenButton.vue'
import DevChip from '@/components/m4-dev.vue'
import { del, errorText, get, post, put } from '@/api'
import { useTerms } from '@/stores/terms'
import { useProject } from '@/stores/project'
import { postFile, saveBlob } from '@/views/check/report'
import { saveText } from '@/views/profiles/csv'
import type { Device } from '@/views/devices/logic'
import HistoryTimeline from './m5/HistoryTimeline.vue'
import DevDelDialog from '@/components/devdel-dialog.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import AiCoverageBar from '@/components/ai-suggest/AiCoverageBar.vue'
import { coverageMarks, diffScope, type Coverage, type CoverageItem, type RefInfo } from '@/components/ai-suggest/logic'
import {
  diffCli, fmtTime, foldRows, groupItems, itemOfNode, markWords, matrixRow, noneffByObject, objectLog, objectOptions,
  pairLines, showVal, underObject, type DiffResult, type Item, type ObjectHistory, type PairRow, type SideVal, type Timeline,
} from './m5/history'

const project = useProject() // 只读成员不显示修改操作（REQ-036）
const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()

// ---------------------------------------------------------------- 设备与时间线
const devices = ref<Device[]>([])
const devId = ref<number | null>(null)
const tl = ref<Timeline | null>(null)
const tlError = ref('')
const loading = ref(false)
const ia = ref(0)
const ib = ref(0)

async function loadDevices(): Promise<void> {
  try {
    const d = await get<{ devices: Device[] }>('/devices')
    devices.value = [...d.devices].sort((x, y) => x.name.localeCompare(y.name, undefined, { numeric: true }))
  } catch (e) {
    tlError.value = errorText(e)
  }
}
async function loadTimeline(keepSel = false): Promise<void> {
  if (devId.value === null) return
  loading.value = true
  tlError.value = ''
  try {
    const r = await get<Timeline>(`/devices/${devId.value}/history`)
    const prevA = tl.value?.snapshots[ia.value]?.id
    const prevB = tl.value?.snapshots[ib.value]?.id
    tl.value = r
    const n = r.snapshots.length
    const qa = Number(route.query.a)
    const qb = Number(route.query.b)
    const byId = (id: number | undefined) => r.snapshots.findIndex((s) => s.id === id)
    if (keepSel && byId(prevA) >= 0 && byId(prevB) >= 0) { ia.value = byId(prevA); ib.value = byId(prevB) } else if (byId(qa) >= 0 && byId(qb) > byId(qa)) { ia.value = byId(qa); ib.value = byId(qb) } else { ib.value = Math.max(0, n - 1); ia.value = Math.max(0, n - 2) }
  } catch (e) {
    tl.value = null
    tlError.value = errorText(e)
  } finally {
    loading.value = false
  }
}
const snaps = computed(() => tl.value?.snapshots ?? [])
const single = computed(() => snaps.value.length < 2)
const sa = computed(() => snaps.value[ia.value] ?? null)
const sb = computed(() => snaps.value[ib.value] ?? null)
const dev = computed(() => devices.value.find((d) => d.id === devId.value) ?? null)

function setAB(a: number, b: number): void {
  if (a >= b) return
  ia.value = a
  ib.value = b
}
const toast = ref('')
let toastTimer = 0
function flash(s: string): void {
  toast.value = s
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2600)
}
const vsPrev = () => setAB(ib.value - 1, ib.value)
const vsLatest = () => { const n = snaps.value.length; setAB(ia.value >= n - 1 ? n - 2 : ia.value, n - 1) }
const swap = () => flash(t('history.swapTip'))
const showList = ref(false)

// ---------------------------------------------------------------- 差异
const effOnly = ref(true)
const rebuild = ref(false)
const diff = ref<DiffResult | null>(null)
const diffError = ref('')
const diffLoading = ref(false)
let diffSeq = 0
async function loadDiff(): Promise<void> {
  if (!tl.value || single.value || !sa.value || !sb.value || devId.value === null) { diff.value = null; return }
  const my = ++diffSeq
  diffLoading.value = true
  diffError.value = ''
  const q = new URLSearchParams({ a: String(sa.value.id), b: String(sb.value.id), show_noneff: 'true', rebuild: String(rebuild.value), context: '100000' })
  try {
    const r = await get<DiffResult>(`/devices/${devId.value}/history/diff?${q}`)
    if (my !== diffSeq) return
    diff.value = r
  } catch (e) {
    if (my === diffSeq) { diff.value = null; diffError.value = errorText(e) }
  } finally {
    if (my === diffSeq) diffLoading.value = false
  }
}
watch([() => sa.value?.id, () => sb.value?.id, rebuild], () => { sel.value = null; unfold.value = new Set(); void loadDiff(); syncQuery() })

const tab = ref<'graph' | 'text' | 'object'>(route.query.tab === 'text' || route.query.tab === 'object' ? route.query.tab : 'graph')
watch(tab, () => syncQuery())
function syncQuery(): void {
  if (devId.value === null) return
  const q: Record<string, string> = {}
  if (sa.value && sb.value && !single.value) { q.a = String(sa.value.id); q.b = String(sb.value.id) }
  if (tab.value !== 'graph') q.tab = tab.value
  if (tab.value === 'object' && objNode.value) q.obj = objNode.value
  void router.replace({ name: 'history', params: { id: String(devId.value) }, query: q })
}

const items = computed(() => diff.value?.items ?? [])
const noneffGroups = computed(() => (effOnly.value ? [] : noneffByObject(diff.value?.noneff ?? [])))
const groups = computed(() => {
  const g = groupItems(items.value).map((x) => ({ domain: x.domain, items: x.items as Item[], noneff: [] as ReturnType<typeof noneffByObject> }))
  for (const n of noneffGroups.value) {
    let d = g.find((x) => x.domain === n.domain)
    if (!d) g.push((d = { domain: n.domain, items: [], noneff: [] }))
    d.noneff.push(n)
  }
  return g
})
const shownCount = computed(() => items.value.length + noneffGroups.value.length)
const kindName = (k: string) => t(`history.kind.${k}`)
const objLabel = (o: string) => terms.describe(o)
const typeName = (schema: string) => terms.name(schema)
const domName = (d: string) => { const k = `features.dom.${d}`; const s = t(k); return s === k ? d : s }
const domRows = computed(() => {
  const bd = diff.value?.summary.by_domain ?? {}
  const max = Math.max(1, ...Object.values(bd).map((v) => v.total ?? 0))
  return Object.entries(bd).map(([d, v]) => ({ d, a: v.added ?? 0, m: (v.modified ?? 0) + (v.renamed ?? 0), r: v.removed ?? 0, t: v.total ?? 0, max }))
})

// ---------------------------------------------------------------- 选中项与详情
const sel = ref<string | null>(null)

// ---------------------------------------------------------------- AI 变化解读（M8-3）：两个快照之间的差异归纳成变更意图
const aiScope = computed(() => (sa.value && sb.value && !single.value ? diffScope('history', sa.value.id, sb.value.id) : ''))
const aiParams = computed(() => ({ source: 'history', device_id: devId.value, a_version: sa.value?.id, b_version: sb.value?.id }))
const aiPanel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiCov = ref<InstanceType<typeof AiCoverageBar> | null>(null)
const aiOpen = ref(false)
const aiState = ref('loading')
const aiShown = computed(() => aiOpen.value || ['done', 'running', 'empty', 'failed', 'cancelled'].includes(aiState.value))
const coverage = ref<Coverage | null>(null)
const covMarks = computed<Record<string, string>>(() => {
  const m = coverageMarks(items.value.map((x) => ({ node: x.object })), coverage.value)
  return Object.fromEntries(items.value.map((x, i) => [x.object, m[i]]))
})
watch(aiScope, () => { aiOpen.value = false; coverage.value = null })
async function runAi(): Promise<void> {
  aiOpen.value = true
  await nextTick()
  await aiPanel.value?.start()
}
/** 引用的差异条目 / 覆盖条里的条目 → 在图差异里选中该对象 */
function aiJump(r: RefInfo | CoverageItem): void {
  const node = r.node ?? null
  const hit = items.value.find((x) => (node && (x.object === node || underObject(node, x.object))) || x.object === r.label)
  if (!hit) return
  tab.value = 'graph'
  sel.value = hit.object
}
const selItem = computed(() => items.value.find((x) => x.object === sel.value) ?? null)
const selNoneff = computed(() => noneffGroups.value.find((x) => x.object === sel.value) ?? null)
const hunkLines = computed(() => (diff.value?.text?.hunks ?? []).flatMap((h) => h.lines))
const linesA = computed(() => { const m = new Map<number, string>(); for (const l of hunkLines.value) if (l.a) m.set(l.a, l.text); return m })
const linesB = computed(() => { const m = new Map<number, string>(); for (const l of hunkLines.value) if (l.b) m.set(l.b, l.text); return m })
const mini = (nums: number[], side: 'a' | 'b') => nums.map((n) => ({ n, t: (side === 'a' ? linesA.value : linesB.value).get(n) ?? '' }))
function pick(o: string): void { sel.value = sel.value === o ? null : o }
function valText(v: SideVal | null | undefined): string { return v ? showVal(v.value) : '' }

// ---------------------------------------------------------------- 配置差异（并排）
const rows = computed<PairRow[]>(() => pairLines(hunkLines.value))
const unfold = ref<Set<string>>(new Set())
const objects = computed(() => items.value.map((x) => x.object).concat(noneffGroups.value.map((x) => x.object)))
const isHl = (r: PairRow) => !!sel.value && (underObject(r.a?.node, sel.value) || underObject(r.b?.node, sel.value))
const segs = computed(() => foldRows(rows.value, isHl, unfold.value))
function openFold(k: string): void { const s = new Set(unfold.value); s.add(k); unfold.value = s }
function rowClick(r: PairRow): void {
  const o = itemOfNode(r.b?.node ?? r.a?.node, objects.value) ?? itemOfNode(r.a?.node, objects.value)
  if (o) sel.value = o
}
const marks = (r: PairRow) => (r.kind === 'ch' && r.a && r.b ? markWords(r.a.text, r.b.text) : null)
function locate(o: string): void { sel.value = o; tab.value = 'text'; setTimeout(() => document.querySelector('.td .tr.is-hl')?.scrollIntoView({ block: 'center' }), 60) }

// ---------------------------------------------------------------- 对象历史
const objNode = ref<string>(typeof route.query.obj === 'string' ? route.query.obj : '')
const objOpts = ref<ReturnType<typeof objectOptions>>([])
const objHist = ref<ObjectHistory | null>(null)
const objError = ref('')
const objLoading = ref(false)
async function loadObjOptions(): Promise<void> {
  if (devId.value === null) return
  try {
    const g = await get<{ nodes: { id: string; kind: string; schema: string | null; origin?: string }[] }>(`/devices/${devId.value}/graph`)
    objOpts.value = objectOptions(g.nodes)
  } catch { objOpts.value = [] }
}
async function loadObject(): Promise<void> {
  if (devId.value === null || !objNode.value) { objHist.value = null; return }
  objLoading.value = true
  objError.value = ''
  try {
    objHist.value = await get<ObjectHistory>(`/devices/${devId.value}/history/object?node=${encodeURIComponent(objNode.value)}`)
  } catch (e) {
    objHist.value = null
    objError.value = errorText(e)
  } finally {
    objLoading.value = false
  }
}
watch(objNode, () => { void loadObject(); syncQuery() })
watch(tab, (v) => {
  if (v !== 'object') return
  if (!objOpts.value.length) void loadObjOptions()
  if (!objNode.value) objNode.value = items.value[0]?.object ?? ''
})
function goObject(o: string): void { objNode.value = o; tab.value = 'object'; if (!objOpts.value.length) void loadObjOptions() }
const optList = computed(() => {
  const all = objOpts.value.map((g) => ({ group: g.group, items: g.items.map((x) => x.id) }))
  if (objNode.value && !all.some((g) => g.items.includes(objNode.value))) all.unshift({ group: '—', items: [objNode.value] })
  return all
})
const matrix = computed(() => (objHist.value ? objHist.value.fields.map((f) => ({ f, cells: matrixRow(objHist.value!.snapshots, f) })) : []))
const objEvents = computed(() => (objHist.value ? objectLog(objHist.value.snapshots) : []))
const snapOf = (seq: number) => snaps.value.find((s) => s.seq === seq)

// ---------------------------------------------------------------- 标签
const tagEdit = ref<number | null>(null)
const tagText = ref('')
const tagBusy = ref(false)
async function saveTag(vid: number): Promise<void> {
  if (!tagText.value.trim() || devId.value === null) return
  tagBusy.value = true
  try {
    await put(`/devices/${devId.value}/history/${vid}/tag`, { tag: tagText.value.trim() })
    tagEdit.value = null
    tagText.value = ''
    await loadTimeline(true)
  } catch (e) { flash(errorText(e)) } finally { tagBusy.value = false }
}
async function removeTag(vid: number): Promise<void> {
  if (devId.value === null) return
  try {
    await del(`/devices/${devId.value}/history/${vid}/tag`)
    await loadTimeline(true)
  } catch (e) { flash(errorText(e)) }
}

// ---------------------------------------------------------------- 删除单个版本（REQ-038）
const delVer = ref<number | null>(null)
async function onVersionDeleted(_r: unknown, msg: string): Promise<void> {
  delVer.value = null
  flash(msg)
  await Promise.all([loadDevices(), loadTimeline(true)])
}

// ---------------------------------------------------------------- 回到 A、报告、CLI
interface RestoreRes { change: { equal?: boolean; script_plain: string; rollback?: { script_plain: string } | null; verify?: { ok: boolean } | null; ops: unknown[]; summary?: { by_action?: Record<string, number> } } }
const restore = ref<RestoreRes | null>(null)
const restoring = ref(false)
async function doRestore(): Promise<void> {
  if (!sa.value || !sb.value || devId.value === null) return
  restoring.value = true
  try {
    restore.value = await post<RestoreRes>(`/devices/${devId.value}/history/restore`, { to: String(sa.value.id), from: String(sb.value.id), style: terms.style, lang: lang.value })
  } catch (e) { flash(errorText(e)) } finally { restoring.value = false }
}
const changeLink = computed(() => (sa.value && sb.value && devId.value !== null ? { name: 'change', query: { device: String(devId.value), cv: String(sb.value.id), tv: String(sa.value.id), run: '1' } } : null))
const reporting = ref('')
async function report(rl: 'zh-CN' | 'en'): Promise<void> {
  if (!sa.value || !sb.value || devId.value === null) return
  reporting.value = rl
  try {
    const name = `history-${(tl.value?.device.name ?? 'device').replace(/[^\w.@-]+/g, '_')}-${sa.value.seq}-${sb.value.seq}.${rl}.html`
    const f = await postFile(`/devices/${devId.value}/history/report`, { a: String(sa.value.id), b: String(sb.value.id), rebuild: rebuild.value, lang: rl, format: 'html', style: terms.style }, name)
    saveBlob(f.blob, f.name)
  } catch (e) { flash(t('history.reportFail', { e: errorText(e) })) } finally { reporting.value = '' }
}
const cli = computed(() => (tl.value && sa.value && sb.value ? diffCli(tl.value.device.name, sa.value.id, sb.value.id, { noneff: !effOnly.value, rebuild: rebuild.value }) : ''))
function copy(s: string): void {
  const ok = () => flash(t('c.copied'))
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(ok, ok)
  else ok()
}
function dlScript(): void {
  if (!restore.value || !tl.value) return
  saveText(`restore-${tl.value.device.name}-v${sa.value?.id}.txt`, restore.value.change.script_plain, 'text/plain;charset=utf-8')
}

// ---------------------------------------------------------------- 初始化
watch(() => route.params.id, (v) => {
  const id = Number(v)
  if (id && id !== devId.value) devId.value = id
})
watch(devId, async (id, old) => {
  if (id === null) return
  if (old !== undefined && old !== null) { objNode.value = ''; objOpts.value = []; objHist.value = null; rebuild.value = false }
  if (String(route.params.id ?? '') !== String(id)) void router.replace({ name: 'history', params: { id: String(id) } })
  await loadTimeline()
  if (tab.value === 'object') { void loadObjOptions(); void loadObject() }
})
onMounted(async () => {
  await loadDevices()
  const pid = Number(route.params.id)
  if (pid) devId.value = pid
  else if (devices.value.length) devId.value = (devices.value.find((d) => d.versions >= 2) ?? devices.value[0]).id
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.dev') }}</span><span class="sep">/</span><span>{{ $t('nav.history') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('history.title') }}</h1>
          <p class="ph-sub">{{ $t('history.sub') }}</p>
        </div>
        <div class="ph-actions">
          <div class="hbar">
            <span class="lbl">{{ $t('history.device') }}</span>
            <select v-model="devId" class="select" :aria-label="$t('history.device')" data-testid="hist-device">
              <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}{{ d.versions > 1 ? ` (${d.versions})` : '' }}</option>
            </select>
          </div>
        </div>
      </div>

      <div v-if="tlError" class="notice err mb12" data-testid="hist-error"><Icon name="err" /><div class="grow">{{ tlError }}</div><button class="btn btn-sm" type="button" @click="loadTimeline()">{{ $t('c.retry') }}</button></div>
      <div v-if="!devices.length && !tlError" class="empty"><Icon name="server" /><h3>{{ $t('history.noDevices') }}</h3><router-link class="btn btn-primary btn-sm" :to="{ name: 'devices' }">{{ $t('history.import') }}</router-link></div>
      <div v-if="loading && !tl" class="empty"><p>{{ $t('c.loading') }}</p></div>

      <template v-if="tl">
        <!-- ===================== 时间线 ===================== -->
        <section class="panel" aria-label="Timeline">
          <div class="tl-h">
            <h2>{{ $t('history.snapshots') }}</h2>
            <span class="meta" data-testid="hist-meta">{{ single ? $t('history.oneSnap') : $t('history.meta', { n: tl.count, imports: tl.imports, keep: tl.keep || '∞' }) }}</span>
            <span class="ml-auto" />
            <template v-if="!single">
              <span class="abpick"><span class="vm a">A</span>
                <select :value="ia" class="select" aria-label="A" data-testid="hist-sel-a" @change="setAB(Number(($event.target as HTMLSelectElement).value), ib)">
                  <option v-for="(s, i) in snaps" :key="s.id" :value="i" :disabled="i >= ib">#{{ s.seq }} · {{ fmtTime(s.collected_at) }}{{ s.tag ? ` · ${s.tag}` : '' }}</option>
                </select>
              </span>
              <button class="btn btn-sm btn-ghost btn-icon" type="button" :title="$t('history.swap')" :aria-label="$t('history.swap')" data-testid="hist-swap" @click="swap"><Icon name="swap" small /></button>
              <span class="abpick"><span class="vm b">B</span>
                <select :value="ib" class="select" aria-label="B" data-testid="hist-sel-b" @change="setAB(ia, Number(($event.target as HTMLSelectElement).value))">
                  <option v-for="(s, i) in snaps" :key="s.id" :value="i" :disabled="i <= ia">#{{ s.seq }} · {{ fmtTime(s.collected_at) }}{{ s.tag ? ` · ${s.tag}` : '' }}</option>
                </select>
              </span>
              <button class="btn btn-sm" type="button" data-testid="hist-prev" @click="vsPrev">{{ $t('history.vsPrev') }}</button>
              <button class="btn btn-sm" type="button" data-testid="hist-latest" @click="vsLatest">{{ $t('history.vsLatest') }}</button>
            </template>
            <button class="btn btn-sm btn-ghost" type="button" :aria-expanded="showList" data-testid="hist-list-btn" @click="showList = !showList"><Icon name="rows" small />{{ $t('history.allSnaps') }}</button>
          </div>
          <HistoryTimeline :snaps="snaps" :a="ia" :b="ib" :single="single" @pick="setAB" />
          <div class="tl-foot">
            <span><span class="vm a sm">A</span>{{ $t('history.legA') }}</span>
            <span><span class="vm b sm">B</span>{{ $t('history.legB') }}</span>
            <span><i class="sq" style="background: var(--d-add)" />{{ $t('history.kind.added') }}</span>
            <span><i class="sq" style="background: var(--d-mod)" />{{ $t('history.kind.modified') }}</span>
            <span><i class="sq" style="background: var(--d-del)" />{{ $t('history.kind.removed') }}</span>
            <span><i class="sq" style="background: var(--line-strong)" />{{ $t('history.fmtOnly') }}</span>
            <span class="faint">{{ $t('history.tlHint') }}</span>
          </div>

          <div v-if="showList" class="snaptbl" data-testid="hist-snap-table">
            <table class="tbl compact">
              <thead><tr><th /><th>#</th><th>{{ $t('history.col.time') }}</th><th>{{ $t('history.col.source') }}</th><th>{{ $t('history.col.actor') }}</th><th class="num">{{ $t('history.col.lines') }}</th><th class="num">{{ $t('history.col.nodes') }}</th><th>{{ $t('history.col.vs') }}</th><th>{{ $t('history.col.kb') }}</th><th>{{ $t('history.col.fp') }}</th><th>{{ $t('history.col.tag') }}</th><th /><th /></tr></thead>
              <tbody>
                <template v-for="(s, i) in [...snaps].reverse()" :key="s.id">
                  <tr v-for="(im, j) in s.imports" :key="im.id" :class="{ 'is-sel': s.id === sa?.id || s.id === sb?.id }">
                    <td><template v-if="j === 0"><span v-if="s.id === sa?.id && !single" class="vm a sm">A</span><span v-else-if="s.id === sb?.id && !single" class="vm b sm">B</span></template></td>
                    <td class="mono">{{ j === 0 ? `#${s.seq}` : '' }}</td>
                    <td class="mono">{{ fmtTime(im.imported_at) }}</td>
                    <td>{{ $t(`history.src.${im.source_kind}`) }} <span class="faint mono small">{{ im.source_name }}</span><span v-if="im.duplicate" class="tag">{{ $t('history.merged') }}</span></td>
                    <td class="mono">{{ im.actor }}</td>
                    <td class="num">{{ j === 0 ? s.lines : '' }}</td>
                    <td class="num">{{ j === 0 ? s.nodes ?? '—' : '' }}</td>
                    <td><template v-if="j === 0"><span v-if="s.vs_previous" class="cnts"><span class="a">+{{ s.vs_previous.added }}</span><span class="m">~{{ s.vs_previous.modified + s.vs_previous.renamed }}</span><span class="d">−{{ s.vs_previous.removed }}</span><span v-if="s.vs_previous.fmt" class="f">{{ $t('history.fmt') }} {{ s.vs_previous.fmt }}</span></span><span v-else class="faint small">{{ $t('history.firstImport') }}</span></template></td>
                    <td class="mono">{{ j === 0 ? s.kb_version : '' }}</td>
                    <td class="mono faint" :title="s.fingerprint">{{ j === 0 ? `sha256:${s.fingerprint.slice(0, 8)}…` : '' }}</td>
                    <td>
                      <template v-if="j === 0">
                        <span v-if="s.tag" class="vtag pin"><Icon name="tag" small />{{ s.tag }}<button v-if="project.canWrite" class="link-btn" type="button" :aria-label="$t('history.untag')" :title="$t('history.untag')" @click="removeTag(s.id)"><Icon name="x" small /></button></span>
                        <span v-else-if="tagEdit === s.id" class="tagedit"><input v-model="tagText" class="input" maxlength="64" :placeholder="$t('history.tagPh')" data-testid="hist-tag-input" @keydown.enter="saveTag(s.id)"><button class="btn btn-xs btn-primary" type="button" :disabled="tagBusy || !tagText.trim()" data-testid="hist-tag-save" @click="saveTag(s.id)">{{ $t('c.save') }}</button><button class="btn btn-xs btn-ghost" type="button" @click="tagEdit = null">{{ $t('c.cancel') }}</button></span>
                        <button v-else-if="project.canWrite" class="btn btn-xs btn-ghost" type="button" :data-testid="`hist-tag-${s.seq}`" @click="tagEdit = s.id; tagText = ''"><Icon name="plus" small />{{ $t('history.addTag') }}</button>
                      </template>
                    </td>
                    <td class="nowrap"><template v-if="j === 0 && !single"><button class="btn btn-xs" type="button" :disabled="snaps.length - 1 - i >= ib" @click="setAB(snaps.length - 1 - i, ib)">A</button> <button class="btn btn-xs" type="button" :disabled="snaps.length - 1 - i <= ia" @click="setAB(ia, snaps.length - 1 - i)">B</button></template></td>
                    <td class="nowrap"><button v-if="j === 0 && project.canWrite" class="btn btn-xs btn-danger" type="button" :disabled="single" :title="single ? $t('devdel.lastVersionTip') : $t('devdel.deleteVersion')" :data-testid="`hist-del-${s.seq}`" @click="delVer = s.id"><Icon name="trash" small />{{ $t('devdel.deleteVersion') }}</button></td>
                  </tr>
                </template>
              </tbody>
            </table>
            <p class="small faint snapnote">{{ $t('history.keepNote', { keep: tl.keep || '∞' }) }}</p>
          </div>

          <div class="abcards" :class="{ one: single }">
            <template v-for="(s, k) in (single ? [snaps[snaps.length - 1]] : [sa, sb])" :key="k">
              <div v-if="s" class="abcard" :data-testid="`hist-card-${single ? 'only' : k === 0 ? 'a' : 'b'}`">
                <div class="hd">
                  <span v-if="!single" class="vm" :class="k === 0 ? 'a' : 'b'">{{ k === 0 ? 'A' : 'B' }}</span>
                  <b>#{{ s.seq }} · {{ fmtTime(s.collected_at) }}</b>
                  <span v-if="s.tag" class="vtag pin"><Icon name="tag" small />{{ s.tag }}</span>
                  <span v-if="s.latest" class="tag t-blue">{{ $t('history.latest') }}</span>
                  <span class="faint small mono">v{{ s.id }}</span>
                  <button v-if="project.canWrite" class="btn btn-xs btn-ghost del-ver" type="button" :disabled="single" :title="single ? $t('devdel.lastVersionTip') : $t('devdel.deleteVersion')" :aria-label="`${$t('devdel.deleteVersion')} #${s.seq}`" :data-testid="`hist-card-del-${single ? 'only' : k === 0 ? 'a' : 'b'}`" @click="delVer = s.id"><Icon name="trash" small /></button>
                </div>
                <dl class="kv">
                  <dt>{{ $t('history.col.source') }}</dt><dd>{{ $t(`history.src.${s.imports[0]?.source_kind ?? 'file'}`) }} <span class="mono faint small">{{ s.source_name }}</span></dd>
                  <dt>{{ $t('history.col.actor') }}</dt><dd class="mono">{{ s.imports[0]?.actor }}</dd>
                  <dt>{{ $t('history.linesNodes') }}</dt><dd class="mono">{{ s.lines }} / {{ s.nodes ?? '—' }}</dd>
                  <dt>{{ $t('history.parsedKb') }}</dt><dd class="mono">{{ s.kb_version }}<span v-if="!s.kb_current" class="tag t-amber" style="margin-left: 6px">{{ $t('history.kbOld') }}</span></dd>
                  <dt>{{ $t('history.col.fp') }}</dt><dd class="mono faint" :title="s.fingerprint">sha256:{{ s.fingerprint.slice(0, 8) }}…</dd>
                  <dt>{{ $t('history.col.vs') }}</dt><dd><span v-if="s.vs_previous" class="cnts"><span class="a">+{{ s.vs_previous.added }}</span><span class="m">~{{ s.vs_previous.modified + s.vs_previous.renamed }}</span><span class="d">−{{ s.vs_previous.removed }}</span><span v-if="s.vs_previous.fmt" class="f">{{ $t('history.fmt') }} {{ s.vs_previous.fmt }}</span></span><span v-else class="faint small">{{ $t('history.firstImport') }}</span></dd>
                </dl>
                <div v-if="s.import_count > 1" class="imports">×{{ s.import_count }} {{ $t('history.mergedImports') }}{{ s.imports.map((x) => `${fmtTime(x.imported_at)} · ${$t(`history.src.${x.source_kind}`)} · ${x.actor}`).join('；') }}</div>
              </div>
              <div v-if="!single && k === 0" class="abarrow"><Icon name="chevR" /></div>
            </template>
          </div>
        </section>

        <!-- ===================== 只有一个快照 ===================== -->
        <section v-if="single" class="panel mt12" data-testid="hist-single">
          <div class="empty">
            <svg class="art" viewBox="0 0 120 84" aria-hidden="true"><line x1="10" y1="50" x2="110" y2="50" stroke="var(--line-strong)" stroke-width="2" /><circle cx="40" cy="50" r="8" fill="var(--surface)" stroke="var(--ink-3)" stroke-width="2" /><circle cx="84" cy="50" r="8" fill="none" stroke="var(--line-strong)" stroke-width="2" stroke-dasharray="3 3" /><text x="84" y="30" text-anchor="middle" font-size="12" fill="var(--ink-3)">?</text></svg>
            <h3>{{ $t('history.singleTitle') }}</h3>
            <p>{{ $t('history.singleText') }}</p>
            <div class="row"><router-link class="btn btn-primary" :to="{ name: 'devices' }"><Icon name="upload" small />{{ $t('history.import') }}</router-link></div>
            <div class="cmdline" style="max-width: 520px"><span class="pfx">$</span>lmesh config import {{ tl.device.name }}.cfg</div>
          </div>
        </section>

        <template v-else>
          <div v-if="diffError" class="notice err mt12" data-testid="hist-diff-error"><Icon name="err" /><div class="grow">{{ diffError }}</div><button class="btn btn-sm" type="button" @click="loadDiff">{{ $t('c.retry') }}</button></div>
          <div v-if="diffLoading && !diff" class="empty mt12"><p>{{ $t('c.loading') }}</p></div>

          <template v-if="diff">
            <!-- 汇总 -->
            <div class="sumrow" data-testid="hist-summary" :class="{ busy: diffLoading }">
              <div><div class="v add">{{ diff.summary.added }}</div><div class="k"><span class="dk added">{{ kindName('added') }}</span></div></div>
              <div><div class="v mod">{{ diff.summary.modified }}</div><div class="k"><span class="dk modified">{{ kindName('modified') }}</span></div></div>
              <div><div class="v del">{{ diff.summary.removed }}</div><div class="k"><span class="dk removed">{{ kindName('removed') }}</span></div></div>
              <div><div class="v ren">{{ diff.summary.renamed }}</div><div class="k"><span class="dk renamed">{{ kindName('renamed') }}</span></div></div>
              <div><div class="v fmt">{{ diff.summary.fmt + diff.summary.noneff }}</div><div class="k" :title="$t('history.notCountedTip')">{{ $t('history.notCounted', { fmt: diff.summary.fmt, eq: diff.summary.noneff }) }}</div></div>
              <div v-if="domRows.length" class="dd">
                <div class="domdist">
                  <div v-for="r in domRows" :key="r.d" class="r">
                    <span>{{ domName(r.d) }}</span>
                    <div class="stackbar"><i v-if="r.a" :style="{ background: 'var(--d-add)', width: `${(r.a / r.max) * 100}%` }" /><i v-if="r.m" :style="{ background: 'var(--d-mod)', width: `${(r.m / r.max) * 100}%` }" /><i v-if="r.r" :style="{ background: 'var(--d-del)', width: `${(r.r / r.max) * 100}%` }" /></div>
                    <b>{{ r.t }}</b>
                  </div>
                </div>
              </div>
            </div>

            <!-- 知识库版本不同 -->
            <div v-if="diff.kb.differs && rebuild" class="notice ok kbnote" data-testid="hist-kb-rebuilt"><Icon name="ok" /><div class="grow">{{ $t('history.rebuiltText', { kb: diff.kb.current }) }}</div><button class="btn btn-sm btn-ghost" type="button" @click="rebuild = false">{{ $t('history.unrebuild') }}</button></div>
            <div v-else-if="diff.kb.differs" class="notice warn kbnote" data-testid="hist-kb-differs"><Icon name="warn" /><div class="grow"><b>{{ $t('history.kbDiffersTitle') }}</b>（A：KB {{ diff.kb.a }}，B：KB {{ diff.kb.b }}）{{ $t('history.kbDiffersText') }}</div><button class="btn btn-sm" type="button" data-testid="hist-rebuild" @click="rebuild = true"><Icon name="refresh" small />{{ $t('history.rebuild', { kb: diff.kb.current }) }}</button></div>
            <div v-else-if="diff.a.graph === 'rebuilt' || diff.b.graph === 'rebuilt'" class="notice kbnote"><Icon name="info" /><div class="grow">{{ $t('history.autoRebuilt') }}</div></div>

            <!-- 操作 -->
            <div class="actrow">
              <button class="btn" type="button" :disabled="restoring" data-testid="hist-restore" @click="doRestore"><Icon name="rollback" small />{{ restoring ? $t('c.running') : $t('history.restore') }}</button>
              <button class="btn btn-ghost" type="button" :disabled="!!reporting" data-testid="hist-report-zh" @click="report('zh-CN')"><Icon name="download" small />{{ $t('history.reportZh') }}</button>
              <button class="btn btn-ghost" type="button" :disabled="!!reporting" data-testid="hist-report-en" @click="report('en')"><Icon name="download" small />{{ $t('history.reportEn') }}</button>
              <AiEntryButton v-if="aiScope" :skills="['diff-explain']" :busy="aiState === 'running'" @run="runAi" />
              <div class="cmdline"><span class="pfx">$</span><span>{{ cli }}</span><button class="btn btn-xs btn-ghost ml-auto" type="button" @click="copy(cli)"><Icon name="copy" small />{{ $t('c.copy') }}</button></div>
            </div>

            <div v-if="aiScope" v-show="aiShown" class="hist-ai" data-testid="hist-ai">
              <AiSuggestPanel ref="aiPanel" skill="diff-explain" :params="aiParams" :scope="aiScope" @state="aiState = $event" @changed="aiCov?.reload()" @jump="aiJump" />
              <AiCoverageBar ref="aiCov" skill="diff-explain" :scope="aiScope" @loaded="coverage = $event" @jump="aiJump" />
            </div>

            <!-- 标签页 -->
            <FullscreenPane class="panel hw" :title="tl.device.name" data-testid="hist-fs">
              <div class="tabs" role="tablist">
                <button type="button" role="tab" :aria-selected="tab === 'graph'" data-testid="hist-tab-graph" @click="tab = 'graph'">{{ $t('history.tabGraph') }} <span class="count">{{ shownCount }}</span></button>
                <button type="button" role="tab" :aria-selected="tab === 'text'" data-testid="hist-tab-text" @click="tab = 'text'">{{ $t('history.tabText') }}<span v-if="diff.text" class="count">+{{ diff.text.stats.added }} −{{ diff.text.stats.removed }}</span></button>
                <button type="button" role="tab" :aria-selected="tab === 'object'" data-testid="hist-tab-object" @click="tab = 'object'">{{ $t('history.tabObject') }}</button>
                <FullscreenButton size="xs" class="tabs-fs" />
              </div>

              <!-- 图差异 -->
              <div v-if="tab === 'graph'" class="gd">
                <div class="gd-list" data-testid="hist-graph-list">
                  <div class="gd-tools">
                    <label class="check"><input v-model="effOnly" type="checkbox" data-testid="hist-eff-only"> <span>{{ $t('history.effOnly') }}</span></label>
                    <span class="small faint">{{ $t('history.effOnlyHint', { n: diff.summary.noneff }) }}</span>
                  </div>
                  <template v-for="g in groups" :key="g.domain">
                    <div class="dg-h">{{ domName(g.domain) }}<span class="cnt">{{ g.items.length + g.noneff.length }}</span></div>
                    <div v-for="it in g.items" :key="it.object" class="di" :class="{ 'is-sel': sel === it.object, 'cov-ai': covMarks[it.object] === 'cov', uncov: covMarks[it.object] === 'uncov' }" tabindex="0" data-testid="hist-item" @click="pick(it.object)" @keydown.enter="pick(it.object)">
                      <div><span class="dk" :class="it.kind">{{ kindName(it.kind) }}</span></div>
                      <div class="nm">
                        <template v-if="it.kind === 'renamed' && it.from && it.to"><code :title="it.from">{{ objLabel(it.from) }}</code><span class="faint">⇢</span><code :title="it.to">{{ objLabel(it.to) }}</code></template>
                        <code v-else :title="it.object">{{ objLabel(it.object) }}</code>
                        <span class="kd">{{ typeName(it.schema) }}</span>
                      </div>
                      <div v-if="it.changes.length" class="chg">
                        <div v-for="c in it.changes.slice(0, 9)" :key="c.node" class="ch">
                          <span class="f">{{ c.field }}</span>
                          <template v-if="it.kind === 'added' || !c.a"><span class="n"><span v-if="c.b?.origin === 'default'" class="dv" :data-k="$t('src.default')">{{ valText(c.b) }}</span><template v-else>{{ valText(c.b) }}</template></span></template>
                          <template v-else-if="it.kind === 'removed' || !c.b"><span class="o">{{ valText(c.a) }}</span></template>
                          <template v-else>
                            <span class="o"><span v-if="c.a.origin === 'default'" class="dv" :data-k="$t('src.default')">{{ valText(c.a) }}</span><template v-else>{{ valText(c.a) }}</template></span>
                            <span class="ar">→</span>
                            <span class="n"><span v-if="c.b.origin === 'default'" class="dv" :data-k="$t('src.default')">{{ valText(c.b) }}</span><template v-else>{{ valText(c.b) }}</template></span>
                          </template>
                        </div>
                        <div v-if="it.changes.length > 9" class="ch faint">{{ $t('history.moreAttrs', { n: it.changes.length - 9 }) }}</div>
                      </div>
                    </div>
                    <div v-for="n in g.noneff" :key="`ne-${n.object}`" class="di" :class="{ 'is-sel': sel === n.object }" tabindex="0" data-testid="hist-noneff" @click="pick(n.object)">
                      <div><span class="dk equal">{{ $t('history.kind.equal') }}</span></div>
                      <div class="nm"><code :title="n.object">{{ objLabel(n.object) }}</code><span class="kd">{{ typeName(n.schema) }}</span></div>
                      <div class="chg">
                        <div v-for="r in n.rows" :key="r.node" class="ch"><span class="f">{{ r.node.slice(n.object.length + 1) || r.schema }}</span><span class="o">{{ r.a.raw ?? valText(r.a) }}</span><span class="ar">→</span><span class="n">{{ r.b.raw ?? valText(r.b) }}</span><span class="eqn">{{ $t(`history.noneff.${r.reason}`) }}</span></div>
                      </div>
                    </div>
                  </template>
                  <div v-if="!groups.length" class="empty" data-testid="hist-equal"><Icon name="ok" /><h3>{{ $t('history.sameTitle') }}</h3><p>{{ diff.summary.noneff || diff.summary.fmt ? $t('history.sameText') : $t('history.sameText2') }}</p></div>
                </div>

                <div class="gd-det" data-testid="hist-detail">
                  <div v-if="!selItem && !selNoneff" class="panel-b"><div class="empty" style="padding: 30px 10px"><Icon name="history" /><h3>{{ $t('history.pickTitle') }}</h3><p>{{ $t('history.pickText') }}</p></div></div>
                  <template v-else-if="selItem">
                    <div class="panel-h"><h3>{{ typeName(selItem.schema) }}</h3><span class="dk" :class="selItem.kind">{{ kindName(selItem.kind) }}</span></div>
                    <div class="panel-b">
                      <div class="det-h"><code>{{ objLabel(selItem.object) }}</code><span class="tag mono">{{ selItem.object }}</span></div>
                      <table v-if="selItem.changes.length || selItem.kind === 'renamed'" class="avb">
                        <thead><tr><th>{{ $t('history.attr') }}</th><th><span class="vm a sm">A</span></th><th><span class="vm b sm">B</span></th></tr></thead>
                        <tbody>
                          <tr v-if="selItem.kind === 'renamed'" class="chg"><td class="f">name</td><td class="a">{{ selItem.from }}</td><td class="b">{{ selItem.to }}</td></tr>
                          <tr v-for="c in selItem.changes" :key="c.node" class="chg">
                            <td class="f" :title="c.schema">{{ c.field }}</td>
                            <td class="a"><template v-if="c.a"><span v-if="c.a.origin === 'default'" class="dv" :data-k="$t('src.default')">{{ valText(c.a) }}</span><template v-else>{{ valText(c.a) }}</template></template><template v-else>—</template></td>
                            <td class="b"><template v-if="c.b"><span v-if="c.b.origin === 'default'" class="dv" :data-k="$t('src.default')">{{ valText(c.b) }}</span><template v-else>{{ valText(c.b) }}</template></template><template v-else>—</template></td>
                          </tr>
                        </tbody>
                      </table>
                      <div v-for="side in (['a', 'b'] as const)" :key="side" class="mini">
                        <div class="mh"><span class="vm sm" :class="side">{{ side.toUpperCase() }}</span>#{{ side === 'a' ? sa?.seq : sb?.seq }} · {{ fmtTime((side === 'a' ? sa : sb)?.collected_at ?? '') }}<span v-if="(side === 'a' ? selItem.lines_a : selItem.lines_b).length" class="ml-auto mono">{{ $t('history.lineRange', { a: (side === 'a' ? selItem.lines_a : selItem.lines_b)[0], b: (side === 'a' ? selItem.lines_a : selItem.lines_b).slice(-1)[0] }) }}</span></div>
                        <div v-if="!(side === 'a' ? selItem.lines_a : selItem.lines_b).length" class="none">{{ $t('history.notPresent') }}</div>
                        <div v-else class="code"><div v-for="l in mini(side === 'a' ? selItem.lines_a : selItem.lines_b, side)" :key="l.n" class="l"><span class="n">{{ l.n }}</span><span class="g" /><span class="t">{{ l.t }}</span></div></div>
                      </div>
                      <div class="row wrap">
                        <button class="btn btn-sm" type="button" data-testid="hist-go-object" @click="goObject(selItem.object)"><Icon name="history" small />{{ $t('history.viewObject') }}</button>
                        <button class="btn btn-sm btn-ghost" type="button" data-testid="hist-go-text" @click="locate(selItem.object)"><Icon name="compare" small />{{ $t('history.locate') }}</button>
                      </div>
                    </div>
                  </template>
                  <template v-else-if="selNoneff">
                    <div class="panel-h"><h3>{{ typeName(selNoneff.schema) }}</h3><span class="dk equal">{{ $t('history.kind.equal') }}</span></div>
                    <div class="panel-b">
                      <div class="det-h"><code>{{ objLabel(selNoneff.object) }}</code></div>
                      <p class="muted small">{{ $t('history.noneffText') }}</p>
                      <table class="avb">
                        <thead><tr><th>{{ $t('history.attr') }}</th><th><span class="vm a sm">A</span></th><th><span class="vm b sm">B</span></th></tr></thead>
                        <tbody><tr v-for="r in selNoneff.rows" :key="r.node"><td class="f">{{ r.node.slice(selNoneff.object.length + 1) || r.schema }}</td><td class="a">{{ r.a.raw ?? valText(r.a) }}<span class="faint"> ({{ r.a.origin === 'default' ? $t('src.default') : $t('src.explicit') }})</span></td><td class="b">{{ r.b.raw ?? valText(r.b) }}<span class="faint"> ({{ r.b.origin === 'default' ? $t('src.default') : $t('src.explicit') }})</span></td></tr></tbody>
                      </table>
                      <div class="row wrap"><button class="btn btn-sm btn-ghost" type="button" @click="locate(selNoneff.object)"><Icon name="compare" small />{{ $t('history.locate') }}</button></div>
                    </div>
                  </template>
                </div>
              </div>

              <!-- 配置差异 -->
              <template v-else-if="tab === 'text'">
                <div class="td-h">
                  <div><span class="vm a">A</span><b>#{{ sa?.seq }}</b>{{ fmtTime(sa?.collected_at ?? '') }}<span class="faint">{{ $t('history.nLines', { n: sa?.lines }) }}</span></div>
                  <div><span class="vm b">B</span><b>#{{ sb?.seq }}</b>{{ fmtTime(sb?.collected_at ?? '') }}<span class="faint">{{ $t('history.nLines', { n: sb?.lines }) }}</span><span class="ml-auto faint small">{{ tl.device.name }}</span></div>
                </div>
                <div v-if="!diff.text || diff.text.equal" class="empty"><Icon name="ok" /><p>{{ $t('history.textEqual') }}</p></div>
                <div v-else class="td" data-testid="hist-text">
                  <template v-for="sg in segs" :key="sg.type === 'row' ? `r${sg.i}` : `f${sg.key}`">
                    <div v-if="sg.type === 'fold'" class="fold"><Icon name="more" small /><button class="link-btn" type="button" data-testid="hist-unfold" @click="openFold(sg.key)">{{ $t('history.unfold', { n: sg.count }) }}</button></div>
                    <div v-else class="tr" :class="{ 'is-hl': isHl(sg.row), fmtrow: sg.row.kind === 'ch' && sg.row.fmt }" @click="rowClick(sg.row)">
                      <div class="tc" :class="sg.row.kind === 'eq' ? '' : sg.row.a ? 'del' : 'void'">
                        <span class="n">{{ sg.row.a?.a ?? '' }}</span><span class="g" />
                        <span class="t"><template v-if="marks(sg.row)"><template v-for="(p, k) in marks(sg.row)![0]" :key="k"><mark v-if="p.mark">{{ p.s }}</mark><template v-else>{{ p.s }}</template></template></template><template v-else>{{ sg.row.a?.text ?? '' }}</template></span>
                      </div>
                      <div class="tc" :class="sg.row.kind === 'eq' ? '' : sg.row.b ? 'add' : 'void'">
                        <span class="n">{{ sg.row.b?.b ?? '' }}</span><span class="g" />
                        <span class="t"><template v-if="marks(sg.row)"><template v-for="(p, k) in marks(sg.row)![1]" :key="k"><mark v-if="p.mark">{{ p.s }}</mark><template v-else>{{ p.s }}</template></template></template><template v-else>{{ sg.row.b?.text ?? '' }}</template></span>
                      </div>
                    </div>
                  </template>
                </div>
                <div class="panel-f small faint">{{ $t('history.textHint', { fmt: diff.text?.stats.fmt ?? 0 }) }}</div>
              </template>

              <!-- 对象历史 -->
              <template v-else>
                <div class="oh-tools">
                  <span class="small muted">{{ $t('history.object') }}</span>
                  <select v-model="objNode" class="select" data-testid="hist-obj-select">
                    <option value="" disabled>{{ $t('history.pickObject') }}</option>
                    <optgroup v-for="g in optList" :key="g.group" :label="g.group">
                      <option v-for="o in g.items" :key="o" :value="o">{{ objLabel(o) }}</option>
                    </optgroup>
                  </select>
                  <span class="small faint">{{ $t('history.matrixHint') }}</span>
                  <div v-if="objNode" class="cmdline ml-auto" style="flex: 0 1 auto"><span class="pfx">$</span>lmesh history object {{ tl.device.name }} "{{ objNode }}"</div>
                </div>
                <div v-if="objError" class="notice err" style="margin: 10px 12px"><Icon name="err" /><div class="grow">{{ objError }}</div></div>
                <div v-else-if="objLoading" class="empty"><p>{{ $t('c.loading') }}</p></div>
                <div v-else-if="!objHist" class="empty"><Icon name="history" /><p>{{ $t('history.pickObjectText') }}</p></div>
                <template v-else>
                  <div class="ohm-wrap" data-testid="hist-obj-matrix">
                    <table class="ohm">
                      <colgroup><col style="width: 200px"><col v-for="s in objHist.snapshots" :key="s.id"></colgroup>
                      <thead>
                        <tr>
                          <th class="rh" />
                          <th v-for="s in objHist.snapshots" :key="s.id" :class="{ inab: !!sa && !!sb && s.seq >= sa.seq && s.seq <= sb.seq }">
                            <span v-if="s.id === sa?.id" class="vm a sm">A</span><span v-else-if="s.id === sb?.id" class="vm b sm">B</span>
                            <span class="dt">#{{ s.seq }} {{ fmtTime(s.collected_at).slice(5, 10) }}</span>
                            <span class="src">{{ s.tag ?? $t(`history.src.${snapOf(s.seq)?.imports[0]?.source_kind ?? 'file'}`) }}</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="r in matrix" :key="r.f">
                          <th class="rh" :title="r.f"><code>{{ r.f }}</code></th>
                          <td v-for="c in r.cells" :key="c.from" :colspan="c.span" :class="{ abs: c.kind === 'abs', first: c.first }" :data-x="c.label ? $t(`history.${c.label}`) : undefined">
                            <span v-if="c.kind === 'val'" class="seg-v" :class="c.cls" :data-k="c.cls === 'def' ? $t('src.default') : undefined" :title="c.cls === 'none' ? $t('history.notSet') : showVal(c.value?.value)">{{ c.cls === 'none' ? $t('history.notSet') : showVal(c.value?.value) }}</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="section-t" style="margin: 14px 14px 0">{{ $t('history.changeLog') }}</div>
                  <div class="oh-log" data-testid="hist-obj-log">
                    <div v-for="e in objEvents" :key="e.seq" class="ev" :class="e.kind">
                      <span class="t">#{{ e.seq }} {{ fmtTime(e.snap.collected_at).slice(5) }}</span>
                      <span class="rail"><i /></span>
                      <div class="body">
                        <div v-if="e.kind === 'add'">{{ e.seq === objHist.snapshots[0].seq ? $t('history.evFirst') : $t('history.evAdd') }}</div>
                        <div v-else-if="e.kind === 'del'">{{ $t('history.evDel') }}</div>
                        <div v-else><template v-for="(f, k) in e.fields" :key="f.field"><template v-if="k">；</template><code>{{ f.field }}</code> {{ f.a?.value === null || f.a === null ? $t('history.notSet') : showVal(f.a.value) }}<span v-if="f.a?.origin === 'default'" class="faint">（{{ $t('src.default') }}）</span> → {{ f.b === null || f.b.value === null ? $t('history.notSet') : showVal(f.b.value) }}<span v-if="f.b?.origin === 'default'" class="faint">（{{ $t('src.default') }}）</span></template></div>
                        <div class="who">{{ snapOf(e.seq) ? `${$t(`history.src.${snapOf(e.seq)!.imports[0]?.source_kind ?? 'file'}`)} · ${snapOf(e.seq)!.imports[0]?.actor ?? ''}` : '' }}</div>
                      </div>
                    </div>
                    <p v-if="!objEvents.length" class="small muted">{{ $t('history.noEvents') }}</p>
                  </div>
                </template>
              </template>
            </FullscreenPane>
          </template>
        </template>
      </template>
    </div>

    <!-- 回到 A 的变更脚本 -->
    <div v-if="restore" class="modal-back" @click.self="restore = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(820px, 100%)" data-testid="hist-restore-dialog">
        <div class="modal-h"><h2>{{ $t('history.restoreTitle', { a: sa?.seq, b: sb?.seq }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="restore = null"><Icon name="x" /></button></div>
        <div class="modal-b stack" style="gap: 12px">
          <div v-if="restore.change.equal" class="notice ok"><Icon name="ok" /><div>{{ $t('history.restoreEqual') }}</div></div>
          <template v-else>
            <p class="small muted">{{ $t('history.restoreText', { n: restore.change.ops.length }) }}<span v-if="restore.change.verify" :style="{ color: restore.change.verify.ok ? 'var(--teal-ink)' : 'var(--amber-ink)' }"> · {{ restore.change.verify.ok ? $t('history.verifyOk') : $t('history.verifyBad') }}</span></p>
            <pre class="block restore-script" data-testid="hist-restore-script">{{ restore.change.script_plain }}</pre>
          </template>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" :disabled="restore.change.equal" @click="copy(restore.change.script_plain)"><Icon name="copy" small />{{ $t('c.copy') }}</button>
          <button class="btn" type="button" :disabled="restore.change.equal" @click="dlScript"><Icon name="download" small />{{ $t('history.dlScript') }}</button>
          <router-link v-if="changeLink" class="btn btn-primary" :to="changeLink" data-testid="hist-to-change"><Icon name="branch" small />{{ $t('history.toChange') }}</router-link>
        </div>
      </div>
    </div>
    <div v-if="toast" class="m5-toast" role="status">{{ toast }}</div>
    <DevDelDialog v-if="delVer !== null && devId !== null" :device-id="devId" :version-id="delVer" @close="delVer = null" @deleted="onVersionDeleted" />
  </main>
</template>

<style scoped>
.hist-ai { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.di.cov-ai { box-shadow: inset 3px 0 0 var(--violet); }
.di.uncov { background: color-mix(in srgb, var(--amber-soft) 50%, transparent); }
.hbar { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }
.hbar .lbl { font-size: 12px; color: var(--ink-2); }
.hbar .select { width: auto; max-width: 280px; }
.mb12 { margin-bottom: 12px; }

.tl-h { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); }
.tl-h h2 { flex: none; }
.tl-h .meta { color: var(--ink-3); font-size: 12px; }
.tl-h .abpick { display: inline-flex; align-items: center; gap: 6px; }
.tl-h .abpick .select { width: auto; max-width: 260px; height: 28px; font-size: 12px; }
.tl-foot { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; padding: 6px 14px 10px; font-size: 11.5px; color: var(--ink-2); }
.tl-foot span { display: inline-flex; align-items: center; gap: 5px; }
.tl-foot i.sq { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }

.abcards { display: grid; grid-template-columns: minmax(0, 1fr) 34px minmax(0, 1fr); border-top: 1px solid var(--line); }
.abcards.one { grid-template-columns: minmax(0, 1fr); }
.abcard { padding: 10px 14px; min-width: 0; }
.abcard .hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.abcard .hd b { font: 600 13px var(--font-mono); }
.abcard .hd .del-ver { margin-left: auto; color: var(--ink-3); }
.abcard .hd .del-ver:hover:not(:disabled) { color: var(--red-ink); background: var(--red-soft); }
.abcard .kv { grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr); gap: 3px 12px; font-size: 12px; }
.abcard .kv dd { font-size: 12px; min-width: 0; overflow-wrap: anywhere; }
.abcard .imports { margin-top: 6px; font-size: 11.5px; color: var(--ink-2); }
.abarrow { display: flex; align-items: center; justify-content: center; color: var(--ink-3); border-left: 1px solid var(--line); border-right: 1px solid var(--line); background: var(--surface-2); }
.snaptbl { border-top: 1px solid var(--line); max-height: 340px; overflow: auto; }
.snapnote { padding: 6px 14px; margin: 0; }
.tagedit { display: inline-flex; gap: 4px; align-items: center; }
.tagedit .input { height: 24px; width: 150px; font-size: 12px; }
.vtag .link-btn { display: inline-flex; padding: 0; margin-left: 2px; color: inherit; }
.cnts { display: inline-flex; gap: 6px; font: 600 11.5px var(--font-mono); }
.cnts .a { color: var(--d-add-ink); }
.cnts .m { color: var(--d-mod-ink); }
.cnts .d { color: var(--d-del-ink); }
.cnts .f { color: var(--ink-3); font-weight: 400; }

.sumrow { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-top: 12px; }
.sumrow.busy { opacity: .6; }
.sumrow > div { padding: 10px 14px; border-left: 1px solid var(--line); min-width: 0; }
.sumrow > div:first-child { border-left: 0; }
.sumrow .v { font: 600 21px/1.25 var(--font-display); }
.sumrow .k { font-size: 12px; color: var(--ink-2); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.sumrow > div.dd { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--line); padding: 8px 14px; }
.sumrow .v.add { color: var(--d-add-ink); }
.sumrow .v.mod { color: var(--d-mod-ink); }
.sumrow .v.del { color: var(--d-del-ink); }
.sumrow .v.ren { color: var(--d-ren-ink); }
.sumrow .v.fmt { color: var(--ink-3); }
.domdist { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 5px 18px; }
.domdist .r { display: grid; grid-template-columns: max-content minmax(30px, 1fr) 16px; gap: 8px; align-items: center; font-size: 11.5px; color: var(--ink-2); }
.domdist .r .stackbar { height: 7px; }
.domdist .r b { font-weight: 600; color: var(--ink); text-align: right; }
.actrow { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; margin-top: 12px; }
.actrow .cmdline { flex: 1; min-width: 300px; }
.kbnote { margin-top: 12px; }

.hw { margin-top: 12px; }
.hw .tabs { margin: 0; padding: 0 8px; }
.hw .tabs-fs { margin-left: auto; align-self: center; }
.hw.is-fs { overflow: auto; }
.hw.is-fs .gd { flex: 1; min-height: 0; }
.hw.is-fs .gd-list, .hw.is-fs .gd-det { max-height: none; }
.hw.is-fs .td { max-height: none; flex: 1; min-height: 0; }
.gd { display: grid; grid-template-columns: minmax(0, 1fr) 420px; min-height: 420px; }
.gd-list { border-right: 1px solid var(--line); overflow: auto; max-height: 68vh; }
.gd-tools { min-height: 40px; display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--surface); position: sticky; top: 0; z-index: 2; }
.dg-h { display: flex; align-items: center; gap: 8px; padding: 7px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); font-size: 12px; font-weight: 600; color: var(--ink-2); }
.dg-h .cnt { margin-left: auto; font-weight: 400; color: var(--ink-3); }
.di { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 3px 10px; padding: 8px 12px; border-bottom: 1px solid var(--line); cursor: pointer; }
.di:hover { background: var(--surface-2); }
.di.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.di .nm { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
.di .nm code { font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }
.di .nm .kd { font-size: 11.5px; color: var(--ink-3); }
.di .chg { grid-column: 2; display: flex; flex-direction: column; gap: 2px; }
.ch { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; font-size: 12px; color: var(--ink-2); min-width: 0; }
.ch .f { font: 11.5px var(--font-mono); color: var(--ink-3); min-width: 92px; }
.ch .o { font: 12px var(--font-mono); color: var(--d-del-ink); text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--d-del) 55%, transparent); overflow-wrap: anywhere; }
.ch .n { font: 12px var(--font-mono); color: var(--ink); overflow-wrap: anywhere; }
.ch .ar { color: var(--ink-3); }
.ch .eqn { font-size: 11px; color: var(--ink-3); font-style: italic; }
.gd-det { overflow: auto; max-height: 68vh; min-width: 0; }
.gd-det .panel-b { display: flex; flex-direction: column; gap: 12px; }
.det-h { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.det-h code { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.det-h .tag { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.avb { width: 100%; border-collapse: collapse; font-size: 12px; }
.avb th { text-align: left; font-weight: 600; color: var(--ink-2); padding: 5px 6px; border-bottom: 1px solid var(--line); background: var(--surface-2); white-space: nowrap; }
.avb td { padding: 5px 6px; border-bottom: 1px solid var(--line); vertical-align: top; font-family: var(--font-mono); font-size: 11.5px; overflow-wrap: anywhere; }
.avb td.f { color: var(--ink-3); }
.avb tr.chg td.b { background: color-mix(in srgb, var(--d-mod-soft) 80%, transparent); }
.avb tr.chg td.a { background: color-mix(in srgb, var(--d-del-soft) 60%, transparent); }
.mini { border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.mini .mh { display: flex; align-items: center; gap: 6px; padding: 5px 8px; font-size: 11.5px; color: var(--ink-2); background: var(--surface-2); border-bottom: 1px solid var(--line); }
.mini .none { padding: 8px 10px; font-size: 12px; color: var(--ink-3); font-style: italic; }

.td-h { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); border-bottom: 1px solid var(--line); background: var(--surface-2); }
.td-h > div { padding: 7px 12px; display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--ink-2); min-width: 0; }
.td-h > div + div { border-left: 1px solid var(--line); }
.td-h b { font: 600 12px var(--font-mono); color: var(--ink); }
.td { max-height: 68vh; overflow: auto; font: 12px/20px var(--font-mono); }
.tr { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); cursor: pointer; }
.tc { display: grid; grid-template-columns: 44px 18px minmax(0, 1fr); min-width: 0; }
.tc + .tc { border-left: 1px solid var(--line); }
.tc .n { text-align: right; padding-right: 8px; color: var(--ink-3); background: var(--surface-2); border-right: 1px solid var(--line); user-select: none; font-size: 11px; }
.tc .g { text-align: center; font-weight: 700; }
.tc .t { white-space: pre; overflow: hidden; text-overflow: ellipsis; padding-right: 8px; }
.tc.del { background: color-mix(in srgb, var(--d-del-soft) 85%, transparent); }
.tc.del .g { color: var(--d-del-ink); }
.tc.del .g::before { content: "−"; }
.tc.del .n { box-shadow: inset 3px 0 0 var(--d-del); color: var(--d-del-ink); }
.tc.add { background: color-mix(in srgb, var(--d-add-soft) 85%, transparent); }
.tc.add .g { color: var(--d-add-ink); }
.tc.add .g::before { content: "+"; }
.tc.add .n { box-shadow: inset 3px 0 0 var(--d-add); color: var(--d-add-ink); }
.tc.void { background: repeating-linear-gradient(135deg, transparent 0 6px, color-mix(in srgb, var(--surface-3) 75%, transparent) 6px 8px); }
.tc.void .n { background: transparent; }
.tr.fmtrow .tc.del, .tr.fmtrow .tc.add { background: var(--surface-2); }
.tr.fmtrow .tc .g { color: var(--ink-3); }
.tr.is-hl .tc .n { background: var(--hl-line); color: var(--amber-ink); font-weight: 700; box-shadow: inset 3px 0 0 var(--hl-line-edge); }
.tr.is-hl .tc:not(.del):not(.add):not(.void) { background: color-mix(in srgb, var(--hl-line) 60%, transparent); }
.tr.is-hl .tc.del, .tr.is-hl .tc.add { outline: 1px solid var(--hl-line-edge); outline-offset: -1px; }
.tc .t mark { background: color-mix(in srgb, var(--d-mod) 40%, transparent); color: inherit; border-radius: 2px; }
.fold { display: flex; align-items: center; gap: 10px; padding: 3px 12px; background: var(--surface-3); color: var(--ink-2); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); font: 12px var(--font-ui); }
.fold button { font-size: 12px; }

.oh-tools { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--line); }
.oh-tools .select { width: auto; max-width: 420px; }
.ohm-wrap { overflow-x: auto; }
.ohm { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; min-width: 640px; }
.ohm th, .ohm td { border-bottom: 1px solid var(--line); padding: 0; height: 34px; }
.ohm thead th { font: 600 11px var(--font-ui); color: var(--ink-2); background: var(--surface-2); padding: 6px 4px; text-align: center; vertical-align: bottom; height: auto; }
.ohm thead th .dt { font: 600 11px var(--font-mono); color: var(--ink); display: block; }
.ohm thead th .src { font-weight: 400; color: var(--ink-3); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ohm thead th .vm { margin: 0 auto 3px; }
.ohm thead th.inab { background: color-mix(in srgb, var(--vb) 14%, var(--surface-2)); }
.ohm th.rh { text-align: left; padding: 0 10px; font: 12px var(--font-ui); color: var(--ink-2); background: var(--surface); position: sticky; left: 0; z-index: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ohm th.rh code { font-size: 11px; color: var(--ink-2); }
.ohm td { padding: 4px 3px; }
.ohm .seg-v { display: flex; align-items: center; height: 24px; padding: 0 8px; border-radius: 4px; background: var(--surface-2); border: 1px solid var(--line); font: 11.5px var(--font-mono); color: var(--ink); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; min-width: 0; }
.ohm .seg-v.chg { background: var(--d-mod-soft); border-color: var(--d-mod-line); box-shadow: inset 3px 0 0 var(--d-mod); }
.ohm .seg-v.new { background: var(--d-add-soft); border-color: var(--d-add-line); box-shadow: inset 3px 0 0 var(--d-add); }
.ohm .seg-v.def { background: transparent; border-style: dashed; border-color: var(--line-strong); color: var(--ink-2); }
.ohm .seg-v.def::after { content: attr(data-k); margin-left: 6px; font: 600 10px var(--font-ui); color: var(--ink-3); }
.ohm .seg-v.none { background: transparent; border-color: transparent; color: var(--ink-3); font-family: var(--font-ui); font-style: italic; }
.ohm td.abs { background: repeating-linear-gradient(135deg, transparent 0 6px, color-mix(in srgb, var(--surface-3) 85%, transparent) 6px 8px); }
.ohm td.abs.first::after { content: attr(data-x); display: block; text-align: center; font-size: 11px; color: var(--ink-3); font-style: italic; }
.oh-log { padding: 10px 14px; display: flex; flex-direction: column; }
.oh-log .ev { display: grid; grid-template-columns: 130px 18px minmax(0, 1fr); gap: 0 8px; align-items: start; }
.oh-log .ev .t { font: 11.5px var(--font-mono); color: var(--ink-2); padding-top: 2px; }
.oh-log .ev .rail { position: relative; height: 100%; min-height: 34px; }
.oh-log .ev .rail::before { content: ""; position: absolute; left: 8px; top: 0; bottom: 0; width: 2px; background: var(--line); }
.oh-log .ev:first-child .rail::before { top: 9px; }
.oh-log .ev:last-child .rail::before { bottom: auto; height: 9px; }
.oh-log .ev .rail i { position: absolute; left: 4px; top: 5px; width: 10px; height: 10px; border-radius: 50%; background: var(--surface); border: 2px solid var(--d-mod); }
.oh-log .ev.add .rail i { border-color: var(--d-add); }
.oh-log .ev.del .rail i { border-color: var(--d-del); }
.oh-log .ev .body { padding-bottom: 10px; font-size: 12.5px; overflow-wrap: anywhere; }
.oh-log .ev .body .who { font-size: 11.5px; color: var(--ink-3); }
.oh-log .ev .body code { font-size: 11.5px; }
.restore-script { max-height: 420px; overflow: auto; }

@media (max-width: 1500px) {
  .gd { grid-template-columns: minmax(0, 1fr) 360px; }
  .domdist { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .actrow .cmdline { flex-basis: 100%; }
}
@media (max-width: 1360px) { .abcard .kv { grid-template-columns: max-content minmax(0, 1fr); } }
@media (max-width: 1000px) {
  .gd { grid-template-columns: minmax(0, 1fr); }
  .gd-list { border-right: 0; border-bottom: 1px solid var(--line); }
  .abcards { grid-template-columns: minmax(0, 1fr); }
  .abarrow { height: 28px; transform: rotate(90deg); border: 0; background: transparent; }
  .sumrow { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
