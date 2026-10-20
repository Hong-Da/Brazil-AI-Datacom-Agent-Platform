<script setup lang="ts">
/**
 * 配置翻译（预览 DevelopDocs/ui-preview/M3/translate.html）：选源（设备 / 版本 / 粘贴）与目标 Profile、接口映射表 →
 * POST /translate → 告警分组、两侧原文联动、校验结果；“显示默认配置”时译文用 POST /render（canonical + with_defaults）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ModelApproxNote from '@/components/model-approx-note.vue'
import FullscreenPane from '@/components/FullscreenPane.vue'
import FullscreenButton from '@/components/FullscreenButton.vue'
import type { FsMode } from '@/components/fullscreen'
import HiddenLegend from '@/components/hidden-legend.vue'
import ShowDefaultToggle from '@/components/show-default-toggle.vue'
import TermName from '@/components/term-name.vue'
import M3Code from '@/components/m3-code.vue'
import { errorText, get, post } from '@/api'
import { rememberedFlag } from '@/stores/prefs'
import { saveText, toCsv } from '@/views/profiles/csv'
import type { Device } from '@/views/devices/logic'
import type { DeviceGraph, VersionInfo } from '@/views/compare/types'
import { mainInterfaces, mapCsvRows, toInterfaceMap, type MapRow } from '@/views/compare/ifmap'
import { ranges, splitLines, type CodeLine } from '@/views/m3/code'
import IfMapPanel from './translate/IfMapPanel.vue'
import WarnPanel from './translate/WarnPanel.vue'
import TranslateGapPanel from './ai-change/TranslateGapPanel.vue'
import DownloadDialog from './translate/DownloadDialog.vue'
import RuleSetPicker from '@/components/rule-set-picker.vue'
import NamingReportPanel from './translate-rules/NamingReportPanel.vue'
import { renamedLines } from './translate-rules/logic'
import {
  appendRaw, buildWarns, groupCounts, interfacesIn, interfacesInGraph, isVerifyItem, linesText, linkFromDst, linkFromSrc, outIndex,
  reportMd, srcIndex, warnCsvRows, warnDst, warnText, type ShownLine,
} from './translate/logic'
import { GROUPS, type Group, type RenderResult, type TranslateResult, type Warn } from './translate/types'
import VendorBadge from '@/components/vendor-badge.vue'

interface ProfileLite { id: string; title: string; vendor: string; family: string }

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))

// ---------------------------------------------------------------- 基础数据
const devices = ref<Device[]>([])
const profiles = ref<ProfileLite[]>([])
const loadError = ref('')
const versions = ref<VersionInfo[]>([])

async function loadBase(): Promise<void> {
  loadError.value = ''
  try {
    const [d, p] = await Promise.all([get<{ devices: Device[] }>('/devices'), get<{ profiles: ProfileLite[] }>('/kb/profiles')])
    devices.value = [...d.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    profiles.value = p.profiles
  } catch (e) {
    loadError.value = errorText(e)
  }
}

// ---------------------------------------------------------------- 源与目标
const mode = ref<'device' | 'paste'>(route.query.mode === 'paste' ? 'paste' : 'device')
const deviceId = ref<number | null>(route.query.device ? Number(route.query.device) : null)
const versionId = ref<number | null>(route.query.version ? Number(route.query.version) : null)
const pasteText = ref('')
const pasteProfile = ref('')
const target = ref<string>(String(route.query.to ?? ''))
const appendRawOpt = ref(true)
const ruleSet = ref<string>(String(route.query.rules ?? '')) // 翻译规则集（REQ-032），空串表示不使用

const device = computed(() => devices.value.find((d) => d.id === deviceId.value) ?? null)
const srcProfileId = computed(() => (mode.value === 'device' ? device.value?.profile ?? '' : pasteProfile.value))
const profileOf = (id: string) => profiles.value.find((p) => p.id === id) ?? null
const srcFamily = computed(() => profileOf(srcProfileId.value)?.family ?? '')
const vendorOf = (pid: string) => profileOf(pid)?.vendor ?? ''

/** 源配置的原文与配置图（设备：按版本取；粘贴：原文就是输入） */
const srcGraph = ref<DeviceGraph | null>(null)
const srcLoading = ref(false)
async function loadSource(): Promise<void> {
  srcGraph.value = null
  if (mode.value !== 'device' || deviceId.value === null) return
  srcLoading.value = true
  try {
    const q = versionId.value !== null ? `&version_id=${versionId.value}` : ''
    srcGraph.value = await get<DeviceGraph>(`/devices/${deviceId.value}/graph?raw=true${q}`)
  } catch {
    srcGraph.value = null
  } finally {
    srcLoading.value = false
  }
}
watch(deviceId, async (id) => {
  versions.value = []
  if (id === null) return
  try {
    versions.value = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions
  } catch { /* 版本列表取不到时用最新版本 */ }
  if (versionId.value !== null && !versions.value.some((v) => v.id === versionId.value)) versionId.value = null
})
watch([mode, deviceId, versionId], () => { void loadSource() })

