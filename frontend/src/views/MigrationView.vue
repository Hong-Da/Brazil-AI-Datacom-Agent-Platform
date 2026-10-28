<script setup lang="ts">
/**
 * 割接迁移（预览 DevelopDocs/ui-preview/M4/migration.html）：旧设备（设备 + 版本或粘贴）→ 目标平台 / 目标设备现有配置 →
 * POST /migrate → 五步：翻译告警（与旧配置行联动）、接口映射表（建议 + 依据 + 置信度，可改写、导入导出 CSV，改后重新生成）、
 * 新设备配置（完整 / 增量 / 增量下发脚本 / 回滚）、割接步骤（执行与回退）、验证与割接包导出（与 CLI 输出目录相同的文件）。
 */
import VendorBadge from '@/components/vendor-badge.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import RuleSetPicker from '@/components/rule-set-picker.vue'
import NamingReportPanel from './translate-rules/NamingReportPanel.vue'
import M3Code from '@/components/m3-code.vue'
import { errorText, get, post } from '@/api'
import { useTerms } from '@/stores/terms'
import { saveText, toCsv } from '@/views/profiles/csv'
import { saveBytes, zipBytes } from '@/views/m3/zip'
import type { CodeLine } from '@/views/m3/code'
import type { Device } from '@/views/devices/logic'
import type { VersionInfo } from '@/views/compare/types'
import { msg } from './m4/texts'
import CutoverPlanPanel from './ai-change/CutoverPlanPanel.vue'
import { lines as splitLines, safeName } from './m4/common'
import {
  allItems, groupCount, mapCsvRows, mapFromCsv, overrides, packageFiles, railStates, rowState, rowTarget, splitSteps,
  stepRisk, stepsText, verifyOk, warnGroup, type Item, type MapRow, type MigrateResult, type Step, type WarnGroup,
} from './m4/migration'

interface ProfileLite { id: string; title: string; vendor: string; family: string }

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()

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
const profileOf = (id: string | null | undefined) => profiles.value.find((p) => p.id === id) ?? null

// ---------------------------------------------------------------- 旧设备与目标
const num = (v: unknown) => (typeof v === 'string' && /^\d+$/.test(v) ? Number(v) : null)
const deviceId = ref<number | null>(num(route.query.device))
const versionId = ref<number | null>(num(route.query.version))
const target = ref(String(route.query.to ?? ''))
const model = ref('')
const exMode = ref<'none' | 'device' | 'paste'>('none')
const exDevice = ref<number | null>(null)
const exText = ref('')
const onConflict = ref<'migrate' | 'keep'>('migrate')
const ruleSet = ref<string>(String(route.query.rules ?? '')) // 翻译规则集（REQ-032）
const device = computed(() => devices.value.find((d) => d.id === deviceId.value) ?? null)
const srcFamily = computed(() => profileOf(device.value?.profile)?.family ?? '')

watch(deviceId, async (id) => {
  versions.value = []
  if (id === null) return
  try { versions.value = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions } catch { /* 用最新版本 */ }
  if (versionId.value !== null && !versions.value.some((v) => v.id === versionId.value)) versionId.value = null
})
watch([srcFamily, profiles], () => {
  if (target.value && profileOf(target.value)) return
  const other = profiles.value.find((p) => srcFamily.value && p.family !== srcFamily.value)
  if (other) target.value = other.id
})
const canRun = computed(() => deviceId.value !== null && !!target.value && (exMode.value !== 'device' || exDevice.value !== null) && (exMode.value !== 'paste' || !!exText.value.trim()))

// ---------------------------------------------------------------- 生成
const running = ref(false)
const runError = ref('')
const result = ref<MigrateResult | null>(null)
/** 最近一次割接迁移的输入（M8-4 割接方案文档用同一组输入，结果由代码重新计算） */
const aiBody = ref<Record<string, unknown> | null>(null)
const srcLines = ref<string[]>([])
const rows = ref<MapRow[]>([])
/** 已经交给后端的映射（再次生成时保留） */
const sentMap = ref<Record<string, string>>({})
const step = ref(0)

