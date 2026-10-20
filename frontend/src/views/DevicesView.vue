<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjSource from '@/components/proj-source.vue'
import { del, errorText, get, post, put, waitTask } from '@/api'
import { useStatus } from '@/stores/status'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import ImportDialog from './devices/ImportDialog.vue'
import CopyToDialog from './devices/CopyToDialog.vue'
import DevDelDialog from '@/components/devdel-dialog.vue'
import { filterDevices, fmtTime, vendorCounts, vendorLabel, type DevFilter } from './devices/logic'
import { bySource, currentSeq, newerRefs, rowActions, stats, type ProjectDevice, type RowAction, type SrcFilter } from './devices/project'
import VendorBadge from '@/components/vendor-badge.vue'
import DeviceIcon from '@/components/devicon/DeviceIcon.vue'
import { loadMarks } from '@/components/devicon/data'
import { annoByDevice, badgesOf, pendingOf, resolveRole, vendorCode, type DeviceAnno, type PendingSuggestion } from '@/components/devicon/logic'

const route = useRoute()
const router = useRouter()
const status = useStatus()
const auth = useAuth()
const project = useProject()
const { t } = useI18n()
// 只读成员、只读令牌：不显示导入、重新解析、删除等修改操作（以后端 403 为准，这里只是不让人点）
const canWrite = computed(() => project.canWrite)

const devices = ref<ProjectDevice[]>([])
const kbVersion = ref('')
const loading = ref(true)
const loadError = ref('')
const filter = reactive<DevFilter>({ q: '', vendor: '', state: '' })
const checked = ref<Set<number>>(new Set())
const showImport = ref(false)

// 设备图标（REQ-042）：角色按项目视图标注（手工 > 采纳的 AI > 平台默认），角标：配置过期、AI 待采纳
const annos = ref<Map<string, DeviceAnno>>(new Map())
const pendingAi = ref<PendingSuggestion[]>([])
async function loadIcons(): Promise<void> {
  if (!project.ref) return
  const m = await loadMarks(project.ref)
  annos.value = annoByDevice(m.annotations)
  pendingAi.value = m.pending
}
const pendingDevs = computed(() => new Set(pendingOf(pendingAi.value).hints.map((h) => h.device_id)))
function iconOf(d: ProjectDevice): { kind: string; vendor: ReturnType<typeof vendorCode>; badges: ReturnType<typeof badgesOf>; title: string } {
  const r = resolveRole(annos.value.get(String(d.id)), d.profile, d.vendor)
  const role = r.role ? t(`devicon.role.${r.role}`) : t(`devicon.plat.${r.glyph}`)
  return { kind: r.glyph, vendor: vendorCode(d.vendor, d.profile), badges: badgesOf({ stale: !!d.stale, ai: pendingDevs.value.has(d.id) }), title: `${role} · ${t(`devicon.src.${r.source}`)}` }
}

async function load(): Promise<void> {
  void loadIcons()
  loading.value = true
  loadError.value = ''
  try {
    const d = await get<{ devices: ProjectDevice[]; kb_version: string }>('/devices')
    devices.value = d.devices
    kbVersion.value = d.kb_version
    const ids = new Set(d.devices.map((x) => x.id))
    checked.value = new Set([...checked.value].filter((id) => ids.has(id)))
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  if (route.query.import === '1') {
    showImport.value = true
    void router.replace({ query: { ...route.query, import: undefined } })
  }
})

const src = ref<SrcFilter>('')
const rows = computed(() => bySource(filterDevices(devices.value, filter), src.value))
const st = computed(() => stats(devices.value))
const newer = computed(() => newerRefs(devices.value))
const vendors = computed(() => vendorCounts(devices.value))
const staleCount = computed(() => devices.value.filter((d) => d.stale).length)
const allChecked = computed(() => rows.value.length > 0 && rows.value.every((d) => checked.value.has(d.id)))

