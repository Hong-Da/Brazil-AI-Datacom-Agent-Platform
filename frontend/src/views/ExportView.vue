<script setup lang="ts">
/**
 * 审计表格导出（预览 DevelopDocs/ui-preview/M5/export.html，REQ-022）：预置模板 / 自定义对象 → 选设备、字段（勾选与拖动排序）、筛选 →
 * 预览（POST /export/table，每格可追溯节点与配置行）→ CSV / XLSX 下载（中文、English、Português 表头）。
 * 格子取值由后端在图上计算；表头叫法按显示风格（华为 / Cisco / Nokia）。
 */
import { STYLES } from '@/terms/terms'
import { vendorKey } from '@/vendor'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import { errorText, get, post } from '@/api'
import { pickLang } from '@/i18n'
import { useTerms } from '@/stores/terms'
import { postFile, saveBlob } from '@/views/check/report'
import type { Device } from '@/views/devices/logic'
import {
  OPS, apiText, cellText, cliText, columnItems, moveKey, sheetName, sortRows, tableBody,
  type AdHoc, type Cell, type ColItem, type FieldInfo, type Preset, type Row, type Selection, type TableResult,
} from './m5/exportTable'

const route = useRoute()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()
const L = (m: Record<string, string> | null | undefined) => (m ? pickLang(m, lang.value) || m.en || '' : '')