/** 目标默认选另一个平台族的 Profile */
watch([srcFamily, profiles], () => {
  if (target.value && profileOf(target.value)) return
  const other = profiles.value.find((p) => srcFamily.value && p.family !== srcFamily.value)
  if (other) target.value = other.id
})

// ---------------------------------------------------------------- 接口映射表
const mapRows = ref<MapRow[]>([])
const mapDirty = ref(false)
const srcInterfaces = computed(() => {
  const g = mode.value === 'device' ? srcGraph.value : null
  const fromText = interfacesIn(g ? g.text ?? '' : pasteText.value)
  // Nokia 的端口不以 `interface X` 声明：文本里找不到时取配置图的顶层接口对象
  return mainInterfaces(fromText.length || !g ? fromText : interfacesInGraph(g.nodes ?? []))
})
function resetMap(): void {
  mapRows.value = srcInterfaces.value.map((a) => ({ a, b: '', how: 'none' }))
}
watch(srcInterfaces, (now, old) => { if ((now ?? []).join() !== (old ?? []).join()) resetMap() })
const ifMap = computed(() => toInterfaceMap(mapRows.value))
watch(ifMap, () => { if (result.value) mapDirty.value = JSON.stringify(ifMap.value) !== JSON.stringify(result.value.interface_map ?? {}) })

// ---------------------------------------------------------------- 翻译
const running = ref(false)
const runError = ref('')
const result = ref<TranslateResult | null>(null)
const srcText = ref('')
const ranAt = ref('')
const ms = ref(0)
const canRun = computed(() => !!target.value && (mode.value === 'device' ? deviceId.value !== null : !!pasteText.value.trim()))