function toggle(id: number, on: boolean): void {
  const s = new Set(checked.value)
  if (on) s.add(id)
  else s.delete(id)
  checked.value = s
}
function toggleAll(on: boolean): void {
  const s = new Set(checked.value)
  for (const d of rows.value) {
    if (on) s.add(d.id)
    else s.delete(d.id)
  }
  checked.value = s
}
function clearFilters(): void {
  filter.q = ''
  filter.vendor = ''
  filter.state = ''
}

// ---- 重新生成图：全部（后台任务）或所选（逐台调用）
interface RebuildResult { devices: number; roundtrip_failed: number; parse_failed: number }
const rebuilding = ref(false)
const rebuildProgress = ref(0)
const rebuildMsg = ref('')
const rebuildResult = ref<RebuildResult | null>(null)
const rebuildError = ref('')

// allProjects：全部项目与公共设备库（只限管理员，旧路径 POST /devices/rebuild）；否则本项目
async function rebuildAll(allProjects = false): Promise<void> {
  rebuilding.value = true
  rebuildProgress.value = 0
  rebuildMsg.value = ''
  rebuildResult.value = null
  rebuildError.value = ''
  try {
    const { task_id } = await post<{ task_id: string }>('/devices/rebuild', {}, { project: allProjects ? false : undefined })
    const t = await waitTask<RebuildResult>(task_id, (x) => { rebuildProgress.value = x.progress; rebuildMsg.value = x.message })
    if (t.status === 'failed') rebuildError.value = t.message
    else rebuildResult.value = t.result
  } catch (e) {
    rebuildError.value = errorText(e)
  } finally {
    rebuilding.value = false
    await Promise.all([load(), status.refresh()])
  }
}

async function rebuildSelected(): Promise<void> {
  const ids = [...checked.value]
  if (!ids.length) return
  rebuilding.value = true
  rebuildProgress.value = 0
  rebuildResult.value = null
  rebuildError.value = ''
  const res: RebuildResult = { devices: 0, roundtrip_failed: 0, parse_failed: 0 }
  try {
    for (const [i, id] of ids.entries()) {
      rebuildMsg.value = `${i + 1}/${ids.length}`
      const r = await post<{ parsed?: boolean; roundtrip?: boolean }>(`/devices/${id}/rebuild`)
      res.devices++
      if (r.parsed === false) res.parse_failed++
      else if (r.roundtrip === false) res.roundtrip_failed++
      rebuildProgress.value = Math.round(((i + 1) * 100) / ids.length)
    }
    rebuildResult.value = res
    checked.value = new Set()
  } catch (e) {
    rebuildError.value = errorText(e)
  } finally {
    rebuilding.value = false
    await Promise.all([load(), status.refresh()])
  }
}

// ---- 删除设备（REQ-038）
const delId = ref<number | null>(null)
const delMsg = ref('')
function onDeleted(_r: unknown, msg: string): void {
  delId.value = null
  delMsg.value = msg
  void load()
  void status.refresh()
}

function onImported(): void {
  void load()
  void status.refresh()
}

// ---- 行尾菜单（REQ-035）：引用的改版本策略、复制为私有、解除引用；私有的重新解析、版本、复制到其他项目、删除
const menuFor = ref<number | null>(null)
const okMsg = ref('')
const actError = ref('')
const copyFor = ref<ProjectDevice | null>(null)
const unlinkFor = ref<ProjectDevice | null>(null)
const ACT_ICON: Record<RowAction, string> = { follow: 'refresh', pinLatest: 'pin', copyPrivate: 'copy', unlink: 'link', rebuild: 'refresh', history: 'history', copyTo: 'copy', delete: 'trash' }

