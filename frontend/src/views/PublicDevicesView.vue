<script setup lang="ts">
/**
 * 公共设备库（管理员，REQ-035，预览 DevelopDocs/ui-preview/M6/public-devices.html）：
 * 统计、筛选、设备表（最新版本、被引用：跟随 / 固定）、右侧详情（版本时间线、引用它的项目）、
 * 导入设备与新版本（POST /public-devices）、删除设备（有引用时 409，可一并解除引用）、删除单个版本、重新解析公共库。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { ApiError, del, errorText, get, post, waitTask } from '@/api'
import { acceptFile, fmtBytes, fmtTime, MAX_FILE_BYTES, vendorLabel } from './devices/logic'
import type { PubDevice, Version } from './add-device/logic'
import { filterPublic, isFresh, publicStats, timeline, type PubFilter } from './public-devices/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`public-devices.${k}`, p ?? {})

const list = ref<PubDevice[]>([])
const loading = ref(true)
const loadErr = ref('')
const q = ref('')
const f = ref<PubFilter>('')
const curId = ref<number | null>(null)
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined
function showToast(m: string): void {
  toast.value = m
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3500)
}
onBeforeUnmount(() => clearTimeout(toastTimer))

async function load(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    list.value = (await get<{ devices: PubDevice[] }>('/public-devices')).devices
    if (!list.value.some((d) => d.id === curId.value)) curId.value = list.value[0]?.id ?? null
  } catch (e) { loadErr.value = errorText(e) } finally { loading.value = false }
}
onMounted(load)

const rows = computed(() => filterPublic(list.value, q.value, f.value))
const stats = computed(() => publicStats(list.value))
const cur = computed(() => list.value.find((d) => d.id === curId.value) ?? null)

// ---------------------------------------------------------------- 版本时间线
const versions = ref<Version[]>([])
const versErr = ref('')
async function loadVersions(): Promise<void> {
  versions.value = []
  versErr.value = ''
  if (!curId.value) return
  try { versions.value = (await get<{ versions: Version[] }>(`/public-devices/${curId.value}/versions`)).versions } catch (e) { versErr.value = errorText(e) }
}
watch(curId, loadVersions)
watch(() => cur.value?.latest_version_id, (v, old) => { if (old !== undefined && v !== old) void loadVersions() })
const tl = computed(() => (cur.value ? timeline(cur.value, versions.value) : []))

// ---------------------------------------------------------------- 导入
const showImport = ref(false)
const impFiles = ref<File[]>([])
const impSkipped = ref<string[]>([])
const impLevel = ref<'basic' | 'strict'>('basic')
const impBusy = ref(false)
const impErr = ref('')
interface ImpResult { source: string; ok: boolean; device: string; error?: string; duplicate?: boolean }
const impResults = ref<ImpResult[] | null>(null)
const impForDevice = ref<string>('')
const impInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
function openImport(d?: PubDevice): void {
  impFiles.value = []
  impSkipped.value = []
  impErr.value = ''
  impResults.value = null
  impForDevice.value = d?.name ?? ''
  showImport.value = true
}
function addImp(fl: FileList | File[]): void {
  const keep = [...impFiles.value]
  const skip: string[] = []
  for (const x of Array.from(fl)) {
    if (!acceptFile(x.name) || x.size > MAX_FILE_BYTES) { skip.push(x.name); continue }
    if (!keep.some((k) => k.name === x.name && k.size === x.size)) keep.push(x)
  }
  impFiles.value = keep
  impSkipped.value = skip
}
function onImpPick(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files) addImp(input.files)
  input.value = ''
}
function onImpDrop(e: DragEvent): void {
  dragging.value = false
  if (e.dataTransfer?.files) addImp(e.dataTransfer.files)
}
/** 导入后对已有设备的影响：跟随最新的项目随之更新，固定版本的项目会看到“有新版本”提示。 */
function impact(name: string): { follow: number; pinned: number } | null {
  const d = list.value.find((x) => x.name.toLowerCase() === name.toLowerCase())
  return d ? { follow: d.follow, pinned: d.pinned } : null
}
const before = ref<Set<string>>(new Set())
async function doImport(): Promise<void> {
  if (!impFiles.value.length) return
  impBusy.value = true
  impErr.value = ''
  before.value = new Set(list.value.map((d) => d.name.toLowerCase()))
  try {
    const fd = new FormData()
    for (const x of impFiles.value) fd.append('files', x, x.name)
    fd.append('level', impLevel.value)
    impResults.value = (await post<{ files: ImpResult[] }>('/public-devices', fd)).files
    await load()
  } catch (e) { impErr.value = errorText(e) } finally { impBusy.value = false }
}