async function targetText(): Promise<string | null> {
  if (exMode.value === 'paste') return exText.value
  if (exMode.value === 'device' && exDevice.value !== null) {
    const d = devices.value.find((x) => x.id === exDevice.value)
    if (d?.latest_version_id) return (await get<{ text: string }>(`/devices/${d.id}/versions/${d.latest_version_id}/text`)).text
  }
  return null
}
async function run(map: Record<string, string> = sentMap.value): Promise<void> {
  if (!canRun.value || running.value) return
  running.value = true
  runError.value = ''
  try {
    const body: Record<string, unknown> = { device_id: deviceId.value, to: target.value, on_conflict: onConflict.value, interface_map: Object.keys(map).length ? map : null }
    if (versionId.value !== null) body.version_id = versionId.value
    if (model.value.trim()) body.model = model.value.trim()
    if (ruleSet.value) body.rule_set = ruleSet.value
    const tt = await targetText()
    if (tt) body.target_text = tt
    const vid = versionId.value ?? device.value?.latest_version_id
    const [r, src] = await Promise.all([
      post<MigrateResult>('/migrate', body),
      vid ? get<{ text: string }>(`/devices/${deviceId.value}/versions/${vid}/text`).catch(() => ({ text: '' })) : Promise.resolve({ text: '' }),
    ])
    result.value = r
    aiBody.value = { ...body, target_text: undefined, target_device_id: exMode.value === 'device' ? exDevice.value : null }
    srcLines.value = splitLines(src.text)
    rows.value = r.interface_map.map((item) => ({ item, edited: null }))
    sentMap.value = map
    sel.value = null
    const q: Record<string, string> = { device: String(deviceId.value), to: target.value }
    if (versionId.value !== null) q.version = String(versionId.value)
    if (ruleSet.value) q.rules = ruleSet.value
    void router.replace({ query: q })
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}
const dirty = computed(() => rows.value.some((r) => r.edited !== null && r.edited !== (r.item.target ?? '')))
function regenerate(): void {
  void run(overrides(rows.value, sentMap.value))
}

// ---------------------------------------------------------------- 1 翻译
const items = computed<Item[]>(() => (result.value ? allItems(result.value) : []))
const counts = computed(() => groupCount(items.value))
const GROUPS: WarnGroup[] = ['map', 'default', 'unsup', 'raw', 'verify']
const filter = ref<WarnGroup | ''>('')
const sel = ref<number | null>(null)
const shownItems = computed(() => items.value.map((it, i) => ({ it, i, g: warnGroup(it) })).filter((x) => !filter.value || x.g === filter.value))
const itemText = (it: Item) => msg(it.key, { ...it.params, node: it.node ? terms.describe(it.node) : it.params.node }, lang.value)
const WCLS: Record<WarnGroup, string> = { map: 'w-default', default: 'w-default', unsup: 'w-unsup', raw: 'w-raw', verify: 'w-unsup' }
const srcCode = computed<CodeLine[]>(() => {
  const mark = new Map<number, string>()
  items.value.forEach((it) => { for (const l of it.lines) if (!mark.has(l)) mark.set(l, WCLS[warnGroup(it)]) })
  const hl = new Set(sel.value !== null ? items.value[sel.value]?.lines ?? [] : [])
  return srcLines.value.map((text, k) => ({ no: k + 1, text, cls: [mark.get(k + 1) ?? '', hl.has(k + 1) ? 'is-hl' : ''].join(' ') }))
})
const srcPane = ref<InstanceType<typeof M3Code>>()
function pickItem(i: number): void {
  sel.value = sel.value === i ? null : i
  const l = sel.value !== null ? items.value[i].lines[0] : undefined
  if (l) srcPane.value?.scrollToIndex(l - 1)
}
function pickSrcLine(k: number): void {
  const i = items.value.findIndex((it) => it.lines.includes(k + 1))
  sel.value = i >= 0 ? i : null
}

// ---------------------------------------------------------------- 2 映射
const newNames = computed(() => [...new Set(rows.value.map((r) => r.item.target).filter((x): x is string => !!x))].sort())
const fileInput = ref<HTMLInputElement>()
const toast = ref('')
let toastTimer = 0
function flash(s: string): void {
  toast.value = s
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2600)
}
async function importCsv(ev: Event): Promise<void> {
  const f = (ev.target as HTMLInputElement).files?.[0]
  ;(ev.target as HTMLInputElement).value = ''
  if (!f) return
  const m = mapFromCsv(await f.text())
  if (!m) { flash(t('migration.csvBad')); return }
  let n = 0
  for (const r of rows.value) if (r.item.source in m) { r.edited = m[r.item.source] === '-' ? '' : m[r.item.source]; n++ }
  // 表中没有的旧接口（之前未映射的）也一并带上
  sentMap.value = { ...sentMap.value, ...Object.fromEntries(Object.entries(m).filter(([k]) => !rows.value.some((r) => r.item.source === k))) }
  flash(t('migration.csvApplied', { n }))
}
const csvText = computed(() => (result.value ? toCsv(mapCsvRows(result.value.interface_map, result.value.unmapped)) : ''))
const base = computed(() => `${safeName(result.value?.source.device)}-to-${result.value?.target.profile ?? 'target'}`)
const confPct = (c: number) => `${Math.round(c * 100)}%`
const speed = (s: number | null) => (s ? `${s}G` : '—')