async function act(d: ProjectDevice, a: RowAction): Promise<void> {
  menuFor.value = null
  actError.value = ''
  okMsg.value = ''
  try {
    if (a === 'history') { await router.push({ name: 'history', params: { id: d.id } }); return }
    if (a === 'copyTo') { copyFor.value = d; return }
    if (a === 'unlink') { unlinkFor.value = d; return }
    if (a === 'delete') { delId.value = d.id; return }
    if (a === 'follow') {
      await put(`/projects/${encodeURIComponent(project.ref ?? "")}/refs/${d.id}`, { version_id: null })
      okMsg.value = t('devices.nowFollow', { d: d.name })
    } else if (a === 'pinLatest') {
      const vid = d.public_latest_version_id ?? d.latest_version_id
      await put(`/projects/${encodeURIComponent(project.ref ?? "")}/refs/${d.id}`, { version_id: vid })
      okMsg.value = t('devices.nowPinned', { d: d.name, n: d.versions })
    } else if (a === 'copyPrivate') {
      const r = await post<{ name: string }>(`/projects/${encodeURIComponent(project.ref ?? "")}/devices/copy-in`, { device_id: d.id })
      okMsg.value = t('devices.copiedPrivate', { d: r.name })
    } else if (a === 'rebuild') {
      await post(`/devices/${d.id}/rebuild`)
      okMsg.value = t('devices.rebuiltOne', { d: d.name })
    }
    await Promise.all([load(), status.refresh()])
  } catch (e) {
    actError.value = errorText(e)
  }
}
async function pinAll(on: 'latest' | 'follow'): Promise<void> {
  actError.value = ''
  try {
    for (const d of newer.value) await put(`/projects/${encodeURIComponent(project.ref ?? "")}/refs/${d.id}`, { version_id: on === 'follow' ? null : d.public_latest_version_id })
    okMsg.value = t(on === 'follow' ? 'devices.allFollow' : 'devices.allPinned', { n: newer.value.length })
    await load()
  } catch (e) {
    actError.value = errorText(e)
  }
}
async function unlink(): Promise<void> {
  const d = unlinkFor.value
  if (!d) return
  unlinkFor.value = null
  try {
    await del(`/projects/${encodeURIComponent(project.ref ?? "")}/refs/${d.id}`)
    okMsg.value = t('devices.unlinked', { d: d.name })
    await Promise.all([load(), status.refresh()])
  } catch (e) {
    actError.value = errorText(e)
  }
}
function onCopied(msg: string): void {
  copyFor.value = null
  okMsg.value = msg
}
function onDoc(e: MouseEvent): void {
  if (menuFor.value !== null && !(e.target as HTMLElement).closest?.('.kebab')) menuFor.value = null
}
onMounted(() => document.addEventListener('click', onDoc))
onBeforeUnmount(() => document.removeEventListener('click', onDoc))
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.devices') }}</h1>
          <p class="ph-sub">{{ $t('devices.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button v-if="devices.length && canWrite" class="btn" :disabled="rebuilding" data-testid="rebuild-all" @click="rebuildAll()">
            <Icon name="refresh" small /><span>{{ $t('devices.rebuildAll', { v: kbVersion }) }}</span>
          </button>
          <button v-if="auth.isAdmin" class="btn" :disabled="rebuilding" :title="$t('devices.rebuildEverythingTip')" data-testid="rebuild-everything" @click="rebuildAll(true)">
            <Icon name="shield" small /><span>{{ $t('devices.rebuildEverything') }}</span>
          </button>
          <router-link v-if="canWrite" class="btn" :to="{ name: 'add-device' }" data-testid="add-device"><Icon name="plus" small /><span>{{ $t('nav.add-device') }}</span></router-link>
          <button v-if="canWrite" class="btn btn-primary" data-testid="open-import" @click="showImport = true">
            <Icon name="upload" small /><span>{{ $t('devices.import') }}</span>
          </button>
        </div>
      </div>

      <div v-if="rebuilding" class="notice info rebuild" data-testid="rebuild-progress">
        <Icon name="refresh" />
        <div class="grow">
          <div class="row"><b>{{ $t('devices.rebuilding', { v: kbVersion }) }}</b><span class="faint small ml-auto">{{ rebuildMsg }}</span></div>
          <div class="progress striped mt8"><i :style="{ width: Math.max(3, rebuildProgress) + '%' }" /></div>
        </div>
      </div>
      <div v-else-if="rebuildError" class="notice err rebuild"><Icon name="err" /><div class="grow">{{ rebuildError }}</div><button class="btn btn-xs" @click="rebuildError = ''">{{ $t('c.close') }}</button></div>
      <div v-else-if="rebuildResult" class="notice rebuild" :class="rebuildResult.roundtrip_failed || rebuildResult.parse_failed ? 'warn' : 'ok'" data-testid="rebuild-result">
        <Icon :name="rebuildResult.roundtrip_failed || rebuildResult.parse_failed ? 'warn' : 'ok'" />
        <div class="grow">{{ $t('devices.rebuildDone', { n: rebuildResult.devices, f: rebuildResult.roundtrip_failed, p: rebuildResult.parse_failed }) }}</div>
        <button class="btn btn-xs" @click="rebuildResult = null">{{ $t('c.close') }}</button>
      </div>
      <div v-else-if="staleCount" class="notice warn rebuild" data-testid="stale-notice">
        <Icon name="warn" />
        <div class="grow">{{ $t('devices.staleHint', { n: staleCount, v: kbVersion }) }}</div>
        <button v-if="canWrite" class="btn btn-sm" @click="rebuildAll()"><Icon name="refresh" small />{{ $t('devices.rebuildNow') }}</button>
      </div>

      <div v-if="newer.length" class="notice warn rebuild" data-testid="newer-notice">
        <Icon name="pin" />
        <div class="grow">{{ $t('devices.newerHint', { n: newer.length, d: newer.map((x) => x.name).join(', ') }) }}</div>
        <router-link v-if="newer.length === 1" class="btn btn-sm" :to="{ name: 'history', params: { id: newer[0].id } }">{{ $t('devices.newerCompare') }}</router-link>
        <template v-if="canWrite">
          <button class="btn btn-sm" type="button" data-testid="newer-pin" @click="pinAll('latest')"><Icon name="pin" small />{{ $t('devices.newerPin') }}</button>
          <button class="btn btn-sm" type="button" data-testid="newer-follow" @click="pinAll('follow')"><Icon name="refresh" small />{{ $t('devices.newerFollow') }}</button>
        </template>
      </div>
      <div v-if="okMsg" class="notice ok rebuild" data-testid="device-action-ok"><Icon name="ok" /><div class="grow">{{ okMsg }}</div><button class="btn btn-xs" @click="okMsg = ''">{{ $t('c.close') }}</button></div>
      <div v-if="actError" class="notice err rebuild" data-testid="device-action-error"><Icon name="err" /><div class="grow">{{ actError }}</div><button class="btn btn-xs" @click="actError = ''">{{ $t('c.close') }}</button></div>
      <div v-if="delMsg" class="notice ok rebuild" data-testid="device-deleted"><Icon name="ok" /><div class="grow">{{ delMsg }}</div><button class="btn btn-xs" @click="delMsg = ''">{{ $t('c.close') }}</button></div>

      <div v-if="loading && !devices.length" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>

      <div v-else-if="loadError" class="notice err" data-testid="load-error">
        <Icon name="err" /><div class="grow">{{ loadError }}</div>
        <button class="btn btn-sm" @click="load">{{ $t('c.retry') }}</button>
      </div>

      <section v-else-if="!devices.length" class="panel" data-testid="devices-empty">
        <div class="empty" style="padding: 64px 24px">
          <svg class="art" viewBox="0 0 120 84" aria-hidden="true"><rect x="22" y="18" width="76" height="20" rx="4" fill="none" stroke="var(--blue)" stroke-width="2" /><rect x="22" y="46" width="76" height="20" rx="4" fill="none" stroke="var(--line-strong)" stroke-width="2" stroke-dasharray="4 3" /><circle cx="32" cy="28" r="2.5" fill="var(--blue)" /></svg>
          <h3>{{ $t('devices.emptyTitle') }}</h3>
          <p>{{ $t('devices.emptyText') }}</p>
          <div v-if="canWrite" class="row mt8" style="justify-content: center; gap: 8px">
            <button class="btn btn-primary" @click="showImport = true"><Icon name="upload" small /><span>{{ $t('devices.import') }}</span></button>
            <router-link class="btn" :to="{ name: 'add-device' }"><Icon name="plus" small /><span>{{ $t('nav.add-device') }}</span></router-link>
          </div>
        </div>
      </section>

      <section v-else class="panel" data-testid="devices-panel">
        <div class="panel-h">
          <div class="toolbar" style="flex: 1">
            <div class="seg" role="group" :aria-label="$t('devices.colSource')" data-testid="filter-source">
              <button type="button" :aria-pressed="src === ''" @click="src = ''">{{ $t('c.all') }} {{ st.total }}</button>
              <button type="button" :aria-pressed="src === 'private'" data-v="private" @click="src = 'private'">{{ $t('proj.src.private') }} {{ st.private }}</button>
              <button type="button" :aria-pressed="src === 'public'" data-v="public" @click="src = 'public'">{{ $t('proj.src.public') }} {{ st.refs }}</button>
            </div>
            <label class="input-wrap"><Icon name="search" small /><input v-model="filter.q" class="input" type="search" :placeholder="$t('devices.searchPh')" data-testid="device-search"></label>
            <select v-model="filter.vendor" class="select" data-testid="filter-vendor">
              <option value="">{{ $t('devices.allVendors') }}</option>
              <option v-for="[v] in vendors" :key="v" :value="v">{{ v ? vendorLabel(v) : $t('devices.vendorUnknown') }}</option>
            </select>
            <select v-model="filter.state" class="select" data-testid="filter-state">
              <option value="">{{ $t('devices.allStates') }}</option>
              <option value="fail">{{ $t('devices.stFail') }}</option>
              <option value="stale">{{ $t('devices.stStale') }}</option>
              <option value="err">{{ $t('devices.stErr') }}</option>
              <option value="unknown">{{ $t('devices.stUnknown') }}</option>
            </select>
            <span class="grow" />
            <span class="faint small">{{ $t('devices.showing', { n: rows.length, t: devices.length }) }}</span>
            <button class="btn btn-ghost btn-icon btn-sm" :title="$t('c.refresh')" :aria-label="$t('c.refresh')" @click="load"><Icon name="refresh" small /></button>
          </div>
        </div>
        <div v-if="checked.size && canWrite" class="bulk" data-testid="bulk-bar">
          <span>{{ $t('devices.selected', { n: checked.size }) }}</span>
          <button class="btn btn-sm" :disabled="rebuilding" data-testid="rebuild-selected" @click="rebuildSelected"><Icon name="refresh" small /><span>{{ $t('devices.rebuildSelected', { v: kbVersion }) }}</span></button>
          <button class="btn btn-sm btn-ghost" @click="checked = new Set()">{{ $t('devices.clearSel') }}</button>
        </div>
        <div class="tbl-wrap" style="max-height: calc(100vh - 290px)">
          <table class="tbl dev-tbl" data-testid="devices-table">
            <thead>
              <tr>
                <th style="width: 30px"><input type="checkbox" class="ck" :checked="allChecked" :aria-label="$t('devices.selectAll')" @change="toggleAll(($event.target as HTMLInputElement).checked)"></th>
                <th>{{ $t('devices.colDevice') }}</th>
                <th>{{ $t('devices.colSource') }}</th>
                <th>{{ $t('devices.colVendor') }}</th>
                <th>Profile</th>
                <th class="num">{{ $t('devices.colLines') }}</th>
                <th class="num">{{ $t('devices.colUnknown') }}</th>
                <th>{{ $t('devices.colParse') }}</th>
                <th>{{ $t('devices.colRoundtrip') }}</th>
                <th>{{ $t('devices.colKb') }}</th>
                <th>{{ $t('devices.colImported') }}</th>
                <th style="width: 40px" :aria-label="$t('devdel.deleteDevice')" />
              </tr>
            </thead>
            <tbody>
              <tr v-if="!rows.length">
                <td colspan="12">
                  <div class="empty">
                    <h3>{{ $t('devices.noMatch') }}</h3>
                    <p>{{ $t('devices.noMatchHint') }}</p>
                    <button class="btn btn-sm" @click="clearFilters">{{ $t('devices.clearFilters') }}</button>
                  </div>
                </td>
              </tr>
              <tr v-for="d in rows" :key="d.id" :class="{ 'is-sel': checked.has(d.id) }">
                <td><input type="checkbox" class="ck" :checked="checked.has(d.id)" :aria-label="d.name" @change="toggle(d.id, ($event.target as HTMLInputElement).checked)"></td>
                <td class="nm nowrap">
                  <div class="nmrow">
                  <DeviceIcon v-bind="iconOf(d)" :size="24" />
                  <div class="nmcol">
                  <router-link class="trunc" style="display: block; max-width: 220px" :title="d.name" :to="{ name: 'device-graph', params: { id: d.id } }" data-testid="device-link">{{ d.name }}</router-link>
                  <div class="mono faint src" :title="d.source_name">{{ d.source_name }}<template v-if="d.parsed"> · <router-link :to="{ name: 'device-analysis', params: { id: d.id } }" :title="$t('nav.device-analysis')" data-testid="device-analysis-link">{{ $t('devices.analyze') }}</router-link> · <router-link class="aisum" :to="{ name: 'device-analysis', params: { id: d.id }, query: { ai: 'summary' } }" :title="$t('devices.summaryTip')" :data-testid="`dev-summary-${d.id}`">{{ $t('devices.summary') }}</router-link></template><template v-if="d.versions > 1"> · <router-link :to="{ name: 'history', params: { id: d.id } }" :title="$t('nav.history')" data-testid="device-history">{{ $t('devices.versions', { n: d.versions }) }}</router-link></template></div>
                  </div>
                  </div>
                </td>
                <td class="nowrap" :title="d.origin_note ?? undefined">
                  <ProjSource :source="d.source" :policy="d.policy" :seq="currentSeq(d)" :latest-seq="d.versions" :newer="d.newer_available" />
                </td>
                <td class="nowrap">
                  <VendorBadge v-if="d.vendor" :of="d.vendor">{{ vendorLabel(d.vendor) }}</VendorBadge>
                  <span v-else class="tag warn">{{ $t('devices.vendorUnknown') }}</span>
                </td>
                <td class="nowrap">
                  <div class="mono">{{ d.profile || '—' }}</div>
                  <div class="mono faint" style="font-size: 11px">{{ d.sw_version }}</div>
                </td>
                <td class="num">{{ d.lines?.toLocaleString() ?? '—' }}</td>
                <td class="num" :class="d.unknown ? 'unk' : 'faint'">{{ d.unknown ?? '—' }}</td>
                <td class="nowrap">
                  <span v-if="d.parsed" class="tag pass">{{ $t('devices.parsed') }}</span>
                  <span v-else-if="d.parsed === false" class="tag fail">{{ $t('devices.parseFailed') }}</span>
                  <span v-else class="faint">—</span>
                </td>
                <td class="nowrap">
                  <span v-if="d.parsed && d.roundtrip" class="tag pass"><Icon name="check" small />{{ $t('devices.rtPass') }}</span>
                  <span v-else-if="d.parsed && d.roundtrip === false" class="tag fail"><Icon name="x" small />{{ $t('devices.rtFail') }}</span>
                  <span v-else class="faint">—</span>
                </td>
                <td class="mono nowrap" :class="{ faint: !d.stale }">
                  {{ d.kb_version || '—' }}
                  <span v-if="d.stale" class="tag warn" style="font-family: var(--font-ui)" :title="$t('devices.staleTip', { v: kbVersion })">{{ $t('devices.old') }}</span>
                </td>
                <td class="nowrap faint" :title="fmtTime(d.collected_at, true)">{{ fmtTime(d.collected_at) }}</td>
                <td class="right nowrap">
                  <button v-if="canWrite && d.source !== 'public'" class="btn btn-ghost btn-icon btn-sm del-btn" type="button" :title="$t('devdel.deleteDevice')" :aria-label="`${$t('devdel.deleteDevice')} ${d.name}`" data-testid="device-delete" @click="delId = d.id"><Icon name="trash" small /></button>
                  <span class="kebab">
                    <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('devices.more', { d: d.name })" :aria-expanded="menuFor === d.id" data-testid="device-menu" @click.stop="menuFor = menuFor === d.id ? null : d.id"><Icon name="more" small /></button>
                    <span v-if="menuFor === d.id" class="kebab-pop" role="menu">
                      <button v-for="a in rowActions(d, canWrite)" :key="a" type="button" role="menuitem" :class="{ danger: a === 'delete' || a === 'unlink' }" :data-testid="`device-act-${a}`" @click="act(d, a)">
                        <Icon :name="ACT_ICON[a]" small />{{ $t(`devices.act.${a}`) }}
                      </button>
                    </span>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="tbl-foot">
          <span>
            {{ $t('devices.total', { n: devices.length }) }}<template v-for="[v, n] in vendors" :key="v">{{ $t('devices.sep') }}{{ v ? vendorLabel(v) : $t('devices.vendorUnknown') }} {{ n }}</template>
          </span>
          <span class="ml-auto">{{ $t('devices.keyNote') }}</span>
        </div>
      </section>
    </div>

    <ImportDialog v-if="showImport" @close="showImport = false" @imported="onImported" />
    <CopyToDialog v-if="copyFor" :device-id="copyFor.id" :device-name="copyFor.name" @close="copyFor = null" @done="onCopied" />
    <div v-if="unlinkFor" class="modal-back" data-testid="unlink-modal" @click.self="unlinkFor = null">
      <div class="modal" style="width: min(460px, 100%)" role="dialog" aria-modal="true" aria-labelledby="ulT">
        <div class="modal-h"><h2 id="ulT">{{ $t('devices.unlinkTitle', { d: unlinkFor.name }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="unlinkFor = null"><Icon name="x" /></button></div>
        <div class="modal-b"><p>{{ $t('devices.unlinkText') }}</p></div>
        <div class="modal-f">
          <button class="btn" type="button" @click="unlinkFor = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger-solid" type="button" data-testid="unlink-ok" @click="unlink"><Icon name="link" small />{{ $t('devices.act.unlink') }}</button>
        </div>
      </div>
    </div>
    <DevDelDialog v-if="delId !== null" :device-id="delId" @close="delId = null" @deleted="onDeleted" />
  </main>
</template>

<style scoped>
.rebuild { margin-bottom: 12px; align-items: center; }
.dev-tbl td.mono, .dev-tbl td.nowrap { white-space: nowrap; }
.dev-tbl .nm a { font-family: var(--font-mono); font-size: 12px; color: var(--ink); }
.dev-tbl .nm a:hover { color: var(--blue-ink); }
.dev-tbl .nm .src { font-size: 11px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.dev-tbl .nmrow { display: flex; gap: 8px; align-items: center; }
.dev-tbl .nmcol { min-width: 0; }
.dev-tbl .nm :deep(.devicon) { color: var(--ink-2); }
.dev-tbl .nm .aisum { color: var(--violet); }
.dev-tbl .unk { color: var(--red-ink); font-weight: 600; }
.ck { accent-color: var(--teal); }
.del-btn { color: var(--ink-3); }
.del-btn:hover { color: var(--red-ink); background: var(--red-soft); }
.tbl-foot { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border-top: 1px solid var(--line); color: var(--ink-3); font-size: 12px; flex-wrap: wrap; }
.bulk { display: flex; gap: 8px; align-items: center; padding: 8px 14px; background: var(--blue-soft); border-bottom: 1px solid var(--blue-line); font-size: 12.5px; }
</style>