async function run(): Promise<void> {
  if (!canRun.value) return
  running.value = true
  runError.value = ''
  const t0 = performance.now()
  const body: Record<string, unknown> = { to: target.value, interface_map: Object.keys(ifMap.value).length ? ifMap.value : null }
  if (ruleSet.value) body.rule_set = ruleSet.value
  if (mode.value === 'device') {
    body.device_id = deviceId.value
    if (versionId.value !== null) body.version_id = versionId.value
  } else {
    body.text = pasteText.value
    if (pasteProfile.value) body.profile = pasteProfile.value
  }
  try {
    const r = await post<TranslateResult>('/translate', body)
    if (mode.value === 'device' && !srcGraph.value) await loadSource()
    srcText.value = mode.value === 'device' ? srcGraph.value?.text ?? '' : pasteText.value
    result.value = r
    ms.value = Math.round(performance.now() - t0)
    ranAt.value = new Date().toLocaleString()
    sel.value = null
    filter.value = ''
    handled.value = {}
    linkSrc.value = []
    linkDst.value = []
    rendered.value = null
    mapDirty.value = false
    syncQuery()
    if (showDefault.value) void loadRendered()
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}

function syncQuery(): void {
  const q: Record<string, string> = { to: target.value }
  if (ruleSet.value) q.rules = ruleSet.value
  if (mode.value === 'paste') q.mode = 'paste'
  else if (deviceId.value !== null) {
    q.device = String(deviceId.value)
    if (versionId.value !== null) q.version = String(versionId.value)
  }
  void router.replace({ query: q })
}

// ---------------------------------------------------------------- 显示默认配置（含默认值的规范渲染）
const showDefault = rememberedFlag('m3-default')
const rendered = ref<RenderResult | null>(null)
const renderLoading = ref(false)
const renderError = ref('')
async function loadRendered(): Promise<void> {
  if (!result.value || rendered.value || renderLoading.value) return
  renderLoading.value = true
  renderError.value = ''
  try {
    rendered.value = await post<RenderResult>('/render', { text: result.value.text, profile: result.value.target.profile, canonical: true, with_defaults: true })
  } catch (e) {
    renderError.value = errorText(e)
  } finally {
    renderLoading.value = false
  }
}
watch(showDefault, (v) => { if (v) void loadRendered() })

// ---------------------------------------------------------------- 告警与行联动
const warns = computed<Warn[]>(() => (result.value ? buildWarns(result.value) : []))
const counts = computed(() => groupCounts(warns.value))
const filter = ref<Group | ''>('')
const sel = ref<string | null>(null)
const handled = ref<Record<string, boolean>>({})
const linkSrc = ref<number[]>([]) // 源配置行号（1 起）
const linkDst = ref<number[]>([]) // 译文行下标（0 起）
const selKind = ref<Group | ''>('')

const rawHeader = 'LMESH untranslated (outside the knowledge base), handle manually:'
const outLines = computed<ShownLine[]>(() => {
  if (!result.value) return []
  const base = showDefault.value && rendered.value ? rendered.value.lines : result.value.lines
  return appendRawOpt.value ? appendRaw(base, warns.value, rawHeader) : base
})
const outIdx = computed(() => outIndex(outLines.value))
const appliedMap = computed(() => result.value?.interface_map ?? {})
const dstOf = (w: Warn) => warnDst(w, outIdx.value, appliedMap.value)
const srcIdx = computed(() => srcIndex(mode.value === 'device' && result.value ? srcGraph.value?.nodes ?? [] : []))
const srcLines = computed(() => splitLines(srcText.value))

const srcCode = computed<CodeLine[]>(() => {
  const cls = new Map<number, string>()
  for (const w of warns.value) {
    if (w.group === 'default') continue
    const c = w.group === 'unsup' ? 'w-unsup' : w.group === 'raw' ? 'w-raw' : 'w-infer'
    for (const l of w.item.lines) if (!cls.has(l)) cls.set(l, c)
  }
  const linked = new Set(linkSrc.value)
  return srcLines.value.map((text, i) => ({ no: i + 1, text, cls: [cls.get(i + 1) ?? '', linked.has(i + 1) ? 'linked' : '', /^\s*[!#]/.test(text) ? 'c-cmt' : ''].join(' ') }))
})
const dstCode = computed<CodeLine[]>(() => {
  const cls = new Map<number, string>()
  for (const w of warns.value) {
    const c = w.group === 'default' && w.item.kind === 'default_differs' ? 'w-default' : w.group === 'infer' ? 'w-infer' : ''
    if (c) for (const i of dstOf(w)) if (!cls.has(i)) cls.set(i, c)
  }
  const linked = new Set(linkDst.value)
  const dflt = t('src.default')
  const renamed = renamedLines(outLines.value.map((l) => l.text), result.value?.naming)
  return outLines.value.map((l, i) => {
    const ghost = l.origin === 'default'
    return {
      no: l.no, text: l.text, ghost,
      tag: ghost && l.kind === 'command' ? dflt : undefined,
      cls: [l.warn ? 'w-raw' : cls.get(i) ?? '', linked.has(i) ? 'linked' : '', !ghost && l.kind === 'comment' ? 'c-cmt' : '', renamed.has(i) ? 'w-rename' : ''].join(' '),
    }
  })
})

const srcPane = ref<InstanceType<typeof M3Code>>()
const dstPane = ref<InstanceType<typeof M3Code>>()

function selectLines(src: number[], dst: number[], kind: Group | ''): void {
  linkSrc.value = src
  linkDst.value = dst
  selKind.value = kind
  void nextTick(() => {
    if (src.length) srcPane.value?.scrollToIndex(Math.min(...src) - 1)
    if (dst.length) dstPane.value?.scrollToIndex(Math.min(...dst))
    requestAnimationFrame(drawBridge)
  })
}
function selectWarn(id: string | null, fromLine = false): void {
  sel.value = id
  const w = warns.value.find((x) => x.id === id)
  if (!w) {
    selectLines([], [], '')
    return
  }
  selectLines(w.item.lines, dstOf(w), w.group)
  if (fromLine) void nextTick(() => document.querySelector(`.wi[data-w="${id}"]`)?.scrollIntoView({ block: 'nearest' }))
}
function pickSrc(i: number): void {
  const lk = linkFromSrc(i + 1, warns.value, dstOf, srcIdx.value.lineNodes, outIdx.value, appliedMap.value)
  if (lk.warn) selectWarn(lk.warn, true)
  else {
    sel.value = null
    selectLines(lk.src, lk.dst, '')
  }
}
function pickDst(i: number): void {
  const lk = linkFromDst(i, outLines.value, warns.value, dstOf, srcIdx.value.nodeLines, appliedMap.value)
  if (lk.warn) selectWarn(lk.warn, true)
  else {
    sel.value = null
    selectLines(lk.src, lk.dst, '')
  }
}
function go(side: 's' | 'd', idx: number): void {
  if (side === 's') srcPane.value?.scrollToIndex(idx)
  else dstPane.value?.scrollToIndex(idx)
  requestAnimationFrame(drawBridge)
}
function setFilter(g: Group | ''): void {
  filter.value = g
}
function toggleSum(g: Group): void {
  filter.value = filter.value === g ? '' : g
}

// ---------------------------------------------------------------- 两侧之间的连接带
const bridgeSvg = ref<SVGSVGElement>()
const bands = ref<string[]>([])
const stubs = ref<string[]>([])
const offs = ref<{ x: number; y: number; t: string; anchor: string }[]>([])
const bridgeW = ref(0)
const bridgeH = ref(0)

function drawBridge(): void {
  const svg = bridgeSvg.value
  const cs = srcPane.value?.box
  const cd = dstPane.value?.box
  bands.value = []
  stubs.value = []
  offs.value = []
  if (!svg || !cs || !cd) return
  const box = svg.getBoundingClientRect()
  const W = box.width
  const H = box.height
  bridgeW.value = W
  bridgeH.value = H
  if (!W) return
  const yr = (pane: HTMLElement, r: [number, number]) => {
    const a = pane.querySelector(`.l[data-i="${r[0]}"]`)
    const b = pane.querySelector(`.l[data-i="${r[1]}"]`)
    if (!a || !b) return null
    const pr = pane.getBoundingClientRect()
    const y1 = a.getBoundingClientRect().top - box.top
    const y2 = b.getBoundingClientRect().bottom - box.top
    const lo = pr.top - box.top
    const hi = pr.bottom - box.top
    return { y1: Math.max(lo, Math.min(hi, y1)), y2: Math.max(lo, Math.min(hi, y2)), above: y2 < lo, below: y1 > hi }
  }
  const rs = ranges(linkSrc.value.map((l) => l - 1)).map((r) => yr(cs, r)).filter((x) => !!x)
  const rd = ranges(linkDst.value).map((r) => yr(cd, r)).filter((x) => !!x)
  const m = W / 2
  if (rs.length && rd.length) {
    for (const a of rs) for (const b of rd) bands.value.push(`M0 ${a.y1} C${m} ${a.y1} ${m} ${b.y1} ${W} ${b.y1} L${W} ${b.y2} C${m} ${b.y2} ${m} ${a.y2} 0 ${a.y2} Z`)
    ;[rs, rd].forEach((set, k) => {
      for (const r of set) if (r.above || r.below) offs.value.push({ x: k ? W - 4 : 4, y: r.above ? 12 : H - 4, t: r.above ? '▲' : '▼', anchor: k ? 'end' : 'start' })
    })
  } else if (rs.length) {
    for (const a of rs) stubs.value.push(`M0 ${a.y1} L${W * 0.45} ${(a.y1 + a.y2) / 2} L0 ${a.y2}`)
  } else if (rd.length) {
    for (const b of rd) stubs.value.push(`M${W} ${b.y1} L${W * 0.55} ${(b.y1 + b.y2) / 2} L${W} ${b.y2}`)
  }
}
watch([srcCode, dstCode], () => { void nextTick(drawBridge) })
onMounted(() => window.addEventListener('resize', drawBridge))
onBeforeUnmount(() => window.removeEventListener('resize', drawBridge))

// ---------------------------------------------------------------- 结果概况
const verify = computed(() => result.value?.verify ?? { checked: false })
const verifyItems = computed(() => warns.value.filter(isVerifyItem))
const verifyOpen = ref(true)
const verifyState = computed(() => (!verify.value.checked ? 'off' : (verify.value.unexplained ?? 0) > 0 ? 'diff' : 'ok'))

const outFile = computed(() => {
  const r = result.value
  if (!r) return 'translated.cfg'
  const base = (r.source.device || 'config').replace(/[^\w.-]+/g, '_')
  return `${base}-${r.target.profile}.cfg`
})

// ---------------------------------------------------------------- 复制与下载
const toast = ref('')
/** 全屏时提示放进全屏区域里（REQ-043），否则看不到。 */
const fsMode = ref<FsMode>('')
let toastTimer = 0
function flash(s: string): void {
  toast.value = s
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2200)
}
function copyText(s: string): void {
  const ok = () => flash(t('c.copied'))
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(ok, ok)
  else ok()
}
const srcTextOf = (lines: number[]) => lines.map((l) => srcLines.value[l - 1] ?? '').join('\n')
const plainOut = computed(() => (result.value ? (appendRawOpt.value ? appendRaw(result.value.lines, warns.value, rawHeader) : result.value.lines) : []))
const dlOpen = ref(false)
function doDl(k: string): void {
  const r = result.value
  if (!r) return
  const stamp = ranAt.value
  const base = outFile.value.replace(/\.cfg$/, '')
  if (k === 'cfg') saveText(outFile.value, linesText(plainOut.value), 'text/plain;charset=utf-8')
  else if (k === 'full' && rendered.value) saveText(`${base}-with-defaults.cfg`, rendered.value.text, 'text/plain;charset=utf-8')
  else if (k === 'rep-zh') saveText(`translate-${base}-zh-CN.md`, reportMd(r, warns.value, 'zh-CN', stamp), 'text/markdown;charset=utf-8')
  else if (k === 'rep-en') saveText(`translate-${base}-en.md`, reportMd(r, warns.value, 'en', stamp), 'text/markdown;charset=utf-8')
  else if (k === 'warn') saveText('warnings.csv', toCsv(warnCsvRows(warns.value, (w) => warnDst(w, outIndex(plainOut.value), appliedMap.value), lang.value)))
  else if (k === 'map') saveText('interface-map.csv', toCsv(mapCsvRows(mapRows.value)))
}

onMounted(async () => {
  await loadBase()
  if (deviceId.value === null && mode.value === 'device' && devices.value.length) deviceId.value = devices.value[0].id
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.dev') }}</span><span class="sep">/</span><span>{{ $t('nav.translate') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('translate.title') }}</h1>
          <p class="ph-sub">{{ $t('translate.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" type="button" :disabled="!result" data-testid="tr-download" @click="dlOpen = true"><Icon name="download" small />{{ $t('translate.download') }}</button>
        </div>
      </div>

      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadBase">{{ $t('c.retry') }}</button></div>

      <!-- ===================== 翻译什么 ===================== -->
      <section class="panel setup" aria-label="Translate" data-testid="tr-setup">
        <div class="panel-h">
          <h2>{{ $t('translate.what') }}</h2>
          <div class="seg" role="group">
            <button type="button" :aria-pressed="mode === 'device'" data-testid="tr-mode-device" @click="mode = 'device'">{{ $t('translate.modeDevice') }}</button>
            <button type="button" :aria-pressed="mode === 'paste'" data-testid="tr-mode-paste" @click="mode = 'paste'">{{ $t('translate.modePaste') }}</button>
          </div>
        </div>
        <div class="panel-b">
          <div class="route">
            <div class="end">
              <div class="end-h">
                <span>{{ $t('translate.source') }}</span>
                <VendorBadge v-if="vendorOf(srcProfileId)" :of="vendorOf(srcProfileId)">{{ srcProfileId }}</VendorBadge>
              </div>
              <template v-if="mode === 'device'">
                <div class="end-sel">
                  <select v-model="deviceId" class="select" :aria-label="$t('translate.device')" data-testid="tr-device">
                    <option v-if="!devices.length" :value="null">{{ $t('translate.noDevices') }}</option>
                    <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option>
                  </select>
                  <select v-model="versionId" class="select" :aria-label="$t('translate.version')" data-testid="tr-version">
                    <option :value="null">{{ $t('translate.latest') }}</option>
                    <option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.seq }} · {{ v.source_name }}{{ v.latest ? ` (${$t('translate.latestTag')})` : '' }}</option>
                  </select>
                </div>
                <div class="end-meta">
                  <span v-if="device">Profile <code>{{ device.profile }}</code></span>
                  <span v-if="srcGraph?.text">{{ $t('translate.linesN', { n: splitLines(srcGraph.text).length }) }}</span>
                  <span v-else-if="srcLoading">{{ $t('c.loading') }}</span>
                </div>
              </template>
              <template v-else>
                <textarea v-model="pasteText" class="input mono paste" rows="7" :placeholder="$t('translate.pastePh')" data-testid="tr-paste" />
                <div class="end-sel">
                  <select v-model="pasteProfile" class="select" :aria-label="$t('translate.srcProfile')">
                    <option value="">{{ $t('translate.autoProfile') }}</option>
                    <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
                  </select>
                </div>
                <div class="end-meta"><span>{{ $t('translate.pasteNote') }}</span></div>
              </template>
            </div>
            <div class="arrow"><Icon name="chevR" /></div>
            <div class="end">
              <div class="end-h">
                <span>{{ $t('translate.target') }}</span>
                <VendorBadge v-if="vendorOf(target)" :of="vendorOf(target)">{{ profileOf(target)?.family }}</VendorBadge>
              </div>
              <div class="end-sel one">
                <select v-model="target" class="select" :aria-label="$t('translate.target')" data-testid="tr-target">
                  <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}（{{ p.title }}）</option>
                </select>
              </div>
              <div class="end-meta">
                <span v-if="srcFamily && profileOf(target)?.family === srcFamily">{{ $t('translate.sameFamily') }}</span>
                <span v-else-if="srcFamily">{{ $t('translate.crossFamily', { a: srcFamily, b: profileOf(target)?.family ?? '' }) }}</span>
              </div>
            </div>
          </div>
          <IfMapPanel v-model:rows="mapRows" :loading="srcLoading" :dirty="mapDirty" @reset="resetMap" />
          <div class="opts">
            <span class="fixed-rule" :title="$t('translate.ruleTip')"><Icon name="lock" small /><span>{{ $t('translate.rule') }}</span></span>
            <label class="check"><input v-model="appendRawOpt" type="checkbox" data-testid="tr-append-raw"><span>{{ $t('translate.appendRaw') }}</span></label>
            <RuleSetPicker v-model="ruleSet" testid="tr-rules" />
            <span style="flex: 1" />
            <button class="btn btn-primary" type="button" :disabled="!canRun || running" data-testid="tr-run" @click="run"><Icon name="swap" small />{{ running ? $t('translate.running') : $t('translate.run') }}</button>
          </div>
        </div>
      </section>

      <div v-if="runError" class="notice err mt12" data-testid="tr-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
      <div v-if="!result && !runError && !running" class="empty mt16" data-testid="tr-empty"><Icon name="swap" /><h3>{{ $t('translate.emptyTitle') }}</h3><p>{{ $t('translate.emptyText') }}</p></div>

      <!-- ===================== 结果 ===================== -->
      <template v-if="result">
        <ModelApproxNote :note="result.approx_profile" />
        <div class="res-head">
          <h2>{{ $t('translate.result') }}</h2>
          <span class="meta"><span>{{ result.source.profile }} → {{ result.target.profile }}</span><span>{{ ranAt }}</span><span>{{ ms }} ms</span></span>
        </div>
        <div class="sumbar" data-testid="tr-sumbar">
          <div><span class="n">{{ result.stats.rendered }}<small>/ {{ result.stats.facts }}</small></span><span class="k">{{ $t('translate.written') }}</span></div>
          <button v-for="g in GROUPS" :key="g" type="button" :aria-pressed="filter === g" :style="{ '--c': `var(--bar-${g})` }" :class="`g-${g}`" :data-testid="`tr-sum-${g}`" @click="toggleSum(g)">
            <span class="n">{{ counts[g] }}</span><span class="k"><span class="wk" :class="g">{{ $t(`translate.group.${g}`) }}</span></span>
          </button>
          <div>
            <span class="n" :class="`v-${verifyState}`">{{ verifyState === 'off' ? '—' : verify.equal ? $t('translate.consistent') : $t('translate.diffN', { n: verify.diffs ?? 0 }) }}</span>
            <span class="k">{{ $t('translate.verifyK') }}</span>
          </div>
        </div>

        <div class="verify" :class="verifyState" data-testid="tr-verify">
          <span class="vi"><Icon :name="verifyState === 'ok' ? 'ok' : verifyState === 'diff' ? 'warn' : 'info'" /></span>
          <div>
            <h3>{{ verifyState === 'off' ? $t('translate.verifyOff') : verify.equal ? $t('translate.verifyEqual') : verifyState === 'ok' ? $t('translate.verifyExplained', { n: verify.diffs ?? 0 }) : $t('translate.verifyBad', { n: verify.unexplained ?? 0 }) }}</h3>
            <div v-if="verify.checked" class="vnums">
              <span>{{ $t('translate.vDiffs') }} <b>{{ verify.diffs ?? 0 }}</b></span>
              <span>{{ $t('translate.vExplained') }} <b>{{ Math.max(0, (verify.diffs ?? 0) - verifyItems.filter((w) => w.item.kind === 'verify_diff').length) }}</b></span>
              <span :style="(verify.unexplained ?? 0) ? 'color: var(--amber-ink)' : ''">{{ $t('translate.vUnexplained') }} <b>{{ verify.unexplained ?? 0 }}</b></span>
            </div>
          </div>
          <button v-if="verifyItems.length" class="btn btn-sm" type="button" @click="verifyOpen = !verifyOpen"><Icon :name="verifyOpen ? 'chevD' : 'chevR'" small />{{ verifyOpen ? $t('c.collapse') : $t('translate.showDiffs') }}</button>
          <span v-else-if="verifyState === 'ok'" class="tag pass"><Icon name="check" small />{{ $t('translate.ready') }}</span>
        </div>
        <div v-if="verifyItems.length && verifyOpen" class="vlist" data-testid="tr-vlist">
          <div class="vhead"><span>{{ $t('translate.vNode') }}</span><span>{{ $t('translate.vSrc') }}</span><span /><span>{{ $t('translate.vOut') }}</span><span>{{ $t('translate.vWhy') }}</span></div>
          <div v-for="w in verifyItems" :key="w.id" class="vrow" :class="{ 'is-sel': sel === w.id }" @click="selectWarn(w.id, true)">
            <div><div class="p">{{ String(w.item.params.cid ?? w.item.params.line ?? w.item.node ?? '') }}</div><div v-if="w.item.node" class="o"><TermName :id="w.item.node" /></div></div>
            <div class="v">{{ String(w.item.params.src_value ?? '') }}</div>
            <div class="faint">→</div>
            <div class="v">{{ String(w.item.params.dst_value ?? w.item.params.text ?? '') }}</div>
            <div class="why">{{ warnText(w, lang) }}</div>
          </div>
        </div>

        <NamingReportPanel v-if="result.naming" :report="result.naming" class="mt12" testid="tr-naming" />

        <FullscreenPane class="tr-fs" :title="`${result.source.profile} → ${result.target.profile}`" data-testid="tr-fs" @change="(m) => (fsMode = m)">
        <div class="rbar">
          <ShowDefaultToggle v-model="showDefault" testid="tr-show-default" />
          <span v-if="showDefault && renderLoading" class="small faint">{{ $t('c.loading') }}</span>
          <span v-if="showDefault && renderError" class="small" style="color: var(--red-ink)">{{ renderError }}</span>
          <HiddenLegend :derived="false" />
          <span class="legend-m3"><span class="faint">|</span><span class="wk default">{{ $t('translate.lgDefault') }}</span><span class="wk unsup">{{ $t('translate.lgUnsup') }}</span><span class="wk raw">{{ $t('translate.lgRaw') }}</span><span class="wk infer">{{ $t('translate.lgInfer') }}</span><span v-if="result.naming?.summary.renamed" class="wk rename" data-testid="tr-rename-legend">{{ $t('translate-rules.report') }}</span></span>
          <span class="ml-auto small faint">{{ $t('translate.linkHint') }}</span>
          <FullscreenButton />
        </div>
        <div class="tw">
          <section class="panel pane src" aria-label="Source">
            <div class="tbar">
              <span class="side-b">{{ $t('translate.sideS') }}</span>
              <VendorBadge :of="vendorOf(result.source.profile) || result.source.profile">{{ result.source.profile }}</VendorBadge>
              <span class="fn">{{ result.source.device }}</span>
            </div>
            <M3Code ref="srcPane" :lines="srcCode" side="s" testid="tr-src" @pick="pickSrc" @scroll="drawBridge" />
          </section>
          <div class="bridge" aria-hidden="true">
            <svg ref="bridgeSvg">
              <line class="rail" :x1="bridgeW / 2" y1="0" :x2="bridgeW / 2" :y2="bridgeH" />
              <path v-for="(d, i) in bands" :key="'b' + i" class="band" :class="{ 'k-unsup': selKind === 'unsup' }" :d="d" />
              <path v-for="(d, i) in stubs" :key="'s' + i" class="stub" :d="d" />
              <text v-for="(o, i) in offs" :key="'o' + i" class="off" :x="o.x" :y="o.y" :text-anchor="o.anchor">{{ o.t }}</text>
            </svg>
          </div>
          <section class="panel pane dst" aria-label="Output">
            <div class="tbar">
              <span class="side-b">{{ $t('translate.sideT') }}</span>
              <VendorBadge :of="vendorOf(result.target.profile) || result.target.profile">{{ result.target.profile }}</VendorBadge>
              <span class="fn">{{ outFile }}</span>
              <span class="ml-auto" />
              <button class="btn btn-ghost btn-xs" type="button" data-testid="tr-copy" @click="copyText(linesText(plainOut))"><Icon name="copy" small />{{ $t('c.copy') }}</button>
            </div>
            <M3Code ref="dstPane" :lines="dstCode" side="d" testid="tr-out" @pick="pickDst" @scroll="drawBridge" />
          </section>
          <WarnPanel
            :warns="warns" :filter="filter" :sel="sel" :handled="handled" :dst-of="dstOf" :src-text="srcTextOf"
            @filter="setFilter" @select="(id) => selectWarn(id)" @go="go" @handle="(id, v) => (handled = { ...handled, [id]: v })" @copy="copyText"
          />
        </div>
        <div v-if="toast && fsMode" class="toast" role="status">{{ toast }}</div>
        </FullscreenPane>
        <TranslateGapPanel
          v-if="mode === 'device' && deviceId !== null"
          :device-id="deviceId" :to="result.target.profile" :rule-set="ruleSet" :interface-map="ifMap"
          :unsupported="result.unsupported" :ai-lines="result.ai_lines" :out-text="result.text" :src-text="srcText"
          @changed="run"
        />
      </template>
    </div>
    <div v-if="toast && !fsMode" class="toast" role="status">{{ toast }}</div>
    <DownloadDialog v-if="dlOpen && result" :file="outFile" :has-defaults="!!rendered" :has-map="mapRows.length > 0" @close="dlOpen = false" @dl="doDl" />
  </main>
</template>

<style scoped>
.setup .panel-b { display: flex; flex-direction: column; gap: 12px; }
.route { display: grid; grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1fr); gap: 10px; align-items: stretch; }
.end { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: var(--surface-2); display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.end-h { display: flex; align-items: center; gap: 8px; font-weight: 600; flex-wrap: wrap; }
.end-sel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.end-sel.one { grid-template-columns: minmax(0, 1fr); }
.end-meta { display: flex; gap: 6px 12px; flex-wrap: wrap; font-size: 12px; color: var(--ink-3); }
.paste { width: 100%; resize: vertical; min-height: 120px; font-size: 12px; }
.route .arrow { display: flex; align-items: center; justify-content: center; color: var(--ink-3); }
.opts { display: flex; gap: 8px 18px; align-items: center; flex-wrap: wrap; }
.fixed-rule { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); border: 1px dashed var(--line-strong); border-radius: 4px; padding: 2px 8px; cursor: help; }
.fixed-rule :deep(.ico) { color: var(--teal-ink); }

.res-head { display: flex; align-items: center; gap: 12px; margin: 18px 0 10px; flex-wrap: wrap; }
.res-head h2 { font-size: 15px; }
.res-head .meta { color: var(--ink-3); font-size: 12px; display: flex; gap: 12px; flex-wrap: wrap; }
.sumbar { --bar-default: #D9962B; --bar-unsup: var(--red); --bar-raw: var(--raw); --bar-infer: var(--blue); display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)) minmax(0, 1.4fr); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; }
.sumbar > button, .sumbar > div { all: unset; box-sizing: border-box; padding: 10px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 3px; min-width: 0; position: relative; }
.sumbar > :first-child { border-left: 0; }
.sumbar > button { cursor: pointer; }
.sumbar > button:hover { background: var(--surface-2); }
.sumbar > button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.sumbar > button[aria-pressed="true"] { background: var(--surface-3); }
.sumbar > button[aria-pressed="true"]::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--c, var(--ink-3)); }
.sumbar .n { font: 600 22px/1.2 var(--font-display); }
.sumbar .n small { font: 400 12px var(--font-ui); color: var(--ink-3); margin-left: 6px; }
.sumbar .n.v-ok { color: var(--teal-ink); }
.sumbar .n.v-diff { color: var(--amber-ink); }
.sumbar .k { font-size: 12px; color: var(--ink-2); display: flex; gap: 6px; align-items: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.verify { margin-top: 10px; }
.vlist { margin-top: 8px; border: 1px solid var(--amber-line); border-radius: 6px; background: var(--surface); overflow: hidden; }
.vrow, .vhead { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, .7fr) 16px minmax(0, .8fr) minmax(0, 1.6fr); gap: 12px; padding: 9px 12px; align-items: start; }
.vrow { border-top: 1px solid var(--line); cursor: pointer; }
.vrow:hover { background: var(--surface-2); }
.vrow.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.vrow .p { font: 12px var(--font-mono); overflow-wrap: anywhere; }
.vrow .o { font-size: 11.5px; color: var(--ink-3); }
.vrow .v { font: 12px var(--font-mono); overflow-wrap: anywhere; }
.vrow .why { font-size: 12px; color: var(--ink-2); }
.vhead { padding: 6px 12px; font-size: 11.5px; font-weight: 600; color: var(--ink-2); background: var(--surface-2); border-bottom: 1px solid var(--line); }

.rbar { display: flex; align-items: center; gap: 10px; margin: 12px 0 8px; flex-wrap: wrap; }
.legend-m3 { display: flex; gap: 6px 10px; flex-wrap: wrap; align-items: center; font-size: 12px; color: var(--ink-2); }
.wk.rename { color: var(--teal-ink); background: var(--teal-soft); border-color: var(--teal-line); }
.wk.rename::before { content: "R"; }
.pane :deep(.code .l.w-rename .n) { box-shadow: inset 3px 0 0 var(--teal); color: var(--teal-ink); }
.mt12 { margin-top: 12px; }

.tw { display: grid; grid-template-columns: minmax(0, 1fr) 46px minmax(0, 1fr) 380px; gap: 0 10px; height: min(70vh, 760px); min-height: 460px; }
.tr-fs.is-fs .rbar { margin: 0; }
.tr-fs.is-fs .tw { flex: 1; height: auto; min-height: 0; }
.tw .pane { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.pane .tbar { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 1px solid var(--line); font-size: 12px; white-space: nowrap; overflow: hidden; }
.pane .tbar .side-b { width: 20px; height: 20px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); border: 1.5px solid var(--line-strong); flex: none; }
.pane .tbar .fn { font: 11.5px var(--font-mono); color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; }
.pane :deep(.code) { flex: 1; min-height: 0; }
.pane :deep(.code .l) { cursor: pointer; }
.pane :deep(.code .l:hover:not(.linked)) { background: color-mix(in srgb, var(--blue-soft) 60%, transparent); }
.bridge { position: relative; }
.bridge svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.bridge .band { fill: color-mix(in srgb, var(--amber) 22%, transparent); stroke: var(--hl-line-edge); stroke-width: 1; }
.bridge .band.k-unsup { fill: color-mix(in srgb, var(--red) 14%, transparent); stroke: var(--red); }
.bridge .stub { fill: none; stroke: var(--line-strong); stroke-width: 1.2; stroke-dasharray: 3 3; }
.bridge .off { font: 600 10px var(--font-ui); fill: var(--ink-3); }
.bridge .rail { stroke: var(--line); stroke-width: 1; }

.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--surface); padding: 8px 14px; border-radius: 6px; font-size: 12.5px; z-index: 60; box-shadow: var(--shadow-pop); }

@media (max-width: 1360px) {
  .tw { grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr); height: auto; min-height: 0; grid-template-rows: min(64vh, 680px) auto; }
  .tw > :deep(.warns) { grid-column: 1 / -1; margin-top: 10px; max-height: 560px; }
}
@media (max-width: 900px) {
  .route { grid-template-columns: minmax(0, 1fr); }
  .route .arrow { transform: rotate(90deg); height: 28px; }
  .sumbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tw { grid-template-columns: minmax(0, 1fr); grid-template-rows: 420px 0 420px auto; }
  .tw .bridge { display: none; }
  .vrow, .vhead { grid-template-columns: minmax(0, 1fr); }
  .vhead { display: none; }
}
</style>