// ---------------------------------------------------------------- 3 配置
const cfgTab = ref<'full' | 'delta' | 'script' | 'rollback'>('full')
const cfgText = computed(() => {
  const r = result.value
  if (!r) return ''
  return cfgTab.value === 'full' ? r.text : cfgTab.value === 'delta' ? r.delta : cfgTab.value === 'script' ? r.script.script ?? '' : r.script.rollback ?? ''
})
const mappedNew = computed(() => new Set(rows.value.map((r) => r.item.target).filter(Boolean)))
const cfgCode = computed<CodeLine[]>(() => splitLines(cfgText.value).map((text, k) => {
  const m = /^\s*interface\s+(\S+)/.exec(text)
  return { no: k + 1, text, cls: m && mappedNew.value.has(m[1]) ? 'is-mapped' : /^\s*[#!]\s*\[\d+\]/.test(text) ? 'c-cmt' : '' }
}))
const cfgFile = computed(() => ({ full: 'new-config.cfg', delta: 'delta.cfg', script: 'script.txt', rollback: 'rollback.txt' })[cfgTab.value])

// ---------------------------------------------------------------- 4 步骤
const steps = computed(() => splitSteps(result.value?.steps ?? []))
const stepText = (s: Step) => msg(s.key, s.params, lang.value)
const devLabel = (d: string) => t(`migration.dev.${d}`)
const devName = (s: Step) => (s.device === 'old' ? result.value?.source.device ?? '' : s.device === 'new' ? result.value?.target.profile ?? '' : '')
const stepsTxt = computed(() => stepsText(result.value?.steps ?? [], stepText, devLabel))

// ---------------------------------------------------------------- 5 验证与导出
const verifyItems = computed(() => items.value.filter((it) => warnGroup(it) === 'verify'))
const ok = computed(() => (result.value ? verifyOk(result.value) : false))
const warnCsv = computed(() => toCsv([
  ['category', 'level', 'kind', 'node', 'lines', 'message'],
  ...(result.value
    ? ([['warning', result.value.warnings], ['unsupported', result.value.unsupported], ['default', result.value.defaults]] as [string, Item[]][]).flatMap(([cat, list]) =>
        list.map((it) => [cat, String(it.params.level ?? ''), it.kind, it.node ?? '', it.lines.join(' '), itemText(it)]))
    : []),
]))
const files = computed(() => (result.value ? packageFiles(result.value, csvText.value, warnCsv.value, stepsTxt.value) : []))
function exportZip(): void {
  saveBytes(`migration-${base.value}.zip`, zipBytes(files.value))
}
const rails = computed(() => (result.value ? railStates(result.value, rows.value, dirty.value) : []))
const railSub = (i: number) => {
  const r = result.value!
  if (i === 0) return t('migration.st.tr', { n: items.value.length })
  if (i === 1) return t('migration.st.map', { m: r.stats.mapped, p: rows.value.filter((x) => rowState(x) === 'low').length + r.unmapped.length })
  if (i === 2) return dirty.value ? t('migration.st.dirty') : t('migration.st.cfg', { n: r.stats.lines })
  if (i === 3) return t('migration.st.cut', { n: steps.value.run.length, r: steps.value.rollback.length })
  return !r.verify.checked ? t('migration.verOff') : ok.value ? t('migration.st.verOk') : t('migration.st.verBad', { n: r.verify.unexplained ?? 0 }, r.verify.unexplained ?? 0)
}
const STEPS = ['tr', 'map', 'cfg', 'cut', 'ver']

function copyText(s: string): void {
  const done = () => flash(t('c.copied'))
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(done, done)
  else done()
}

onMounted(async () => {
  await loadBase()
  if (deviceId.value === null && devices.value.length) deviceId.value = devices.value[0].id
  if (route.query.run === '1' && canRun.value) void run()
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.chg') }}</span><span class="sep">/</span><span>{{ $t('nav.migration') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('migration.title') }}</h1>
          <p class="ph-sub">{{ $t('migration.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button v-if="result && dirty" class="btn btn-primary" type="button" :disabled="running" data-testid="mig-regen" @click="regenerate"><Icon name="refresh" small />{{ $t('migration.regen') }}</button>
        </div>
      </div>
      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadBase">{{ $t('c.retry') }}</button></div>

      <section class="panel" data-testid="mig-setup">
        <div class="panel-b setup">
          <div class="route">
            <div class="end">
              <div class="end-h"><Icon name="server" small /><span>{{ $t('migration.old') }}</span><span class="k">{{ $t('migration.oldK') }}</span></div>
              <div class="end-sel">
                <select v-model="deviceId" class="select" data-testid="mig-device">
                  <option v-if="!devices.length" :value="null">{{ $t('migration.noDevices') }}</option>
                  <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option>
                </select>
                <select v-model="versionId" class="select">
                  <option :value="null">{{ $t('migration.latest') }}</option>
                  <option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.seq }} · {{ v.source_name }}</option>
                </select>
              </div>
              <div class="end-meta"><DevChip v-if="device" :name="device.name" :vendor="device.vendor" /><span v-if="device">{{ device.profile }}</span><span>{{ srcFamily }}</span></div>
            </div>
            <div class="arrow"><Icon name="swap2" /></div>
            <div class="end">
              <div class="end-h"><Icon name="cpu" small /><span>{{ $t('migration.new') }}</span><span class="k">{{ $t('migration.newK') }}</span></div>
              <div class="end-sel">
                <select v-model="target" class="select" :aria-label="$t('migration.targetProfile')" data-testid="mig-target">
                  <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}（{{ p.title }}）</option>
                </select>
                <input v-model="model" class="input mono" :placeholder="$t('migration.model')" :title="$t('migration.model')">
              </div>
              <div class="end-meta"><VendorBadge v-if="profileOf(target)" :of="profileOf(target)!.vendor">{{ profileOf(target)!.family }}</VendorBadge><span>{{ $t('migration.targetProfile') }}</span></div>
            </div>
            <div class="end opts">
              <div class="end-h"><Icon name="sliders" small /><span>{{ $t('migration.existing') }}</span></div>
              <div class="seg" role="group">
                <button v-for="m in (['none', 'device', 'paste'] as const)" :key="m" type="button" :aria-pressed="exMode === m" @click="exMode = m">{{ $t(`migration.ex.${m}`) }}</button>
              </div>
              <select v-if="exMode === 'device'" v-model="exDevice" class="select">
                <option v-for="d in devices.filter((x) => profileOf(x.profile)?.family === profileOf(target)?.family)" :key="d.id" :value="d.id">{{ d.name }}</option>
              </select>
              <textarea v-if="exMode === 'paste'" v-model="exText" class="input mono paste" rows="3" :placeholder="$t('migration.exPastePh')" />
              <label v-if="exMode !== 'none'" class="check small"><span>{{ $t('migration.onConflict') }}</span>
                <select v-model="onConflict" class="select" style="width: auto; height: 26px"><option value="migrate">{{ $t('migration.oc.migrate') }}</option><option value="keep">{{ $t('migration.oc.keep') }}</option></select>
              </label>
            </div>
          </div>
          <div class="opts"><RuleSetPicker v-model="ruleSet" testid="mig-rules" /><span v-if="ruleSet" class="small faint">{{ $t('translate-rules.migNote') }}</span><span class="ml-auto" /><button class="btn btn-primary btn-sm" type="button" :disabled="!canRun || running" data-testid="mig-run" @click="run({})"><Icon name="play" small />{{ running ? $t('migration.running') : $t('migration.run') }}</button></div>
        </div>
      </section>

      <div v-if="runError" class="notice err mt12" data-testid="mig-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run()">{{ $t('c.retry') }}</button></div>
      <div v-if="!result && !runError" class="empty mt16"><Icon name="swap2" /><h3>{{ running ? $t('c.loading') : $t('migration.emptyTitle') }}</h3><p v-if="!running">{{ $t('migration.emptyText') }}</p></div>

      <template v-if="result">
        <nav class="mrail" aria-label="Steps" data-testid="mig-rail">
          <button v-for="(s, i) in STEPS" :key="s" type="button" :class="`s-${rails[i]}`" :aria-current="step === i ? 'step' : undefined" :data-testid="`mig-step-${s}`" @click="step = i">
            <span class="no"><Icon v-if="rails[i] === 'done'" name="check" small /><template v-else>{{ i + 1 }}</template></span>
            <span class="tt">{{ i + 1 }}. {{ $t(`migration.step.${s}`) }}</span><span class="st">{{ railSub(i) }}</span>
          </button>
        </nav>
        <div v-if="dirty" class="notice warn" style="margin-bottom: 10px"><Icon name="warn" /><div class="grow">{{ $t('migration.dirty') }}</div><button class="btn btn-sm btn-primary" type="button" @click="regenerate">{{ $t('migration.regen') }}</button></div>

        <NamingReportPanel v-if="result.naming && step === 0" :report="result.naming" style="margin-bottom: 12px" testid="mig-naming" />
        <!-- 1 翻译 -->
        <section v-if="step === 0" data-testid="mig-tr">
          <div class="step-h"><h2>{{ $t('migration.trTitle', { p: result.target.profile }) }}</h2><span class="meta">{{ result.source.profile }} → {{ result.target.profile }}</span>
            <span class="ml-auto"><router-link class="btn btn-sm" :to="{ name: 'translate', query: { device: String(deviceId), to: result.target.profile } }"><Icon name="swap" small />{{ $t('migration.openTranslate') }}</router-link></span></div>
          <div class="sumbar">
            <div><span class="n">{{ result.stats.translate.rendered ?? 0 }}<small>/ {{ result.stats.translate.facts ?? 0 }}</small></span><span class="k">{{ $t('migration.written') }}</span></div>
            <button v-for="g in GROUPS" :key="g" type="button" :aria-pressed="filter === g" :data-testid="`mig-g-${g}`" @click="filter = filter === g ? '' : g"><span class="n">{{ counts[g] }}</span><span class="k">{{ $t(`migration.g.${g}`) }}</span></button>
          </div>
          <div class="tw">
            <div class="panel pane"><div class="tbar"><DevChip :name="result.source.device ?? ''" :vendor="result.source.family" /><span class="fn">{{ $t('migration.srcPane') }}</span></div>
              <M3Code ref="srcPane" :lines="srcCode" side="s" testid="mig-src" @pick="pickSrcLine" /></div>
            <div class="panel pane"><div class="tbar"><VendorBadge :of="result.target.family">{{ result.target.profile }}</VendorBadge><span class="fn">{{ $t('migration.dstPane') }}</span></div>
              <M3Code :lines="splitLines(result.text).map((text, k) => ({ no: k + 1, text }))" side="d" testid="mig-dst" /></div>
            <div class="panel warns"><div class="wlist" data-testid="mig-warns">
              <p v-if="!shownItems.length" class="small muted" style="padding: 12px">{{ $t('migration.noWarns') }}</p>
              <div v-for="x in shownItems" :key="x.i" class="wi" :class="[`k-${x.g}`, { 'is-sel': sel === x.i }]" data-testid="mig-warn" @click="pickItem(x.i)">
                <div class="wh"><span class="wid">{{ $t(`migration.g.${x.g}`) }}</span><span v-if="x.it.lines.length" class="mono small faint">L{{ x.it.lines.join(', ') }}</span></div>
                <div class="wt">{{ itemText(x.it) }}</div>
                <div v-if="x.it.node" class="wd mono small">{{ terms.describe(x.it.node) }}</div>
              </div>
            </div></div>
          </div>
        </section>

        <!-- 2 映射 -->
        <section v-if="step === 1" data-testid="mig-map">
          <div class="step-h"><h2>{{ $t('migration.mapTitle') }}</h2>
            <span class="meta">{{ $t('migration.mapMeta', { m: result.stats.mapped, u: result.unmapped.length, inv: $t(`migration.inv.${result.inventory.source}`, { model: result.inventory.model ?? '' }) }) }}</span>
            <span class="ml-auto">
              <button class="btn btn-sm" type="button" @click="fileInput?.click()"><Icon name="upload" small />{{ $t('migration.importCsv') }}</button>
              <input ref="fileInput" type="file" accept=".csv,text/csv" hidden @change="importCsv">
              <button class="btn btn-sm" type="button" data-testid="mig-map-csv" @click="saveText(`interface-map-${base}.csv`, csvText)"><Icon name="download" small />{{ $t('migration.exportCsv') }}</button>
            </span>
          </div>
          <section class="panel map">
            <div class="tbl-wrap">
              <table class="tbl">
                <thead><tr><th>{{ $t('migration.col.old') }}</th><th class="arrowc" /><th>{{ $t('migration.col.new') }}</th><th>{{ $t('migration.col.kind') }}</th><th>{{ $t('migration.col.speed') }}</th><th>{{ $t('migration.col.basis') }}</th><th>{{ $t('migration.col.conf') }}</th><th>{{ $t('migration.col.state') }}</th></tr></thead>
                <tbody>
                  <tr v-for="r in rows" :key="r.item.source" :class="{ pending: rowState(r) === 'low', skip: rowState(r) === 'skip' }" data-testid="mig-map-row">
                    <td class="mono">{{ r.item.source }}<div v-if="r.item.subinterfaces.length" class="small faint">+ {{ r.item.subinterfaces.length }} {{ $t('migration.col.subs') }}</div></td>
                    <td class="arrowc">→</td>
                    <td>
                      <input class="input mono newif" :value="rowTarget(r)" :placeholder="$t('migration.newPh')" list="mig-newnames" data-testid="mig-map-input" @change="r.edited = ($event.target as HTMLInputElement).value.trim()">
                      <button v-if="r.edited !== null" class="link-btn small" type="button" @click="r.edited = null">{{ $t('migration.reset') }}</button>
                    </td>
                    <td class="small">{{ r.item.kind }}</td>
                    <td class="small mono">{{ speed(r.item.source_speed) }} → {{ speed(r.item.target_speed) }}</td>
                    <td class="why">{{ msg(`migrate.basis.${r.item.basis}`, {}, lang) }}</td>
                    <td><span class="conf"><i :style="{ width: confPct(r.item.confidence) }" :class="{ lo: r.item.confidence < 0.5 }" /></span><span class="small mono">{{ confPct(r.item.confidence) }}</span></td>
                    <td><span class="ls" :class="{ ok: 'ok', manual: 'ok', low: 'warn', skip: 'na' }[rowState(r)]">{{ $t(`migration.rs.${rowState(r)}`) }}</span></td>
                  </tr>
                </tbody>
              </table>
              <datalist id="mig-newnames"><option v-for="n in newNames" :key="n" :value="n" /><option value="-" /></datalist>
            </div>
            <div v-if="result.unmapped.length" class="unm">
              <div class="sec-k">{{ $t('migration.unmapped') }}</div>
              <div v-for="u in result.unmapped" :key="u.source ?? u.name" class="small"><code>{{ u.source ?? u.name }}</code> — {{ $t(`migration.reason.${u.reason}`) }}</div>
            </div>
            <div class="map-f"><Icon name="info" small /><span>{{ $t('migration.mapNote') }}</span></div>
          </section>
        </section>

        <!-- 3 配置 -->
        <section v-if="step === 2" data-testid="mig-cfg">
          <div class="step-h"><h2>{{ $t('migration.cfgTitle') }}</h2><span class="meta">{{ result.target.profile }} · {{ result.stats.lines }} / {{ result.stats.delta_lines }}</span>
            <span class="ml-auto">
              <button class="btn btn-sm" type="button" @click="copyText(cfgText)"><Icon name="copy" small />{{ $t('migration.copy') }}</button>
              <button class="btn btn-sm btn-primary" type="button" data-testid="mig-cfg-dl" @click="saveText(cfgFile, cfgText, 'text/plain;charset=utf-8')"><Icon name="download" small />{{ cfgFile }}</button>
            </span></div>
          <div class="seg" role="group" style="margin-bottom: 10px">
            <button type="button" :aria-pressed="cfgTab === 'full'" @click="cfgTab = 'full'">{{ $t('migration.cfgFull') }}</button>
            <button v-if="result.target.existing" type="button" :aria-pressed="cfgTab === 'delta'" @click="cfgTab = 'delta'">{{ $t('migration.cfgDelta') }}</button>
            <button type="button" :aria-pressed="cfgTab === 'script'" :disabled="!result.script.available" @click="cfgTab = 'script'">{{ $t('migration.cfgScript') }}</button>
            <button type="button" :aria-pressed="cfgTab === 'rollback'" :disabled="!result.script.available" @click="cfgTab = 'rollback'">{{ $t('migration.cfgRollback') }}</button>
          </div>
          <div v-if="result.merge" class="notice info" style="margin-bottom: 10px"><Icon name="info" /><div class="grow">{{ $t('migration.merge', result.merge) }}</div></div>
          <div v-if="!result.script.available" class="notice warn" style="margin-bottom: 10px"><Icon name="warn" /><div class="grow">{{ $t('migration.scriptOff', { r: result.script.reason ?? '' }) }}</div></div>
          <div v-else-if="result.script.verify?.ok && (cfgTab === 'script' || cfgTab === 'rollback')" class="notice ok" style="margin-bottom: 10px"><Icon name="ok" /><div class="grow">{{ $t('migration.scriptVerifyOk') }}</div></div>
          <section class="panel"><M3Code :lines="cfgCode" testid="mig-cfg-code" class="cfgcode" /></section>
        </section>

        <!-- 4 步骤 -->
        <section v-if="step === 3" data-testid="mig-cut">
          <div class="step-h"><h2>{{ $t('migration.cutTitle') }}</h2>
            <span class="ml-auto"><button class="btn btn-sm" type="button" @click="saveText(`steps-${base}.txt`, stepsTxt, 'text/plain;charset=utf-8')"><Icon name="download" small />{{ $t('migration.dlSteps') }}</button></span></div>
          <div class="notice info" style="margin-bottom: 10px"><Icon name="info" /><div class="grow">{{ $t('migration.cutNote') }}</div></div>
          <template v-for="part in (['run', 'rollback'] as const)" :key="part">
            <div class="sec-k mt12">{{ part === 'run' ? $t('migration.runSteps') : $t('migration.rbSteps') }}</div>
            <section class="panel"><div class="ph-list">
              <div v-for="s in steps[part]" :key="s.no" class="phs" :class="stepRisk(s) ? `r-${stepRisk(s)}` : ''" data-testid="mig-step">
                <div class="when">
                  <div class="t0">{{ s.no }}. {{ $t(`migration.phase.${s.phase}`) }}</div>
                  <div class="tags"><DevChip v-if="s.device !== 'site'" :name="devName(s)" :vendor="s.device === 'old' ? result.source.family : result.target.family" /><span v-else class="small faint">{{ $t('migration.dev.site') }}</span></div>
                  <div class="tags">
                    <span v-if="stepRisk(s) === 'cut'" class="risk cut"><Icon name="bolt" />{{ $t('migration.riskCut') }}</span>
                    <span v-else-if="stepRisk(s) === 'care'" class="risk care"><Icon name="warn" />{{ $t('migration.riskCare') }}</span>
                  </div>
                </div>
                <div><div class="pt">{{ stepText(s) }}</div></div>
                <div><pre class="block">{{ s.commands.length ? s.commands.join('\n') : $t('migration.noCmds') }}</pre></div>
              </div>
            </div></section>
          </template>
          <CutoverPlanPanel :body="aiBody" />
        </section>

        <!-- 5 验证 -->
        <section v-if="step === 4" data-testid="mig-ver">
          <div class="step-h"><h2>{{ $t('migration.verTitle') }}</h2><span class="meta">{{ $t('migration.verMeta') }}</span></div>
          <div class="verify" :class="!result.verify.checked ? 'off' : ok ? 'ok' : 'diff'" data-testid="mig-verify">
            <span class="vi"><Icon :name="!result.verify.checked ? 'info' : ok ? 'ok' : 'warn'" /></span>
            <div>
              <h3>{{ !result.verify.checked ? $t('migration.verOff') : result.verify.equal ? $t('migration.verEqual') : ok ? $t('migration.verExplained', { n: result.verify.diffs ?? 0 }, result.verify.diffs ?? 0) : $t('migration.verBad', { n: result.verify.unexplained ?? 0 }, result.verify.unexplained ?? 0) }}</h3>
              <div v-if="result.verify.checked" class="vnums">
                <span>{{ $t('migration.v.diffs') }} <b>{{ result.verify.diffs ?? 0 }}</b></span>
                <span>{{ $t('migration.v.unexplained') }} <b>{{ result.verify.unexplained ?? 0 }}</b></span>
                <span>{{ $t('migration.v.existing') }} <b>{{ result.verify.target_existing ?? 0 }}</b></span>
                <span>{{ $t('migration.v.unmapped') }} <b>{{ result.unmapped.length }}</b></span>
              </div>
            </div>
            <span />
          </div>
          <template v-if="verifyItems.length">
            <div class="sec-k mt12">{{ $t('migration.verItems') }}</div>
            <section class="panel"><div class="tbl-wrap"><table class="tbl"><tbody>
              <tr v-for="(it, i) in verifyItems" :key="i"><td class="mono small">{{ it.node ? terms.describe(it.node) : '' }}</td><td class="why">{{ itemText(it) }}</td></tr>
            </tbody></table></div></section>
          </template>
          <div class="sec-k mt12">{{ $t('migration.package') }}</div>
          <section class="panel"><div class="panel-b gate">
            <span class="ls" :class="ok ? 'ok' : 'warn'">{{ ok ? $t('migration.packageOk') : $t('migration.packageGate') }}</span>
            <button class="btn btn-sm btn-primary" type="button" :disabled="!ok || dirty" data-testid="mig-zip" @click="exportZip"><Icon name="zip" small />{{ $t('migration.packageZip') }}</button>
            <span class="small faint">{{ $t('migration.packageFiles', { list: files.map((f) => f.name).join('、') }) }}</span>
          </div></section>
        </section>
      </template>
    </div>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </main>
</template>

<style scoped>
.setup { display: flex; flex-direction: column; gap: 12px; }
.route { display: grid; grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1fr) minmax(0, .9fr); gap: 10px; align-items: stretch; }
.end { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: var(--surface-2); display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.end-h { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.end-h .k { font-weight: 400; color: var(--ink-3); font-size: 12px; margin-left: auto; }
.end-sel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.end-meta { display: flex; gap: 4px 12px; flex-wrap: wrap; font-size: 12px; color: var(--ink-3); align-items: center; }
.route .arrow { display: flex; align-items: center; justify-content: center; color: var(--ink-3); }
.paste { width: 100%; resize: vertical; font-size: 12px; }
.opts { display: flex; gap: 8px 18px; align-items: center; flex-wrap: wrap; }
.mrail { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 16px 0 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; }
.mrail button { all: unset; box-sizing: border-box; cursor: pointer; padding: 10px 14px 11px; display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 2px 10px; align-items: center; border-left: 1px solid var(--line); position: relative; min-width: 0; }
.mrail button:first-child { border-left: 0; }
.mrail button:hover { background: var(--surface-2); }
.mrail button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.mrail button[aria-current="step"] { background: var(--surface-3); }
.mrail button[aria-current="step"]::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--amber); }
.mrail .no { grid-row: 1 / 3; width: 26px; height: 26px; border-radius: 50%; border: 1.5px solid var(--line-strong); display: inline-flex; align-items: center; justify-content: center; font: 600 12px var(--font-ui); color: var(--ink-2); background: var(--surface); }
.mrail .s-done .no { background: var(--teal); border-color: var(--teal); color: #fff; }
:root[data-theme="dark"] .mrail .s-done .no { color: #06201D; }
.mrail .s-warn .no { background: var(--amber-soft); border-color: var(--amber); color: var(--amber-ink); }
.mrail .s-block .no { border-style: dashed; color: var(--ink-3); }
.mrail .tt { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mrail .st { font-size: 11.5px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mrail .s-warn .st { color: var(--amber-ink); }
.step-h { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.step-h h2 { font-size: 15px; }
.step-h .meta { color: var(--ink-3); font-size: 12px; }
.step-h .ml-auto { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
.sumbar { display: grid; grid-template-columns: minmax(0, 1.3fr) repeat(5, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; margin-bottom: 10px; }
.sumbar > div, .sumbar > button { all: unset; box-sizing: border-box; padding: 10px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 3px; min-width: 0; position: relative; }
.sumbar > :first-child { border-left: 0; }
.sumbar > button { cursor: pointer; }
.sumbar > button:hover { background: var(--surface-2); }
.sumbar > button[aria-pressed="true"] { background: var(--surface-3); }
.sumbar > button[aria-pressed="true"]::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--amber); }
.sumbar .n { font: 600 22px/1.2 var(--font-display); }
.sumbar .n small { font: 400 12px var(--font-ui); color: var(--ink-3); margin-left: 6px; }
.sumbar .k { font-size: 12px; color: var(--ink-2); }
.tw { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 360px; gap: 10px; height: min(66vh, 700px); min-height: 440px; }
.pane { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.pane .tbar { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 1px solid var(--line); font-size: 12px; white-space: nowrap; overflow: hidden; }
.pane .tbar .fn { font: 11.5px var(--font-mono); color: var(--ink-3); }
.pane :deep(.code) { flex: 1; min-height: 0; }
.pane :deep(.code .l) { cursor: pointer; }
.warns { display: flex; flex-direction: column; overflow: hidden; }
.wlist { flex: 1; overflow: auto; }
.wi { padding: 10px 12px 10px 14px; border-bottom: 1px solid var(--line); cursor: pointer; position: relative; }
.wi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bar, transparent); }
.wi.k-default, .wi.k-map { --bar: #D9962B; }
.wi.k-unsup, .wi.k-verify { --bar: var(--red); }
.wi.k-raw { --bar: var(--raw); }
.wi:hover { background: var(--surface-2); }
.wi.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.wi .wh { display: flex; align-items: center; gap: 8px; }
.wi .wid { font: 600 11px var(--font-ui); color: var(--ink-3); }
.wi .wt { margin-top: 5px; font-size: 12.5px; line-height: 1.45; }
.wi .wd { margin-top: 4px; color: var(--ink-2); overflow-wrap: anywhere; }
.map .tbl td { vertical-align: middle; }
.map .arrowc { color: var(--ink-3); text-align: center; width: 28px; }
.map .newif { height: 26px; font-size: 12px; width: 230px; max-width: 100%; }
.map tr.pending td { background: color-mix(in srgb, var(--amber-soft) 55%, transparent); }
.map tr.skip td { color: var(--ink-3); }
.map .link-btn { margin-left: 8px; }
.why { font-size: 12px; color: var(--ink-2); }
.conf { display: inline-block; width: 48px; height: 6px; border-radius: 3px; background: var(--surface-3); margin-right: 6px; vertical-align: middle; overflow: hidden; }
.conf i { display: block; height: 100%; background: var(--teal); }
.conf i.lo { background: var(--amber); }
.unm { padding: 10px 12px; border-top: 1px solid var(--line); }
.sec-k { font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
.map-f { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
.cfgcode { max-height: 70vh; }
.cfgcode :deep(.l.is-mapped .t) { text-decoration: underline; text-decoration-color: var(--teal); text-underline-offset: 3px; }
.ph-list { display: flex; flex-direction: column; }
.phs { display: grid; grid-template-columns: 200px minmax(0, 1fr) minmax(0, 1.1fr); gap: 0 12px; padding: 12px 14px; border-top: 1px solid var(--line); }
.phs:first-child { border-top: 0; }
.phs .when { position: relative; padding-left: 20px; }
.phs .when::before { content: ""; position: absolute; left: 5px; top: 4px; width: 9px; height: 9px; border-radius: 50%; background: var(--surface); border: 2px solid var(--ink-3); }
.phs .when::after { content: ""; position: absolute; left: 10px; top: 17px; bottom: -16px; width: 1px; background: var(--line-strong); }
.phs:last-child .when::after { display: none; }
.phs.r-cut .when::before { border-color: var(--red); background: var(--red-soft); }
.phs.r-care .when::before { border-color: var(--amber); background: var(--amber-soft); }
.phs .t0 { font: 600 12px var(--font-ui); color: var(--ink); }
.phs .pt { font-weight: 600; font-size: 12.5px; }
.phs .tags { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 6px; }
.phs pre.block { font-size: 11.5px; line-height: 1.55; max-height: 260px; margin: 0; }
.gate { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--surface); padding: 8px 14px; border-radius: 6px; font-size: 12.5px; z-index: 60; box-shadow: var(--shadow-pop); }
@media (max-width: 1360px) {
  .tw { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); height: auto; grid-template-rows: min(60vh, 600px) auto; }
  .tw .warns { grid-column: 1 / -1; max-height: 520px; }
  .route { grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1fr); }
  .route .opts { grid-column: 1 / -1; }
}
@media (max-width: 900px) {
  .route { grid-template-columns: minmax(0, 1fr); }
  .route .arrow { transform: rotate(90deg); height: 28px; }
  .end-sel { grid-template-columns: minmax(0, 1fr); }
  .mrail { grid-template-columns: minmax(0, 1fr); }
  .sumbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tw { grid-template-columns: minmax(0, 1fr); grid-template-rows: 380px 380px auto; }
  .tw .warns { grid-column: 1; }
  .phs { grid-template-columns: minmax(0, 1fr); gap: 8px; }
}
</style>
