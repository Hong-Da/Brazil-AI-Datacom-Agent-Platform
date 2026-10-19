<script setup lang="ts">
/**
 * 添加设备到项目（REQ-035，预览 DevelopDocs/ui-preview/M6/add-device.html）：
 * 公共设备库引用（跟随最新 / 固定版本）或复制为私有、从我的其他项目复制、导入新配置，三种来源可以混合，底部汇总后一起添加。
 * 没有批量接口：逐条调用 POST /projects/{p}/refs、/devices/copy-in，最后上传文件（POST /configs），逐条报告结果。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjSource from '@/components/proj-source.vue'
import { errorText, get, post } from '@/api'
import { useProject, type ProjectRow } from '@/stores/project'
import { useStatus } from '@/stores/status'
import { acceptFile, fmtBytes, fmtTime, MAX_FILE_BYTES, vendorLabel } from './devices/logic'
import {
  buildOps, classifyImport, inProject, matchDevice, predictName, summarize,
  type ImportKind, type ImportResult, type Op, type ProjDevice, type ProjSel, type PubDevice, type PubSel, type Version,
} from './add-device/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`add-device.${k}`, p ?? {})
const route = useRoute()
const router = useRouter()
const project = useProject()
const status = useStatus()

type Src = 'pub' | 'proj' | 'file'
const src = ref<Src>(['pub', 'proj', 'file'].includes(String(route.query.src)) ? (route.query.src as Src) : 'pub')

// ---------------------------------------------------------------- 本项目的设备
const here = ref<ProjDevice[]>([])
const loadErr = ref('')
async function loadHere(): Promise<void> {
  try {
    here.value = (await get<{ devices: ProjDevice[] }>('/devices')).devices
  } catch (e) { loadErr.value = errorText(e) }
}

// ---------------------------------------------------------------- 公共设备库
const pub = ref<PubDevice[]>([])
const pubLoading = ref(true)
const pubErr = ref('')
const qPub = ref('')
const pubSel = reactive<Record<number, PubSel>>({})
const pubVers = reactive<Record<number, Version[] | 'loading' | 'error'>>({})
const pubRows = computed(() => pub.value.filter((d) => matchDevice(d, qPub.value)))

async function loadPub(): Promise<void> {
  pubLoading.value = true
  pubErr.value = ''
  try { pub.value = (await get<{ devices: PubDevice[] }>('/public-devices')).devices } catch (e) { pubErr.value = errorText(e) } finally { pubLoading.value = false }
}
async function pubVersions(id: number): Promise<void> {
  if (pubVers[id] && pubVers[id] !== 'error') return
  pubVers[id] = 'loading'
  try { pubVers[id] = (await get<{ versions: Version[] }>(`/public-devices/${id}/versions`)).versions } catch { pubVers[id] = 'error' }
}
function togglePub(d: PubDevice, on: boolean): void {
  if (on) pubSel[d.id] = { mode: 'ref', policy: 'follow', versionId: d.latest_version_id }
  else delete pubSel[d.id]
}
function setMode(d: PubDevice, mode: 'ref' | 'copy'): void {
  const s = pubSel[d.id]
  if (!s) return
  s.mode = mode
  if (mode === 'copy') void pubVersions(d.id)
}
function setPolicy(d: PubDevice, p: 'follow' | 'pin'): void {
  const s = pubSel[d.id]
  if (!s) return
  s.policy = p
  if (p === 'pin') void pubVersions(d.id)
}
const pubVerList = (id: number): Version[] => (Array.isArray(pubVers[id]) ? (pubVers[id] as Version[]) : [])

// ---------------------------------------------------------------- 我的其他项目
const projects = ref<ProjectRow[]>([])
const srcProject = ref<string>('')
const srcDevices = ref<ProjDevice[]>([])
const srcLoading = ref(false)
const srcErr = ref('')
const projSel = reactive<Record<number, ProjSel>>({})
const srcVers = reactive<Record<number, Version[] | 'loading' | 'error'>>({})

async function loadProjects(): Promise<void> {
  try {
    const l = await project.loadLists()
    projects.value = [...l.mine, ...l.shared].filter((p) => p.slug !== project.slug)
    if (!srcProject.value && projects.value.length) srcProject.value = projects.value[0].slug
  } catch (e) { srcErr.value = errorText(e) }
}
watch(srcProject, async (s) => {
  for (const k of Object.keys(projSel)) delete projSel[+k]
  for (const k of Object.keys(srcVers)) delete srcVers[+k]
  srcDevices.value = []
  if (!s) return
  srcLoading.value = true
  srcErr.value = ''
  try {
    // 路径以 /projects/ 开头，api.ts 不会改写到当前项目
    srcDevices.value = (await get<{ devices: ProjDevice[] }>(`/projects/${encodeURIComponent(s)}/devices`)).devices
  } catch (e) { srcErr.value = errorText(e) } finally { srcLoading.value = false }
})
function takenNames(except?: number): string[] {
  return [...here.value.map((d) => d.name), ...Object.entries(projSel).filter(([id]) => +id !== except).map(([, s]) => s.name)]
}
function toggleProj(d: ProjDevice, on: boolean): void {
  if (!on) { delete projSel[d.id]; return }
  projSel[d.id] = { versionId: null, name: predictName(d.name, takenNames(d.id)) }
  if (d.source !== 'public') void srcVersions(d.id)
}
async function srcVersions(id: number): Promise<void> {
  if (srcVers[id] && srcVers[id] !== 'error') return
  srcVers[id] = 'loading'
  try {
    srcVers[id] = (await get<{ versions: Version[] }>(`/projects/${encodeURIComponent(srcProject.value)}/devices/${id}/versions`)).versions
  } catch { srcVers[id] = 'error' }
}
const srcVerList = (id: number): Version[] => (Array.isArray(srcVers[id]) ? (srcVers[id] as Version[]) : [])
const renamed = (d: ProjDevice) => !!projSel[d.id] && projSel[d.id].name.trim().toLowerCase() !== d.name.toLowerCase() && here.value.some((x) => x.name.toLowerCase() === d.name.toLowerCase())

// ---------------------------------------------------------------- 导入新配置
const files = ref<File[]>([])
const skipped = ref<string[]>([])
const level = ref<'basic' | 'strict'>('basic')
const dragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
function addFiles(list: FileList | File[]): void {
  const keep = [...files.value]
  const skip: string[] = []
  for (const f of Array.from(list)) {
    if (!acceptFile(f.name) || f.size > MAX_FILE_BYTES) { skip.push(f.name); continue }
    if (!keep.some((k) => k.name === f.name && k.size === f.size)) keep.push(f)
  }
  files.value = keep
  skipped.value = skip
}
function onPick(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files) addFiles(input.files)
  input.value = ''
}
function onDrop(e: DragEvent): void {
  dragging.value = false
  if (e.dataTransfer?.files) addFiles(e.dataTransfer.files)
}

// ---------------------------------------------------------------- 汇总与执行
const ops = computed<Op[]>(() => buildOps(pub.value, pubSel, srcProject.value || null, srcDevices.value, projSel))
const sum = computed(() => summarize(ops.value, files.value.length))
const nothing = computed(() => !ops.value.length && !files.value.length)

interface Outcome { label: string; what: string; ok: boolean; msg: string }
const running = ref(false)
const progress = reactive({ done: 0, total: 0 })
const outcomes = ref<Outcome[]>([])
const imported = ref<{ r: ImportResult; kind: ImportKind }[]>([])
const runErr = ref('')

async function addAll(): Promise<void> {
  if (!project.slug || !project.canWrite || nothing.value || running.value) return
  const slug = encodeURIComponent(project.slug)
  const list = ops.value
  running.value = true
  runErr.value = ''
  outcomes.value = []
  imported.value = []
  progress.done = 0
  progress.total = list.length + (files.value.length ? 1 : 0)
  for (const op of list) {
    const what = op.kind === 'ref' ? (op.versionId ? T('opRefPin') : T('opRefFollow')) : op.from === 'public' ? T('opCopyPub') : T('opCopyProj', { p: op.from })
    try {
      if (op.kind === 'ref') {
        await post(`/projects/${slug}/refs`, { device_id: op.deviceId, version_id: op.versionId })
        outcomes.value.push({ label: op.label, what, ok: true, msg: '' })
      } else {
        const r = await post<{ device?: { name?: string }; name?: string; renamed?: boolean }>(`/projects/${slug}/devices/copy-in`, {
          device_id: op.deviceId, version_id: op.versionId, ...(op.name ? { name: op.name } : {}),
        })
        const newName = r.device?.name ?? r.name ?? ''
        outcomes.value.push({ label: op.label, what, ok: true, msg: newName && newName !== op.label ? T('copiedAs', { n: newName }) : '' })
      }
      if (op.kind === 'ref' || op.from === 'public') delete pubSel[op.deviceId]
      else delete projSel[op.deviceId]
    } catch (e) {
      outcomes.value.push({ label: op.label, what, ok: false, msg: errorText(e) })
    }
    progress.done++
  }
  if (files.value.length) {
    const before = here.value.slice()
    try {
      const fd = new FormData()
      for (const f of files.value) fd.append('files', f, f.name)
      fd.append('level', level.value)
      const data = await post<{ files: ImportResult[] }>('/configs', fd)
      const kinds = classifyImport(data.files, before)
      imported.value = data.files.map((r, i) => ({ r, kind: kinds[i] }))
      files.value = []
    } catch (e) {
      runErr.value = errorText(e)
    }
    progress.done++
  }
  running.value = false
  await loadHere()
  void loadPub()
  void status.refresh()
}
const failed = computed(() => outcomes.value.filter((o) => !o.ok).length + imported.value.filter((x) => x.kind === 'failed').length)
const finished = computed(() => !running.value && (outcomes.value.length > 0 || imported.value.length > 0))

onMounted(async () => {
  await Promise.all([loadHere(), loadPub(), loadProjects()])
})
watch(() => project.slug, () => { void loadHere(); void loadProjects() })
watch(src, (s) => { void router.replace({ query: { ...route.query, src: s } }) })
const KIND_TAG: Record<ImportKind, string> = { new: 't-teal', version: 't-blue', duplicate: '', failed: 'fail' }
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs">
        <span>{{ project.info?.name }}</span><span class="sep">/</span>
        <router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link><span class="sep">/</span>
        <span>{{ $t('nav.add-device') }}</span>
      </div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ T('title') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
      </div>

      <div v-if="!project.canWrite && project.info" class="notice warn mb12" data-testid="add-readonly">
        <Icon name="eye" /><div class="grow">{{ T('readOnly', { u: project.info.owner ?? '—' }) }}</div>
      </div>
      <div v-if="loadErr" class="notice err mb12"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="loadHere">{{ $t('c.retry') }}</button></div>

      <div class="srcpick" role="radiogroup" data-testid="add-source">
        <label class="radio-card"><input v-model="src" type="radio" value="pub" data-testid="src-pub"><div><div class="rc-t"><Icon name="db" small />{{ T('srcPub') }}</div><div class="rc-d">{{ T('srcPubD') }}</div></div></label>
        <label class="radio-card"><input v-model="src" type="radio" value="proj" data-testid="src-proj"><div><div class="rc-t"><Icon name="folders" small />{{ T('srcProj') }}</div><div class="rc-d">{{ T('srcProjD') }}</div></div></label>
        <label class="radio-card"><input v-model="src" type="radio" value="file" data-testid="src-file"><div><div class="rc-t"><Icon name="upload" small />{{ T('srcFile') }}</div><div class="rc-d">{{ T('srcFileD') }}</div></div></label>
      </div>

      <!-- 公共设备库 -->
      <section v-show="src === 'pub'" class="panel" data-testid="add-pub">
        <div class="panel-h toolbar" style="padding: 8px 12px">
          <label class="input-wrap" style="width: 240px"><Icon name="search" small /><input v-model="qPub" class="input" type="search" :placeholder="T('filterPub')" data-testid="add-pub-q"></label>
          <span class="grow" />
          <span class="small faint">{{ T('pubNote') }}</span>
        </div>
        <div v-if="pubErr" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ pubErr }}</div><button class="btn btn-sm" type="button" @click="loadPub">{{ $t('c.retry') }}</button></div>
        <div v-else-if="pubLoading" class="empty">{{ $t('c.loading') }}</div>
        <div v-else-if="!pub.length" class="empty" data-testid="add-pub-empty"><h3>{{ T('pubEmpty') }}</h3><p>{{ T('pubEmptyD') }}</p></div>
        <div v-else class="tbl-wrap">
          <table class="tbl" data-testid="add-pub-table">
            <thead><tr><th style="width: 32px" /><th>{{ T('colDevice') }}</th><th>{{ T('colLatest') }}</th><th>{{ T('colAddAs') }}</th><th>{{ T('colVersion') }}</th><th class="num">{{ T('colRefs') }}</th></tr></thead>
            <tbody>
              <tr v-for="d in pubRows" :key="d.id" :class="{ 'tr-dis': inProject(d, here) }" :data-testid="`add-pub-row-${d.id}`">
                <td>
                  <input v-if="inProject(d, here)" type="checkbox" class="check" checked disabled :aria-label="d.name">
                  <input v-else type="checkbox" class="check" :checked="!!pubSel[d.id]" :disabled="!project.canWrite" :aria-label="d.name" :data-testid="`add-pub-check-${d.id}`" @change="togglePub(d, ($event.target as HTMLInputElement).checked)">
                </td>
                <td>
                  <div class="devcell">
                    <span class="vendor"><i :class="d.vendor === 'huawei' ? 'hw' : d.vendor === 'cisco' ? 'cs' : ''">{{ d.vendor === 'huawei' ? 'H' : d.vendor === 'cisco' ? 'C' : '?' }}</i></span>
                    <div><b>{{ d.name }}</b><small>{{ vendorLabel(d.vendor) }} · {{ d.profile }}</small></div>
                  </div>
                </td>
                <td class="small"><span class="mono">v{{ d.versions }}</span> <span class="faint">{{ fmtTime(d.collected_at) }}</span></td>
                <td>
                  <span v-if="inProject(d, here) === 'ref'" class="small faint">{{ T('already') }}</span>
                  <span v-else-if="inProject(d, here) === 'name'" class="small" style="color: var(--amber-ink)">{{ T('sameName') }}</span>
                  <div v-else class="seg" role="group">
                    <button type="button" :aria-pressed="!pubSel[d.id] || pubSel[d.id].mode === 'ref'" :disabled="!pubSel[d.id]" :data-testid="`add-pub-mode-ref-${d.id}`" @click="setMode(d, 'ref')">{{ T('modeRef') }}</button>
                    <button type="button" :aria-pressed="pubSel[d.id]?.mode === 'copy'" :disabled="!pubSel[d.id]" :data-testid="`add-pub-mode-copy-${d.id}`" @click="setMode(d, 'copy')">{{ T('modeCopy') }}</button>
                  </div>
                </td>
                <td>
                  <span v-if="pubSel[d.id] && !inProject(d, here)" class="pol">
                    <select v-if="pubSel[d.id].mode === 'ref'" class="select" :value="pubSel[d.id].policy" :data-testid="`add-pub-policy-${d.id}`" @change="setPolicy(d, ($event.target as HTMLSelectElement).value as 'follow' | 'pin')">
                      <option value="follow">{{ T('follow') }}</option>
                      <option value="pin">{{ T('pin') }}</option>
                    </select>
                    <span v-else class="small muted">{{ T('copyVersion') }}</span>
                    <select v-if="pubSel[d.id].mode === 'copy' || pubSel[d.id].policy === 'pin'" v-model="pubSel[d.id].versionId" class="select" :data-testid="`add-pub-ver-${d.id}`">
                      <option v-if="!pubVerList(d.id).length" :value="d.latest_version_id">v{{ d.versions }}</option>
                      <option v-for="v in pubVerList(d.id)" :key="v.id" :value="v.id">v{{ v.seq }}{{ v.latest ? T('latestMark') : '' }}</option>
                    </select>
                  </span>
                  <span v-else-if="!inProject(d, here)" class="small faint">—</span>
                </td>
                <td class="num small muted">{{ T('nProjects', { n: d.refs.length }) }}</td>
              </tr>
              <tr v-if="!pubRows.length"><td colspan="6" class="muted" style="text-align: center; padding: 20px">{{ T('noMatch') }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 我的其他项目 -->
      <section v-show="src === 'proj'" class="panel" data-testid="add-proj">
        <div class="panel-h toolbar" style="padding: 8px 12px">
          <span class="small muted">{{ T('srcProject') }}</span>
          <select v-model="srcProject" class="select" style="width: auto" :disabled="!projects.length" data-testid="add-src-project">
            <option v-for="p in projects" :key="p.slug" :value="p.slug">{{ p.name }}{{ p.role !== 'owner' ? ` — ${$t(`proj.role.${p.role}`)} · ${p.owner ?? ''}` : '' }}</option>
          </select>
          <span class="grow" />
          <span class="small faint">{{ T('projNote') }}</span>
        </div>
        <div v-if="srcErr" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ srcErr }}</div></div>
        <div v-else-if="!projects.length" class="empty" data-testid="add-proj-none"><h3>{{ T('noOtherProjects') }}</h3><p>{{ T('noOtherProjectsD') }}</p></div>
        <div v-else-if="srcLoading" class="empty">{{ $t('c.loading') }}</div>
        <div v-else class="tbl-wrap">
          <table class="tbl" data-testid="add-proj-table">
            <thead><tr><th style="width: 32px" /><th>{{ T('colDevice') }}</th><th>{{ T('colInSource') }}</th><th>{{ T('colCopyVersion') }}</th><th>{{ T('colNewName') }}</th></tr></thead>
            <tbody>
              <tr v-for="d in srcDevices" :key="d.id" :data-testid="`add-proj-row-${d.id}`">
                <td><input type="checkbox" class="check" :checked="!!projSel[d.id]" :disabled="!project.canWrite" :aria-label="d.name" :data-testid="`add-proj-check-${d.id}`" @change="toggleProj(d, ($event.target as HTMLInputElement).checked)"></td>
                <td>
                  <div class="devcell">
                    <span class="vendor"><i :class="d.vendor === 'huawei' ? 'hw' : d.vendor === 'cisco' ? 'cs' : ''">{{ d.vendor === 'huawei' ? 'H' : d.vendor === 'cisco' ? 'C' : '?' }}</i></span>
                    <div><b>{{ d.name }}</b><small>{{ d.profile }}</small></div>
                  </div>
                </td>
                <td><ProjSource :source="d.source" :policy="d.policy" :seq="d.source === 'public' && d.policy === 'pin' ? d.pinned_seq : d.versions" /></td>
                <td>
                  <select v-if="projSel[d.id]" v-model="projSel[d.id].versionId" class="select" style="height: 26px; font-size: 12px; width: auto" :data-testid="`add-proj-ver-${d.id}`">
                    <option :value="null">{{ d.source === 'public' ? T('usedBySource') : `v${d.versions}${T('currentMark')}` }}</option>
                    <template v-if="d.source !== 'public'">
                      <option v-for="v in srcVerList(d.id).filter((x) => !x.current)" :key="v.id" :value="v.id">v{{ v.seq }}</option>
                    </template>
                  </select>
                  <span v-else class="small faint">—</span>
                </td>
                <td>
                  <template v-if="projSel[d.id]">
                    <input v-model="projSel[d.id].name" class="input mono" style="height: 26px; font-size: 12px; width: 200px" :aria-label="T('colNewName')" :data-testid="`add-proj-name-${d.id}`">
                    <div v-if="renamed(d)" class="small" style="color: var(--amber-ink)">{{ T('autoRenamed') }}</div>
                  </template>
                  <span v-else class="small faint">—</span>
                </td>
              </tr>
              <tr v-if="!srcDevices.length"><td colspan="5" class="muted" style="text-align: center; padding: 20px">{{ T('sourceEmpty') }}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="panel-f small faint">{{ T('projFoot') }}</div>
      </section>

      <!-- 导入新配置 -->
      <section v-show="src === 'file'" class="panel" data-testid="add-file">
        <div class="panel-b">
          <div class="dropzone" :class="{ over: dragging }" data-testid="add-dropzone" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
            <Icon name="upload" />
            <div style="font-weight: 600">{{ T('drop') }} <button class="link-btn" type="button" :disabled="!project.canWrite" data-testid="add-browse" @click="fileInput?.click()">{{ T('browse') }}</button></div>
            <div class="small faint mt8">{{ T('dropD') }}</div>
            <input ref="fileInput" type="file" multiple hidden accept=".cfg,.txt,.log,.conf,.config,.zip" data-testid="add-file-input" @change="onPick">
          </div>
          <div v-if="skipped.length" class="notice warn mt12"><Icon name="warn" /><div class="grow small">{{ T('skipped', { n: skipped.length }) }} <span class="mono">{{ skipped.slice(0, 5).join('、') }}</span></div></div>
          <div v-if="files.length" class="tbl-wrap mt12">
            <table class="tbl compact" data-testid="add-files">
              <thead><tr><th>{{ T('colFile') }}</th><th class="num">{{ T('colSize') }}</th><th /></tr></thead>
              <tbody>
                <tr v-for="(f, i) in files" :key="f.name + i">
                  <td class="mono">{{ f.name }}</td>
                  <td class="num faint">{{ fmtBytes(f.size) }}</td>
                  <td style="width: 30px"><button class="btn btn-ghost btn-icon btn-xs" type="button" :aria-label="$t('c.delete')" @click="files = files.filter((_, j) => j !== i)"><Icon name="x" small /></button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="field mt12">
            <label>{{ T('level') }}</label>
            <div class="seg" role="group">
              <button type="button" :aria-pressed="level === 'basic'" @click="level = 'basic'">basic · {{ T('lvBasic') }}</button>
              <button type="button" :aria-pressed="level === 'strict'" @click="level = 'strict'">strict · {{ T('lvStrict') }}</button>
            </div>
            <p class="small faint">{{ T('fileNote') }}</p>
          </div>
        </div>
      </section>

      <!-- 结果 -->
      <section v-if="running || finished || runErr" class="panel mt12" data-testid="add-results">
        <div class="panel-h">
          <h2>{{ running ? T('running', { d: progress.done, n: progress.total }) : T('resultTitle') }}</h2>
          <span v-if="finished" class="meta">{{ failed ? T('resultFailed', { n: failed }) : T('resultOk') }}</span>
        </div>
        <div class="panel-b">
          <div v-if="running" class="progress striped mb12"><i :style="{ width: Math.max(4, (progress.done / Math.max(1, progress.total)) * 100) + '%' }" /></div>
          <div v-if="runErr" class="notice err mb12"><Icon name="err" /><div class="grow">{{ T('uploadFailed') }}{{ runErr }}</div></div>
          <table v-if="outcomes.length || imported.length" class="tbl compact">
            <tbody>
              <tr v-for="(o, i) in outcomes" :key="'o' + i" :data-testid="`add-outcome-${i}`">
                <td style="width: 24px"><Icon :name="o.ok ? 'ok' : 'err'" small /></td>
                <td class="mono">{{ o.label }}</td>
                <td class="small">{{ o.what }}</td>
                <td class="small" :class="o.ok ? 'faint' : ''" :style="o.ok ? '' : 'color: var(--red-ink)'">{{ o.ok ? (o.msg || T('done')) : o.msg }}</td>
              </tr>
              <tr v-for="(x, i) in imported" :key="'f' + i" :data-testid="`add-import-${i}`">
                <td style="width: 24px"><Icon :name="x.kind === 'failed' ? 'err' : 'ok'" small /></td>
                <td class="mono">{{ x.r.source }}</td>
                <td class="small"><span :class="['tag', KIND_TAG[x.kind]]">{{ T(`kind.${x.kind}`) }}</span></td>
                <td class="small">
                  <span v-if="x.kind === 'failed'" style="color: var(--red-ink)">{{ x.r.error }}</span>
                  <span v-else class="mono">{{ x.r.device }}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="finished" class="row mt12">
            <router-link class="btn btn-primary" :to="{ name: 'devices' }" data-testid="add-back"><Icon name="server" small />{{ T('backToDevices') }}</router-link>
          </div>
        </div>
      </section>

      <div class="add-sum" data-testid="add-summary">
        <Icon name="plus" small />
        <div class="grow">
          {{ T('sumPrefix') }}<b>{{ sum.refFollow + sum.refPin }}</b>{{ T('sumRefs', { f: sum.refFollow, p: sum.refPin }) }} · <b>{{ sum.copies }}</b>{{ T('sumCopies') }} · <b>{{ sum.files }}</b>{{ T('sumFiles') }}
        </div>
        <router-link class="btn" :to="{ name: 'devices' }">{{ $t('c.cancel') }}</router-link>
        <button class="btn btn-primary" type="button" :disabled="nothing || running || !project.canWrite" data-testid="add-submit" @click="addAll">
          <Icon name="check" small /><span>{{ running ? T('adding') : T('add') }}</span>
        </button>
      </div>
    </div>
  </main>
</template>

<style scoped>
.mb12 { margin-bottom: 12px; }
.devcell small { font-family: var(--font-ui); }
</style>