// ---------------------------------------------------------------- 删除
interface DelState { kind: 'device' | 'version'; d: PubDevice; v?: { id: number; seq: number }; force: boolean; busy: boolean; err: string; blockers: { project: string; name?: string }[] }
const delState = ref<DelState | null>(null)
function askDelete(d: PubDevice, v?: { id: number; seq: number }): void {
  delState.value = { kind: v ? 'version' : 'device', d, v, force: false, busy: false, err: '', blockers: v ? [] : d.refs.map((r) => ({ project: r.project, name: r.name })) }
}
async function confirmDelete(): Promise<void> {
  const s = delState.value
  if (!s) return
  s.busy = true
  s.err = ''
  try {
    const path = s.kind === 'device' ? `/public-devices/${s.d.id}` : `/public-devices/${s.d.id}/versions/${s.v?.id}`
    await del(`${path}${s.force ? '?force=true' : ''}`)
    showToast(s.kind === 'device' ? T('deletedDevice', { n: s.d.name }) : T('deletedVersion', { n: s.d.name, v: s.v?.seq ?? '' }))
    delState.value = null
    await load()
    void loadVersions()
  } catch (e) {
    s.err = errorText(e)
    if (e instanceof ApiError && e.status === 409) {
      // data.projects：引用它的项目标识
      const data = e.data as { projects?: (string | { slug?: string; name?: string })[] } | null
      if (data?.projects?.length) s.blockers = data.projects.map((p) => (typeof p === 'string' ? { project: p } : { project: p.slug ?? '', name: p.name }))
    }
  } finally { if (delState.value) delState.value.busy = false }
}

