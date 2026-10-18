<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { errorText, get, post, waitTask } from '@/api'
import { useStatus } from '@/stores/status'
import ImportDialog from './devices/ImportDialog.vue'
import { filterDevices, fmtTime, vendorCounts, vendorLabel, type DevFilter, type Device } from './devices/logic'

const route = useRoute()
const router = useRouter()
const status = useStatus()

const devices = ref<Device[]>([])
const kbVersion = ref('')
const loading = ref(true)
const loadError = ref('')
const filter = reactive<DevFilter>({ q: '', vendor: '', state: '' })
const checked = ref<Set<number>>(new Set())
const showImport = ref(false)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const d = await get<{ devices: Device[]; kb_version: string }>('/devices')
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

const rows = computed(() => filterDevices(devices.value, filter))
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

async function rebuildAll(): Promise<void> {
  rebuilding.value = true
  rebuildProgress.value = 0
  rebuildMsg.value = ''
  rebuildResult.value = null
  rebuildError.value = ''
  try {
    const { task_id } = await post<{ task_id: string }>('/devices/rebuild')
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

function onImported(): void {
  void load()
  void status.refresh()
}
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
          <button v-if="devices.length" class="btn" :disabled="rebuilding" data-testid="rebuild-all" @click="rebuildAll">
            <Icon name="refresh" small /><span>{{ $t('devices.rebuildAll', { v: kbVersion }) }}</span>
          </button>
          <button class="btn btn-primary" data-testid="open-import" @click="showImport = true">
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
        <button class="btn btn-sm" @click="rebuildAll"><Icon name="refresh" small />{{ $t('devices.rebuildNow') }}</button>
      </div>

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
          <button class="btn btn-primary mt8" @click="showImport = true"><Icon name="upload" small /><span>{{ $t('devices.import') }}</span></button>
        </div>
      </section>

      <section v-else class="panel" data-testid="devices-panel">
        <div class="panel-h">
          <div class="toolbar" style="flex: 1">
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
        <div v-if="checked.size" class="bulk" data-testid="bulk-bar">
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
                <th>{{ $t('devices.colVendor') }}</th>
                <th>Profile</th>
                <th class="num">{{ $t('devices.colLines') }}</th>
                <th class="num">{{ $t('devices.colUnknown') }}</th>
                <th>{{ $t('devices.colParse') }}</th>
                <th>{{ $t('devices.colRoundtrip') }}</th>
                <th>{{ $t('devices.colKb') }}</th>
                <th>{{ $t('devices.colImported') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!rows.length">
                <td colspan="10">
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
                  <router-link class="trunc" style="display: block; max-width: 220px" :title="d.name" :to="{ name: 'device-graph', params: { id: d.id } }" data-testid="device-link">{{ d.name }}</router-link>
                  <div class="mono faint src" :title="d.source_name">{{ d.source_name }}<template v-if="d.versions > 1"> · {{ $t('devices.versions', { n: d.versions }) }}</template></div>
                </td>
                <td class="nowrap">
                  <span v-if="d.vendor" class="vendor"><i :class="d.vendor === 'huawei' ? 'hw' : d.vendor === 'cisco' ? 'cs' : ''">{{ d.vendor === 'huawei' ? 'HW' : d.vendor === 'cisco' ? 'CS' : '?' }}</i>{{ vendorLabel(d.vendor) }}</span>
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
  </main>
</template>

<style scoped>
.rebuild { margin-bottom: 12px; align-items: center; }
.dev-tbl td.mono, .dev-tbl td.nowrap { white-space: nowrap; }
.dev-tbl .nm a { font-family: var(--font-mono); font-size: 12px; color: var(--ink); }
.dev-tbl .nm a:hover { color: var(--blue-ink); }
.dev-tbl .nm .src { font-size: 11px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.dev-tbl .unk { color: var(--red-ink); font-weight: 600; }
.ck { accent-color: var(--teal); }
.tbl-foot { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border-top: 1px solid var(--line); color: var(--ink-3); font-size: 12px; flex-wrap: wrap; }
.bulk { display: flex; gap: 8px; align-items: center; padding: 8px 14px; background: var(--blue-soft); border-bottom: 1px solid var(--blue-line); font-size: 12.5px; }
</style>