// ---------------------------------------------------------------- 基础数据
const presets = ref<Preset[]>([])
const objects = ref<string[]>([])
const devices = ref<Device[]>([])
const loadError = ref('')
async function loadBase(): Promise<void> {
  loadError.value = ''
  try {
    const [p, f, d] = await Promise.all([
      get<{ presets: Preset[] }>(`/export/presets?style=${terms.style}`),
      get<{ objects: string[] }>('/export/fields'),
      get<{ devices: Device[] }>('/devices'),
    ])
    presets.value = p.presets
    objects.value = f.objects
    devices.value = [...d.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    if (!selDevs.value.length) selDevs.value = devices.value.map((x) => x.name)
  } catch (e) {
    loadError.value = errorText(e)
  }
}
watch(() => terms.style, async () => {
  try { presets.value = (await get<{ presets: Preset[] }>(`/export/presets?style=${terms.style}`)).presets } catch { /* 保留原来的 */ }
  void refresh()
})

// ---------------------------------------------------------------- 选择
const presetId = ref<string>('')
const object = ref('interface')
const cols = ref<ColItem[]>([])
const where = ref<string[]>([])
const adhoc = ref<AdHoc[]>([])
const fieldInfo = ref<FieldInfo[]>([])
const selDevs = ref<string[]>([])
const defaults = ref(true)
const canonical = ref(false)
const group = ref(true)
const sort = ref<'dev' | 'key'>('dev')
const preset = computed(() => presets.value.find((p) => p.id === presetId.value) ?? null)
const allDevices = computed(() => devices.value.length > 0 && selDevs.value.length === devices.value.length)

async function loadFields(obj: string): Promise<{ fields: FieldInfo[]; derives: string[] }> {
  try {
    return await get<{ fields: FieldInfo[]; derives: string[] }>(`/export/fields?object=${encodeURIComponent(obj)}`)
  } catch {
    return { fields: [], derives: [] }
  }
}
async function applyPreset(id: string): Promise<void> {
  const p = presets.value.find((x) => x.id === id)
  if (!p) return
  presetId.value = id
  object.value = p.object
  where.value = [...p.where]
  adhoc.value = []
  sel.value = null
  const f = await loadFields(p.object)
  fieldInfo.value = f.fields
  cols.value = columnItems(p, f.fields, f.derives)
  void refresh()
}
async function applyObject(obj: string): Promise<void> {
  presetId.value = ''
  object.value = obj
  where.value = []
  adhoc.value = []
  sel.value = null
  const f = await loadFields(obj)
  fieldInfo.value = f.fields
  cols.value = columnItems(null, f.fields, f.derives)
  void refresh()
}
const showAll = ref(false)
const onCols = computed(() => cols.value.filter((c) => c.on))
const shownCols = computed(() => (showAll.value ? cols.value : cols.value.filter((c) => c.on || cols.value.indexOf(c) < 14)))
const colLabel = (c: ColItem) => (c.label ? L(c.label) : c.derived ? c.key.slice(7) : semantic(c.key) || c.key)
const semantic = (path: string) => { const f = fieldInfo.value.find((x) => x.path === path); return f ? (f.semantic[lang.value as 'en'] || f.semantic.en || '') : '' }
function toggleCol(k: string): void { cols.value = cols.value.map((c) => (c.key === k ? { ...c, on: !c.on } : c)); void refresh() }
function toggleWhere(id: string): void { where.value = where.value.includes(id) ? where.value.filter((x) => x !== id) : [...where.value, id]; void refresh() }
function toggleDev(n: string): void { selDevs.value = selDevs.value.includes(n) ? selDevs.value.filter((x) => x !== n) : [...selDevs.value, n]; void refresh() }
/** 快捷选择：全部 / 全不选 / 某个厂商的设备（只列出现有设备的厂商）。 */
const quickVendors = computed(() => STYLES.filter((v) => devices.value.some((d) => vendorKey(d.vendor) === v)))
function quick(k: 'all' | 'none' | string): void {
  selDevs.value = devices.value.filter((d) => k === 'all' || (k !== 'none' && vendorKey(d.vendor) === k)).map((d) => d.name)
  void refresh()
}
const newFilter = ref<AdHoc>({ field: '', op: '=', value: '' })
function addFilter(): void {
  if (!newFilter.value.field) return
  adhoc.value = [...adhoc.value, { ...newFilter.value }]
  newFilter.value = { field: '', op: '=', value: '' }
  void refresh()
}
function removeFilter(i: number): void { adhoc.value = adhoc.value.filter((_, k) => k !== i); void refresh() }

// 拖动排序
const dragKey = ref<string | null>(null)
const overKey = ref<string | null>(null)
function onDrop(to: string): void {
  if (dragKey.value) { cols.value = moveKey(cols.value, dragKey.value, to); void refresh() }
  dragKey.value = null
  overKey.value = null
}

const selection = computed<Selection>(() => ({
  preset: preset.value,
  object: object.value,
  columns: cols.value,
  where: where.value,
  adhoc: adhoc.value,
  devices: selDevs.value,
  allDevices: allDevices.value,
  defaults: defaults.value,
  canonical: canonical.value,
  style: terms.style,
}))

// ---------------------------------------------------------------- 预览
const table = ref<TableResult | null>(null)
const tblError = ref('')
const loading = ref(false)
let timer = 0
let seq = 0
function refresh(): Promise<void> {
  window.clearTimeout(timer)
  return new Promise((resolve) => { timer = window.setTimeout(() => { void run().then(resolve) }, 250) })
}
async function run(): Promise<void> {
  if (!onCols.value.length || !selDevs.value.length) { table.value = null; tblError.value = ''; return }
  const my = ++seq
  loading.value = true
  tblError.value = ''
  try {
    const r = await post<TableResult>('/export/table', { ...tableBody(selection.value), format: 'json' })
    if (my === seq) table.value = r
  } catch (e) {
    if (my === seq) { table.value = null; tblError.value = errorText(e) }
  } finally {
    if (my === seq) loading.value = false
  }
}
watch([defaults, canonical], () => { void refresh() })
const devOrder = computed(() => devices.value.map((d) => d.name))
const rows = computed(() => (table.value ? sortRows(table.value.rows, sort.value, devOrder.value) : []))
const devInfo = (name: string) => table.value?.devices.find((d) => d.name === name)
const vendorOf = (name: string) => devices.value.find((d) => d.name === name)?.vendor ?? devInfo(name)?.family ?? null
const devCounts = computed(() => {
  const m = new Map<string, number>()
  for (const r of rows.value) m.set(r.device, (m.get(r.device) ?? 0) + 1)
  return [...m.entries()]
})
const unsupCols = computed(() => {
  if (!table.value) return [] as { i: number; devs: string[] }[]
  return table.value.columns.map((_, i) => ({ i, devs: [...new Set(table.value!.rows.filter((r) => r.cells[i]?.origin === 'unsupported').map((r) => r.device))] })).filter((x) => x.devs.length)
})
const unsupOf = (i: number) => unsupCols.value.find((x) => x.i === i)?.devs ?? []
type Disp = { kind: 'none' | 'unsup' | 'secret' | 'def' | 'val'; text: string }
function disp(c: Cell | undefined, i: number): Disp {
  if (!c) return { kind: 'none', text: '' }
  if (c.origin === 'unsupported') return { kind: 'unsup', text: '—' }
  if (c.secret) return { kind: 'secret', text: c.value ? t('export.configured') : t('export.notConfigured') }
  const empty = table.value?.columns[i]?.empty
  if (c.origin === 'none' || cellText(c) === '') return { kind: 'none', text: empty ? L(empty) : '—' }
  if (c.origin === 'default') return defaults.value ? { kind: 'def', text: cellText(c) } : { kind: 'none', text: '' }
  return { kind: 'val', text: cellText(c) }
}
const monoTypes = new Set(['key', 'ipv4', 'integer', 'interface', 'ref', 'derived', 'string'])

// ---------------------------------------------------------------- 格子来源
const sel = ref<{ r: number; c: number } | null>(null)
const selRow = computed<Row | null>(() => (sel.value ? rows.value[sel.value.r] ?? null : null))
const selCell = computed<Cell | null>(() => (sel.value && selRow.value ? selRow.value.cells[sel.value.c] ?? null : null))
const selCol = computed(() => (sel.value ? table.value?.columns[sel.value.c] ?? null : null))
const texts = ref<Record<number, string[]>>({})
async function pickCell(r: number, c: number): Promise<void> {
  sel.value = { r, c }
  const row = rows.value[r]
  if (row?.device_id && !texts.value[row.device_id]) {
    try {
      const g = await get<{ text?: string }>(`/devices/${row.device_id}/graph?raw=true`)
      texts.value = { ...texts.value, [row.device_id]: (g.text ?? '').split('\n') }
    } catch { /* 没有原文时只显示行号 */ }
  }
}
const srcLines = computed(() => {
  const row = selRow.value
  if (!row?.device_id) return []
  const text = texts.value[row.device_id]
  if (!text) return []
  const hl = new Set(selCell.value?.lines ?? [])
  const nums = row.lines.length ? row.lines : [...hl]
  if (!nums.length) return []
  const lo = Math.max(1, Math.min(...nums))
  const hi = Math.min(text.length, Math.max(...nums, ...hl))
  const out = []
  for (let n = lo; n <= hi && out.length < 40; n++) out.push({ n, t: text[n - 1] ?? '', hl: hl.has(n) })
  return out
})
watch(table, () => { sel.value = null })

// ---------------------------------------------------------------- 导出
const fmt = ref<'xlsx' | 'csv'>('xlsx')
const sheets = ref<'per-device' | 'single'>('per-device')
const busy = ref('')
const toast = ref('')
let tt = 0
function flash(s: string): void { toast.value = s; window.clearTimeout(tt); tt = window.setTimeout(() => { toast.value = '' }, 2600) }
async function download(hl: 'zh-CN' | 'en' | 'pt-BR'): Promise<void> {
  busy.value = hl
  try {
    const name = `lmesh-${preset.value?.id ?? object.value}-${hl}.${fmt.value}`
    const f = await postFile('/export/table', { ...tableBody(selection.value), format: fmt.value, lang: hl, sheets: sheets.value }, name)
    saveBlob(f.blob, f.name)
  } catch (e) { flash(errorText(e)) } finally { busy.value = '' }
}
const sheetTabs = computed(() => [t('export.aboutSheet'), ...(sheets.value === 'per-device' ? devCounts.value.map(([n]) => sheetName(n)) : [sheetName(preset.value ? L(preset.value.title) : object.value)])])
const cli = computed(() => cliText(selection.value, fmt.value, sheets.value, lang.value))
const apiStr = computed(() => apiText(selection.value, fmt.value, sheets.value, lang.value))
function copy(s: string): void {
  const ok = () => flash(t('c.copied'))
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(ok, ok)
  else ok()
}
const kpiDefaults = computed(() => table.value?.summary.default_cells ?? 0)
const ICONS: Record<string, string> = { 'ip-address': 'globe', 'bridge-domain': 'layers', 'bgp-peer': 'link', 'interface-description': 'rows', vrf: 'layers', 'static-route': 'branch' }

onMounted(async () => {
  await loadBase()
  const want = typeof route.query.preset === 'string' ? route.query.preset : ''
  const p = presets.value.find((x) => x.id === want || x.aliases.includes(want)) ?? presets.value[0]
  if (p) await applyPreset(p.id)
  else await applyObject('interface')
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.ana') }}</span><span class="sep">/</span><span>{{ $t('nav.export') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('export.title') }}</h1>
          <p class="ph-sub">{{ $t('export.sub') }}</p>
        </div>
      </div>

      <div v-if="loadError" class="notice err mb12"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadBase">{{ $t('c.retry') }}</button></div>

      <div class="strip ex-s" data-testid="exp-kpi">
        <div><div class="k"><Icon name="rows" small />{{ $t('export.kRows') }}</div><div class="v">{{ table?.summary.rows ?? 0 }}</div><div class="s">{{ $t('export.kRowsS') }}</div></div>
        <div><div class="k"><Icon name="server" small />{{ $t('export.kDevices') }}</div><div class="v">{{ devCounts.length }}<small> / {{ selDevs.length }}</small></div><div class="s">{{ $t('export.kDevicesS') }}</div></div>
        <div><div class="k"><Icon name="table" small />{{ $t('export.kCols') }}</div><div class="v">{{ onCols.length }}</div><div class="s">{{ $t('export.kColsS') }}</div></div>
        <div><div class="k"><Icon name="info" small />{{ $t('export.kDefaults') }}</div><div class="v">{{ kpiDefaults }}</div><div class="s">{{ defaults ? $t('export.kDefaultsOn') : $t('export.kDefaultsOff') }}</div></div>
      </div>

      <div class="ex">
        <aside class="panel" aria-label="Templates">
          <div class="panel-h"><h3>{{ $t('export.templates') }}</h3></div>
          <div class="tpls" data-testid="exp-presets">
            <div class="gh">{{ $t('export.builtin') }}</div>
            <button v-for="p in presets" :key="p.id" type="button" class="tpl" :aria-pressed="presetId === p.id" :data-testid="`exp-preset-${p.id}`" @click="applyPreset(p.id)">
              <Icon :name="ICONS[p.id] ?? 'table'" />
              <span><span class="t">{{ L(p.title) }}</span><span class="d">{{ L(p.description) }}</span></span>
            </button>
            <button type="button" class="tpl new" :aria-pressed="!presetId" data-testid="exp-custom" @click="applyObject(object)"><Icon name="plus" /><span class="t">{{ $t('export.custom') }}</span></button>
          </div>
        </aside>

        <div class="stack" style="gap: 12px; min-width: 0">
          <section class="panel" aria-label="Builder">
            <div class="panel-h"><h3>{{ $t('export.builder') }}</h3><span class="meta">{{ object }} · {{ $t('export.nCols', { n: onCols.length }) }}</span></div>
            <div class="bld">
              <div class="k">{{ $t('export.devices') }}</div>
              <div class="devs" data-testid="exp-devices">
                <button v-for="d in devices" :key="d.id" type="button" class="devt" :aria-pressed="selDevs.includes(d.name)" :title="`${d.profile ?? ''} · ${d.sw_version ?? ''}`" @click="toggleDev(d.name)">
                  <input type="checkbox" tabindex="-1" :checked="selDevs.includes(d.name)"><DevChip :name="d.name" :vendor="d.vendor" />
                </button>
                <span class="quick">
                  <button type="button" @click="quick('all')">{{ $t('export.qAll') }}</button>
                  <button v-for="v in quickVendors" :key="v" type="button" :data-vendor="v" @click="quick(v)">{{ $t(`style.${v}`) }}</button>
                  <button type="button" @click="quick('none')">{{ $t('export.qNone') }}</button>
                </span>
                <span v-if="!devices.length" class="small faint">{{ $t('export.noDevices') }}</span>
              </div>

              <div class="k">{{ $t('export.object') }}</div>
              <div class="objsel">
                <select :value="object" class="select" data-testid="exp-object" @change="applyObject(($event.target as HTMLSelectElement).value)">
                  <option v-for="o in objects" :key="o" :value="o">{{ terms.name(o) }} · {{ o }}</option>
                </select>
                <span class="small faint">{{ $t('export.objectHint') }}</span>
              </div>

              <div class="k">{{ $t('export.fields') }}</div>
              <div>
                <div class="fields" data-testid="exp-fields">
                  <span
                    v-for="c in shownCols" :key="c.key" class="fld" :class="[c.on ? 'on' : 'off', { drag: dragKey === c.key, over: overKey === c.key && dragKey !== c.key }]"
                    draggable="true" :title="c.key" :data-k="c.key"
                    @dragstart="dragKey = c.key" @dragover.prevent="overKey = c.key" @drop.prevent="onDrop(c.key)" @dragend="dragKey = null; overKey = null"
                  >
                    <span class="grip">⋮⋮</span>
                    <input type="checkbox" :checked="c.on" :aria-label="colLabel(c)" @change="toggleCol(c.key)">
                    <span v-if="c.on" class="ord">{{ onCols.indexOf(c) + 1 }}</span>
                    <Icon v-if="c.secret" name="lock" small />
                    <span class="nm">{{ colLabel(c) }}</span><code>{{ c.key }}</code>
                  </span>
                  <button v-if="cols.length > shownCols.length || showAll" type="button" class="link-btn small" @click="showAll = !showAll">{{ showAll ? $t('export.fewerFields') : $t('export.moreFields', { n: cols.length - shownCols.length }) }}</button>
                </div>
                <div class="small faint mt8">{{ $t('export.fieldsHint') }}</div>
              </div>

              <div class="k">{{ $t('export.filter') }}</div>
              <div class="filters" data-testid="exp-filters">
                <label v-for="f in preset?.filters ?? []" :key="f.id" class="check"><input type="checkbox" :checked="where.includes(f.id)" :data-testid="`exp-where-${f.id}`" @change="toggleWhere(f.id)"> <span>{{ L(f.label) }}</span></label>
                <span v-for="(f, i) in adhoc" :key="`a${i}`" class="chip">{{ f.field }} {{ f.op }} {{ f.op.includes('exists') ? '' : f.value }}<button class="link-btn" type="button" :aria-label="$t('c.delete')" @click="removeFilter(i)"><Icon name="x" small /></button></span>
                <span class="adhoc">
                  <select v-model="newFilter.field" class="select" :aria-label="$t('export.filterField')"><option value="">{{ $t('export.filterField') }}</option><option v-for="c in cols.filter((x) => !x.derived)" :key="c.key" :value="c.key">{{ c.key }}</option></select>
                  <select v-model="newFilter.op" class="select" aria-label="op"><option v-for="o in OPS" :key="o" :value="o">{{ o }}</option></select>
                  <input v-if="!newFilter.op.includes('exists')" v-model="newFilter.value" class="input" :placeholder="$t('export.filterValue')" @keydown.enter="addFilter">
                  <button class="btn btn-sm" type="button" :disabled="!newFilter.field" @click="addFilter"><Icon name="plus" small />{{ $t('export.addFilter') }}</button>
                </span>
              </div>

              <div class="k">{{ $t('export.options') }}</div>
              <div class="opts">
                <label class="check"><span class="switch"><input v-model="defaults" type="checkbox" data-testid="exp-defaults"><span /></span>{{ $t('export.optDefaults') }}</label>
                <label class="check"><span class="switch"><input v-model="group" type="checkbox"><span /></span>{{ $t('export.optGroup') }}</label>
                <span v-if="object === 'interface' || cols.some((c) => c.on && c.key.includes('interface'))" class="row" style="gap: 6px">
                  <span class="lab">{{ $t('export.ifNames') }}</span>
                  <div class="seg" role="group"><button type="button" :aria-pressed="!canonical" @click="canonical = false">{{ $t('export.asWritten') }}</button><button type="button" :aria-pressed="canonical" :title="$t('export.canonTip')" @click="canonical = true">{{ $t('export.canonical') }}</button></div>
                </span>
                <span class="row" style="gap: 6px"><span class="lab">{{ $t('export.sort') }}</span><select v-model="sort" class="select"><option value="dev">{{ $t('export.sortDev') }}</option><option value="key">{{ $t('export.sortKey') }}</option></select></span>
              </div>
            </div>
          </section>

          <section class="panel" aria-label="Preview">
            <div class="pv-h">
              <h2>{{ $t('export.preview') }}</h2>
              <span class="small faint" data-testid="exp-count">{{ $t('export.count', { rows: rows.length, cols: table?.columns.length ?? 0 }) }}</span>
              <span v-if="loading" class="small faint">{{ $t('c.loading') }}</span>
              <div class="subt"><span v-for="[n, k] in devCounts" :key="n"><DevChip :name="n" :vendor="vendorOf(n)" /><b>{{ k }}</b></span></div>
            </div>
            <div v-if="unsupCols.length && table" class="notice warn" style="margin: 10px 14px 0"><Icon name="warn" /><div class="grow">{{ $t('export.unsupNote', { cols: unsupCols.map((u) => L(table!.columns[u.i].label)).join('、'), devs: [...new Set(unsupCols.flatMap((u) => u.devs))].join('、') }) }} <router-link :to="{ name: 'features' }">{{ $t('export.toFeatures') }}</router-link></div></div>
            <div v-if="tblError" class="notice err" style="margin: 10px 14px"><Icon name="err" /><div class="grow">{{ tblError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
            <div class="pvwrap">
              <div v-if="!onCols.length || !selDevs.length" class="empty"><Icon name="table" /><p>{{ !selDevs.length ? $t('export.pickDevices') : $t('export.pickFields') }}</p></div>
              <div v-else-if="table && !rows.length" class="empty" data-testid="exp-empty"><Icon name="filter" /><h3>{{ $t('export.noRows') }}</h3><p>{{ $t('export.noRowsText') }}</p><div class="row"><button class="btn btn-sm" type="button" @click="where = []; adhoc = []; refresh()">{{ $t('export.clearFilters') }}</button><button class="btn btn-sm" type="button" @click="quick('all')">{{ $t('export.allDevices') }}</button></div></div>
              <table v-else-if="table" class="tbl compact pv" data-testid="exp-table">
                <thead>
                  <tr>
                    <th v-if="!group">{{ $t('export.device') }}</th>
                    <th v-for="(c, i) in table.columns" :key="c.key" :class="{ unsup: unsupOf(i).length }" :title="unsupOf(i).length ? $t('export.unsupTip', { devs: unsupOf(i).join('、') }) : c.schema ?? c.key">
                      <Icon v-if="unsupOf(i).length" name="warn" small /> {{ L(c.label) }}<span class="hpath">{{ c.derive ? `derive:${c.derive}` : c.field }}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="(r, ri) in rows" :key="`${r.device}|${r.node}`">
                    <tr v-if="group && (ri === 0 || rows[ri - 1].device !== r.device)" class="grp"><td :colspan="table.columns.length"><DevChip :name="r.device" :vendor="vendorOf(r.device)" /><span class="cnt">{{ r.profile }}<template v-if="devInfo(r.device)?.version_id"> · v{{ devInfo(r.device)?.version_id }}</template> · {{ $t('export.nRows', { n: devCounts.find(([n]) => n === r.device)?.[1] ?? 0 }) }}</span></td></tr>
                    <tr>
                      <td v-if="!group" @click="pickCell(ri, 0)"><DevChip :name="r.device" :vendor="vendorOf(r.device)" /></td>
                      <td v-for="(c, ci) in table.columns" :key="c.key" :class="{ 'c-sel': sel?.r === ri && sel?.c === ci, unsupc: r.cells[ci]?.origin === 'unsupported' }" :data-testid="`exp-cell-${ri}-${ci}`" @click="pickCell(ri, ci)">
                        <template v-for="d in [disp(r.cells[ci], ci)]" :key="0">
                          <span v-if="d.kind === 'none' || d.kind === 'unsup'" class="none">{{ d.text }}</span>
                          <span v-else-if="d.kind === 'secret'" class="sens"><Icon name="lock" small />{{ d.text }}</span>
                          <span v-else-if="d.kind === 'def'" class="dv" :class="{ mono: monoTypes.has(c.type) }" :data-k="$t('src.default')">{{ d.text }}</span>
                          <span v-else :class="{ mono: monoTypes.has(c.type) }">{{ d.text }}</span>
                        </template>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div class="src" data-testid="exp-source">
              <template v-if="!sel || !selRow || !selCell"><div class="hint"><Icon name="info" small />{{ $t('export.srcHint') }}</div><div /></template>
              <template v-else>
                <div>
                  <dl class="kv">
                    <dt>{{ $t('export.device') }}</dt><dd><DevChip :name="selRow.device" :vendor="vendorOf(selRow.device)" /> <span class="faint small">{{ selRow.profile }}<template v-if="selRow.version_id"> · v{{ selRow.version_id }}</template></span></dd>
                    <dt>{{ $t('export.node') }}</dt><dd><code :title="selRow.node">{{ terms.describe(selRow.node) }}</code><div v-for="n in selCell.nodes.filter((x) => x !== selRow!.node).slice(0, 4)" :key="n" class="small faint mono">{{ n }}</div></dd>
                    <dt>{{ $t('export.value') }}</dt><dd>
                      <template v-if="selCell.origin === 'unsupported'">{{ $t('export.unsupValue') }}</template>
                      <template v-else-if="selCell.secret">{{ selCell.value ? $t('export.configured') : $t('export.notConfigured') }}</template>
                      <span v-else-if="selCell.origin === 'default'" class="dv" :data-k="$t('src.default')">{{ cellText(selCell) }}</span>
                      <template v-else>{{ cellText(selCell) || '—' }}</template>
                    </dd>
                    <dt>{{ $t('export.source') }}</dt><dd>{{ $t(`export.origin.${selCell.origin}`, { path: selCol?.schema ?? selCol?.key ?? '', lines: selCell.lines.join(', ') }) }}</dd>
                    <template v-if="selCell.secret"><dt>{{ $t('export.sensitive') }}</dt><dd>{{ $t('export.sensitiveText') }}</dd></template>
                  </dl>
                </div>
                <div v-if="srcLines.length" class="code"><div v-for="l in srcLines" :key="l.n" class="l" :class="{ 'is-hl': l.hl && !selCell.secret }"><span class="n">{{ l.n }}</span><span class="g" /><span class="t">{{ selCell.secret && l.hl ? '******' : l.t }}</span></div></div>
                <div v-else class="hint">{{ selRow.lines.length ? $t('export.linesOnly', { lines: selRow.lines.join(', ') }) : $t('export.noLines') }}</div>
              </template>
            </div>
          </section>
        </div>

        <aside class="panel xpanel" aria-label="Export">
          <div class="panel-h"><h3>{{ $t('export.export') }}</h3></div>
          <div class="xp-b">
            <div>
              <div class="lbl">{{ $t('export.format') }}</div>
              <div class="fmt radio-cards">
                <label class="radio-card"><input v-model="fmt" type="radio" value="xlsx" data-testid="exp-fmt-xlsx"><span><span class="rc-t">XLSX</span><span class="rc-d" style="display: block">{{ $t('export.xlsx') }}</span></span></label>
                <label class="radio-card"><input v-model="fmt" type="radio" value="csv" data-testid="exp-fmt-csv"><span><span class="rc-t">CSV</span><span class="rc-d" style="display: block">{{ $t('export.csv') }}</span></span></label>
              </div>
            </div>
            <div v-if="fmt === 'xlsx'">
              <div class="lbl">{{ $t('export.sheets') }}</div>
              <div class="seg" role="group" style="margin-bottom: 8px"><button type="button" :aria-pressed="sheets === 'per-device'" @click="sheets = 'per-device'">{{ $t('export.perDevice') }}</button><button type="button" :aria-pressed="sheets === 'single'" @click="sheets = 'single'">{{ $t('export.single') }}</button></div>
              <div class="sheets" aria-label="XLSX"><div class="grid-mini"><div class="hdr" /></div><div class="tabsx"><span v-for="(s, i) in sheetTabs" :key="i" :class="{ on: i === 1 }">{{ s }}</span></div></div>
              <p class="small faint mt8">{{ $t('export.aboutNote', { kb: table?.kb_version ?? '' }) }}</p>
            </div>
            <p v-else class="small faint">{{ $t('export.csvNote') }}</p>
            <div>
              <div class="lbl">{{ $t('export.download') }}</div>
              <div class="dl">
                <button class="btn btn-primary" type="button" :disabled="!rows.length || !!busy" data-testid="exp-dl-zh" @click="download('zh-CN')"><Icon name="download" small /><span>{{ $t('export.hZh') }}<small>.{{ fmt }}</small></span></button>
                <button class="btn" type="button" :disabled="!rows.length || !!busy" data-testid="exp-dl-en" @click="download('en')"><Icon name="download" small /><span>{{ $t('export.hEn') }}<small>.{{ fmt }}</small></span></button>
                <button class="btn" type="button" :disabled="!rows.length || !!busy" data-testid="exp-dl-pt" @click="download('pt-BR')"><Icon name="download" small /><span>{{ $t('export.hPt') }}<small>.{{ fmt }}</small></span></button>
              </div>
              <p class="small faint mt8">{{ $t('export.dlNote') }}</p>
            </div>
            <div class="xnote"><Icon name="info" small /><span>{{ $t('export.noteConfig') }}</span></div>
            <div class="xnote"><Icon name="lock" small /><span>{{ $t('export.noteSecret') }}</span></div>
            <div class="eq">
              <div class="lbl">{{ $t('export.equivalent') }}</div>
              <div class="row"><span class="small faint">CLI</span><button class="btn btn-xs btn-ghost" type="button" @click="copy(cli.replace(/ \\\n {4}/g, ' '))"><Icon name="copy" small />{{ $t('c.copy') }}</button></div>
              <div class="cmdline"><code>{{ cli }}</code></div>
              <div class="row mt8"><span class="small faint">API</span><button class="btn btn-xs btn-ghost" type="button" @click="copy(apiStr)"><Icon name="copy" small />{{ $t('c.copy') }}</button></div>
              <div class="cmdline"><code>{{ apiStr }}</code></div>
            </div>
          </div>
        </aside>
      </div>
    </div>
    <div v-if="toast" class="m5-toast" role="status">{{ toast }}</div>
  </main>
</template>

<style scoped>
.mb12 { margin-bottom: 12px; }
.ex { display: grid; grid-template-columns: 228px minmax(0, 1fr) 320px; gap: 12px; align-items: start; }
@media (max-width: 1560px) { .ex { grid-template-columns: 210px minmax(0, 1fr); } .ex .xpanel { grid-column: 2; } }
@media (max-width: 1000px) { .ex { grid-template-columns: minmax(0, 1fr); } .ex .xpanel { grid-column: 1; } }
.tpls { padding: 6px; display: flex; flex-direction: column; gap: 2px; }
.tpls .gh { font-size: 11.5px; color: var(--ink-3); font-weight: 600; padding: 4px 8px; }
.tpl { display: flex; gap: 9px; align-items: flex-start; padding: 7px 8px; border-radius: 5px; cursor: pointer; border: 1px solid transparent; background: transparent; text-align: left; font: inherit; color: var(--ink); width: 100%; }
.tpl:hover { background: var(--surface-2); }
.tpl[aria-pressed="true"] { background: var(--blue-soft); border-color: var(--blue-line); }
.tpl :deep(.ico) { margin-top: 2px; color: var(--ink-3); flex: none; }
.tpl[aria-pressed="true"] :deep(.ico) { color: var(--blue-ink); }
.tpl .t { font-weight: 600; font-size: 12.5px; display: block; }
.tpl .d { font-size: 11.5px; color: var(--ink-3); line-height: 1.4; margin-top: 1px; display: block; }
.tpl.new { border: 1px dashed var(--line-strong); color: var(--ink-2); margin-top: 6px; align-items: center; }
.bld { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px 12px; align-items: start; padding: 12px 14px; }
.bld > .k { font-size: 12px; color: var(--ink-2); font-weight: 600; padding-top: 5px; }
.devs { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.devt { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 9px 0 6px; border: 1px solid var(--line-strong); border-radius: 5px; background: var(--surface); cursor: pointer; font: inherit; color: var(--ink); }
.devt[aria-pressed="false"] { opacity: .55; border-style: dashed; }
.devt[aria-pressed="true"] { border-color: var(--blue); box-shadow: inset 0 0 0 1px var(--blue); }
.devt input { accent-color: var(--blue); margin: 0; pointer-events: none; }
.quick { display: inline-flex; gap: 4px; margin-left: 6px; flex-wrap: wrap; }
.quick button { border: 0; background: none; color: var(--blue-ink); font: inherit; font-size: 12px; cursor: pointer; padding: 2px 4px; border-radius: 3px; }
.quick button:hover { background: var(--blue-soft); }
.objsel { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.objsel .select { width: auto; min-width: 240px; max-width: 100%; }
.fields { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.fld { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 8px 0 4px; border: 1px solid var(--line-strong); border-radius: 5px; background: var(--surface); cursor: grab; user-select: none; max-width: 100%; }
.fld .grip { color: var(--ink-3); font: 700 11px/1 var(--font-mono); letter-spacing: -2px; width: 10px; }
.fld input { accent-color: var(--teal); margin: 0; }
.fld .nm { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
.fld code { font-size: 10.5px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }
.fld.on { border-color: var(--teal-line); background: color-mix(in srgb, var(--teal-soft) 55%, var(--surface)); }
.fld.off { opacity: .62; }
.fld :deep(.ico) { width: 12px; height: 12px; color: var(--amber-ink); }
.fld.drag { opacity: .35; }
.fld.over { box-shadow: -3px 0 0 var(--amber); }
.fld .ord { font: 700 10px/1 var(--font-ui); color: var(--teal-ink); background: var(--surface); border: 1px solid var(--teal-line); border-radius: 8px; min-width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; }
.filters, .opts { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; }
.filters .chip { display: inline-flex; gap: 4px; align-items: center; font: 12px var(--font-mono); }
.adhoc { display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.adhoc .select { width: auto; height: 28px; font-size: 12px; max-width: 200px; }
.adhoc .input { height: 28px; width: 140px; font-size: 12px; }
.opts .seg button { height: 26px; font-size: 12px; }
.opts .lab { font-size: 12px; color: var(--ink-2); }
.opts .select { width: auto; height: 28px; }
.pv-h { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.pv-h h2 { font-size: 14px; }
.subt { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
.subt span { display: inline-flex; gap: 5px; align-items: center; font-size: 11.5px; color: var(--ink-2); height: 22px; padding: 0 7px 0 4px; border: 1px solid var(--line); border-radius: 11px; background: var(--surface-2); }
.subt span b { color: var(--ink); }
.pvwrap { overflow: auto; max-height: 560px; }
.pv td { cursor: pointer; white-space: nowrap; }
.pv td.c-sel { box-shadow: inset 0 0 0 2px var(--amber); background: var(--hl-line) !important; }
.pv td .none { color: var(--ink-3); }
.pv td .sens { display: inline-flex; gap: 4px; align-items: center; color: var(--ink-2); font-size: 12px; }
.pv th .hpath { display: block; font: 400 10.5px var(--font-mono); color: var(--ink-3); }
.pv th.unsup { color: var(--amber-ink); }
.pv tr.grp td { background: var(--surface-2); font-weight: 600; cursor: default; }
.pv tr.grp td .cnt { font-weight: 400; color: var(--ink-3); margin-left: 8px; }
.pv td.unsupc { background: repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in srgb, var(--line) 55%, transparent) 5px 6px); }
.src { border-top: 1px solid var(--line); padding: 10px 14px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 14px; align-items: start; background: var(--surface-2); border-radius: 0 0 var(--r-panel) var(--r-panel); }
.src .kv { font-size: 12px; }
.src .kv dd { min-width: 0; overflow-wrap: anywhere; }
.src .code { border: 1px solid var(--line); border-radius: 6px; max-height: 210px; overflow: auto; background: var(--surface); }
.src .hint { color: var(--ink-3); font-size: 12px; display: flex; gap: 6px; align-items: center; }
.xp-b { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
.xp-b .lbl { font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
.fmt { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.fmt .radio-card { padding: 8px 10px; }
.sheets { border: 1px solid var(--line); border-radius: 6px; overflow: hidden; background: var(--surface); }
.sheets .grid-mini { height: 70px; background-image: linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px); background-size: 46px 14px; background-color: var(--surface); position: relative; }
.sheets .grid-mini .hdr { position: absolute; left: 0; right: 0; top: 0; height: 14px; background: color-mix(in srgb, var(--teal-soft) 80%, transparent); border-bottom: 1px solid var(--teal-line); }
.sheets .tabsx { display: flex; border-top: 1px solid var(--line); background: var(--surface-2); overflow-x: auto; }
.sheets .tabsx span { font-size: 11px; padding: 3px 9px; border-right: 1px solid var(--line); white-space: nowrap; color: var(--ink-2); }
.sheets .tabsx span.on { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: inset 0 2px 0 var(--teal); }
.dl { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.dl .btn { justify-content: flex-start; height: auto; min-height: 34px; padding: 5px 10px; white-space: normal; text-align: left; line-height: 1.3; }
.dl .btn small { display: block; font-weight: 400; color: var(--ink-3); font-size: 11px; }
.dl .btn-primary small { color: inherit; opacity: .85; }
.eq .cmdline { margin-top: 4px; white-space: pre-wrap; word-break: break-all; align-items: flex-start; font-size: 11.5px; }
.eq .cmdline code { font-size: 11.5px; background: none; border: 0; padding: 0; }
.eq .row { justify-content: space-between; }
.xnote { font-size: 12px; color: var(--ink-2); display: flex; gap: 6px; align-items: flex-start; }
.xnote :deep(.ico) { margin-top: 2px; color: var(--ink-3); flex: none; }
.strip.ex-s { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 12px; }
.strip.ex-s .v { font-size: 18px; }
.strip.ex-s .v small { font-size: 12px; color: var(--ink-3); font-weight: 400; }
.strip.ex-s .k { display: flex; gap: 6px; align-items: center; }
@media (max-width: 900px) { .src { grid-template-columns: minmax(0, 1fr); } .bld { grid-template-columns: minmax(0, 1fr); } }
</style>