// ---------------------------------------------------------------- 重新解析
const rebuilding = ref(false)
const rebuildPct = ref(0)
async function rebuild(): Promise<void> {
  rebuilding.value = true
  rebuildPct.value = 0
  try {
    const { task_id } = await post<{ task_id: string }>('/public-devices/rebuild')
    const task = await waitTask<{ devices?: number }>(task_id, (x) => { rebuildPct.value = x.progress })
    showToast(task.status === 'done' ? T('rebuilt', { n: task.result?.devices ?? list.value.length }) : T('rebuildFailed', { m: task.message }))
    await load()
  } catch (e) { showToast(errorText(e)) } finally { rebuilding.value = false }
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.sys') }}</span><span class="sep">/</span><span>{{ $t('nav.public-devices') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.public-devices') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" type="button" :disabled="rebuilding || !list.length" data-testid="pub-rebuild" @click="rebuild">
            <Icon name="refresh" small /><span>{{ rebuilding ? T('rebuilding', { p: rebuildPct }) : T('rebuild') }}</span>
          </button>
          <button class="btn btn-primary" type="button" data-testid="pub-import" @click="openImport()"><Icon name="upload" small /><span>{{ T('import') }}</span></button>
        </div>
      </div>

      <div class="m6-strip" data-testid="pub-stats">
        <div><div class="k">{{ T('stTotal') }}</div><div class="v">{{ stats.total }}<small>{{ T('stReferenced', { n: stats.referenced }) }}</small></div></div>
        <div><div class="k">{{ T('stProjects') }}</div><div class="v">{{ stats.projects }}</div></div>
        <div><div class="k">{{ T('stFresh') }}</div><div class="v">{{ stats.fresh }}</div></div>
        <div><div class="k">{{ T('stPinnedOld') }}</div><div class="v" :style="stats.pinnedOld ? 'color: var(--amber-ink)' : ''">{{ stats.pinnedOld }}</div></div>
      </div>

      <div v-if="loadErr" class="notice err"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <div v-else class="lib-wrap">
        <section class="panel">
          <div class="panel-h toolbar" style="padding: 8px 12px">
            <label class="input-wrap" style="width: 220px"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="T('filter')" data-testid="pub-q"></label>
            <div class="seg" role="group" data-testid="pub-filter">
              <button type="button" :aria-pressed="f === ''" @click="f = ''">{{ T('fAll') }}</button>
              <button type="button" :aria-pressed="f === 'fresh'" data-testid="pub-f-fresh" @click="f = 'fresh'">{{ T('fFresh') }}</button>
              <button type="button" :aria-pressed="f === 'unused'" data-testid="pub-f-unused" @click="f = 'unused'">{{ T('fUnused') }}</button>
            </div>
          </div>
          <div v-if="loading && !list.length" class="empty">{{ $t('c.loading') }}</div>
          <div v-else-if="!list.length" class="empty" data-testid="pub-empty">
            <h3>{{ T('empty') }}</h3><p>{{ T('emptyD') }}</p>
            <button class="btn btn-primary" type="button" @click="openImport()"><Icon name="upload" small />{{ T('import') }}</button>
          </div>
          <div v-else class="tbl-wrap">
            <table class="tbl" data-testid="pub-table">
              <thead><tr><th>{{ T('colDevice') }}</th><th>{{ T('colLatest') }}</th><th>{{ T('colRefs') }}</th><th /></tr></thead>
              <tbody>
                <tr v-for="d in rows" :key="d.id" :class="{ 'is-sel': d.id === curId }" style="cursor: pointer" :data-testid="`pub-row-${d.id}`" @click="curId = d.id">
                  <td>
                    <div class="devcell">
                      <span class="vendor"><i :class="d.vendor === 'huawei' ? 'hw' : d.vendor === 'cisco' ? 'cs' : ''">{{ d.vendor === 'huawei' ? 'H' : d.vendor === 'cisco' ? 'C' : '?' }}</i></span>
                      <div><b>{{ d.name }}</b><small>{{ vendorLabel(d.vendor) }} · {{ d.profile }}</small></div>
                    </div>
                  </td>
                  <td>
                    <span class="mono">v{{ d.versions }}</span>
                    <span v-if="isFresh(d)" class="tag t-amber">{{ T('new') }}</span>
                    <div class="small faint">{{ fmtTime(d.collected_at) }}</div>
                  </td>
                  <td>
                    <template v-if="d.refs.length">
                      <span class="refbar"><i class="f" :style="{ width: (d.follow / d.refs.length) * 100 + '%' }" /><i class="p" :style="{ width: (d.pinned / d.refs.length) * 100 + '%' }" /></span>
                      <span class="small">{{ T('nProjects', { n: d.refs.length }) }}</span>
                      <div class="small faint">{{ T('followPinned', { f: d.follow, p: d.pinned }) }}</div>
                    </template>
                    <span v-else class="small faint">{{ T('fUnused') }}</span>
                  </td>
                  <td class="right nowrap"><button class="btn btn-sm" type="button" :data-testid="`pub-newver-${d.id}`" @click.stop="openImport(d)"><Icon name="upload" small />{{ T('newVersion') }}</button></td>
                </tr>
                <tr v-if="!rows.length"><td colspan="4" class="muted" style="text-align: center; padding: 20px">{{ T('noMatch') }}</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <aside class="panel" data-testid="pub-detail">
          <template v-if="cur">
            <div class="panel-h"><h2 class="mono">{{ cur.name }}</h2><span class="meta">{{ cur.profile }}</span></div>
            <div class="panel-b">
              <div class="section-t">{{ T('versions') }}</div>
              <div v-if="versErr" class="notice err"><Icon name="err" /><div class="grow">{{ versErr }}</div></div>
              <div v-else class="vt" data-testid="pub-timeline">
                <div v-for="v in tl" :key="v.id" :data-testid="`pub-ver-${v.seq}`">
                  <span class="vn">v{{ v.seq }}</span>
                  <span class="small muted">{{ fmtTime(v.at) }}</span>
                  <span class="small nowrap">
                    <span v-if="v.follow" class="verchip follow">{{ T('nFollow', { n: v.follow }) }}</span>
                    <span v-if="v.pinned" class="verchip pin">{{ T('nPinned', { n: v.pinned }) }}</span>
                    <button v-if="tl.length > 1" class="btn btn-ghost btn-icon btn-xs" type="button" :title="T('deleteVersion')" :aria-label="T('deleteVersion')" :data-testid="`pub-delver-${v.seq}`" @click="askDelete(cur, { id: v.id, seq: v.seq })"><Icon name="trash" small /></button>
                  </span>
                </div>
              </div>
              <div class="section-t">{{ T('refsBy') }}</div>
              <p v-if="!cur.refs.length" class="small faint">{{ T('noRefsCanDelete') }}</p>
              <table v-else class="tbl compact" data-testid="pub-refs">
                <tbody>
                  <tr v-for="r in cur.refs" :key="r.project">
                    <td>
                      <router-link :to="{ name: 'devices', params: { project: r.project } }">{{ r.name }}</router-link>
                      <div class="small faint">{{ T('owner', { u: r.owner ?? '—' }) }}</div>
                    </td>
                    <td class="right">
                      <span v-if="r.policy === 'follow'" class="verchip follow"><Icon name="refresh" small />{{ T('follow') }}</span>
                      <span v-else class="verchip pin"><Icon name="pin" small />v{{ r.seq ?? '?' }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <hr>
              <div class="row wrap">
                <button class="btn btn-sm" type="button" @click="openImport(cur)"><Icon name="upload" small />{{ T('newVersion') }}</button>
                <button class="btn btn-sm btn-danger ml-auto" type="button" data-testid="pub-delete" @click="askDelete(cur)"><Icon name="trash" small />{{ $t('c.delete') }}</button>
              </div>
              <p v-if="cur.refs.length" class="small faint mt8">{{ T('stillRefs', { n: cur.refs.length }) }}</p>
            </div>
          </template>
          <div v-else class="empty small">{{ T('pick') }}</div>
        </aside>
      </div>
    </div>

    <!-- 导入 -->
    <div v-if="showImport" class="modal-back" data-testid="pub-import-modal" @click.self="!impBusy && (showImport = false)">
      <div class="modal" style="width: min(640px, 100%)" role="dialog" aria-modal="true" aria-labelledby="pubImpT">
        <div class="modal-h">
          <h2 id="pubImpT">{{ impForDevice ? T('importFor', { n: impForDevice }) : T('importTitle') }}</h2>
          <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" :disabled="impBusy" @click="showImport = false"><Icon name="x" /></button>
        </div>
        <div class="modal-b stack">
          <template v-if="!impResults">
            <div class="dropzone" :class="{ over: dragging }" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onImpDrop">
              <Icon name="upload" />
              <div style="font-weight: 600">{{ T('drop') }} <button class="link-btn" type="button" data-testid="pub-browse" @click="impInput?.click()">{{ T('browse') }}</button></div>
              <input ref="impInput" type="file" multiple hidden accept=".cfg,.txt,.log,.conf,.config,.zip" data-testid="pub-file-input" @change="onImpPick">
            </div>
            <p v-if="impForDevice" class="small faint">{{ T('newVersionHint', { n: impForDevice }) }}</p>
            <div v-if="impSkipped.length" class="notice warn"><Icon name="warn" /><div class="grow small">{{ T('skipped', { n: impSkipped.length }) }}</div></div>
            <table v-if="impFiles.length" class="tbl compact">
              <tbody>
                <tr v-for="(x, i) in impFiles" :key="x.name + i"><td class="mono">{{ x.name }}</td><td class="num faint">{{ fmtBytes(x.size) }}</td>
                  <td style="width: 30px"><button class="btn btn-ghost btn-icon btn-xs" type="button" :aria-label="$t('c.delete')" @click="impFiles = impFiles.filter((_, j) => j !== i)"><Icon name="x" small /></button></td></tr>
              </tbody>
            </table>
            <div class="field">
              <label>{{ T('level') }}</label>
              <div class="seg" role="group">
                <button type="button" :aria-pressed="impLevel === 'basic'" @click="impLevel = 'basic'">basic</button>
                <button type="button" :aria-pressed="impLevel === 'strict'" @click="impLevel = 'strict'">strict</button>
              </div>
              <p class="small faint">{{ T('sanitizeNote') }}</p>
            </div>
            <div v-if="impErr" class="notice err"><Icon name="err" /><div class="grow">{{ impErr }}</div></div>
          </template>
          <div v-else class="tbl-wrap">
            <table class="tbl compact" data-testid="pub-import-results">
              <thead><tr><th>{{ T('colFile') }}</th><th>{{ T('colMatch') }}</th><th>{{ T('colImpact') }}</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in impResults" :key="i">
                  <td class="mono">{{ r.source }}<div v-if="r.ok" class="small faint">{{ r.device }}</div></td>
                  <td>
                    <span v-if="!r.ok" class="tag fail">{{ $t('c.failed') }}</span>
                    <span v-else-if="r.duplicate" class="tag">{{ T('duplicate') }}</span>
                    <span v-else-if="before.has(r.device.toLowerCase())" class="tag t-blue">{{ T('existing') }}</span>
                    <span v-else class="tag t-teal">{{ T('newDevice') }}</span>
                  </td>
                  <td class="small">
                    <span v-if="!r.ok" style="color: var(--red-ink)">{{ r.error }}</span>
                    <template v-else-if="before.has(r.device.toLowerCase()) && !r.duplicate && impact(r.device)">{{ T('impact', { f: impact(r.device)?.follow ?? 0, p: impact(r.device)?.pinned ?? 0 }) }}</template>
                    <span v-else class="faint">{{ T('noRefsYet') }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" :disabled="impBusy" @click="showImport = false">{{ impResults ? $t('c.close') : $t('c.cancel') }}</button>
          <button v-if="!impResults" class="btn btn-primary" type="button" :disabled="!impFiles.length || impBusy" data-testid="pub-import-ok" @click="doImport">{{ impBusy ? T('importing') : T('importOk') }}</button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="delState" class="modal-back" data-testid="pub-del-modal" @click.self="delState = null">
      <div class="modal" style="width: min(520px, 100%)" role="dialog" aria-modal="true" aria-labelledby="pubDelT">
        <div class="modal-h">
          <h2 id="pubDelT">{{ delState.kind === 'device' ? T('delTitle', { n: delState.d.name }) : T('delVerTitle', { n: delState.d.name, v: delState.v?.seq ?? '' }) }}</h2>
          <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="delState = null"><Icon name="x" /></button>
        </div>
        <div class="modal-b stack">
          <p>{{ delState.kind === 'device' ? T('delBody', { v: delState.d.versions }) : T('delVerBody') }}</p>
          <div v-if="delState.kind === 'device' && delState.blockers.length" class="notice warn" data-testid="pub-del-blockers">
            <Icon name="warn" />
            <div class="grow">
              <div>{{ T('delRefs', { n: delState.blockers.length }) }}</div>
              <div class="mono small">{{ delState.blockers.map((b) => b.name || b.project).join('、') }}</div>
              <label class="check mt8"><input v-model="delState.force" type="checkbox" data-testid="pub-del-force"> <span>{{ T('delForce') }}</span></label>
            </div>
          </div>
          <p class="small faint">{{ T('delLogged') }}</p>
          <div v-if="delState.err" class="notice err" data-testid="pub-del-error"><Icon name="err" /><div class="grow">{{ delState.err }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="delState = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger-solid" type="button" :disabled="delState.busy || (delState.kind === 'device' && delState.blockers.length > 0 && !delState.force)" data-testid="pub-del-ok" @click="confirmDelete">
            <Icon name="trash" small />{{ $t('c.delete') }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="toast" class="toast" role="status" data-testid="pub-toast"><Icon name="ok" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
.btn-danger-solid:disabled { opacity: .5; cursor: not-allowed; }
</style>
