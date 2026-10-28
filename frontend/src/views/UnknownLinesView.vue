<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import AiOffHint from '@/components/ai-off-hint.vue'
import { errorText, get, post } from '@/api'
import { useStatus } from '@/stores/status'
import type { Device } from './devices/logic'
import {
  filterPatterns, patKey, patternParts, patternsToSend, stateOf, views,
  type PatFilter, type PatState, type UnknownPattern,
} from './unknown-lines/logic'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import UnknownTriage from '@/components/ai-kb/UnknownTriage.vue'
import TriageChip from '@/components/ai-kb/TriageChip.vue'
import type { TriageMark } from '@/components/ai-kb/logic'

// M8-5 未识别行归因（AI）：右侧面板与表格的“AI 归因”列
const triage = ref<InstanceType<typeof UnknownTriage> | null>(null)
const aiOpen = ref(false)
const aiState = ref('loading')
const marks = ref<Record<string, TriageMark>>({})
const triagePatterns = computed(() => [...new Set(patterns.value.filter((p) => checked.value.has(patKey(p))).map((p) => p.pattern))])
async function runTriage(): Promise<void> {
  aiOpen.value = true
  await triage.value?.start()
}

const status = useStatus()
const { t } = useI18n()
const PAGE = 200
const MAX = 1000 // 接口 limit 上限

const patterns = ref<UnknownPattern[]>([])
const states = ref<Record<string, string>>({})
const devices = ref<Device[]>([])
const limit = ref(PAGE)
const loading = ref(true)
const loadError = ref('')
const filter = reactive<PatFilter>({ q: '', view: '', state: '' })
const checked = ref<Set<string>>(new Set())
const selKey = ref('')
const sending = ref(false)
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    // 依次请求：后端每个请求都会跑一次数据库迁移检查，并发时偶发 500（见报告）
    const p = await get<{ patterns: UnknownPattern[] }>(`/unknown-lines?limit=${limit.value}`)
    const s = await get<{ states: Record<string, string> }>('/unknown-lines/states')
    // 设备列表只用于“含未识别行的设备”计数，取不到时不影响本页
    const d = await get<{ devices: Device[] }>('/devices').catch(() => ({ devices: devices.value }))
    patterns.value = p.patterns
    states.value = s.states
    devices.value = d.devices
    if (!patterns.value.some((x) => patKey(x) === selKey.value)) selKey.value = patterns.value[0] ? patKey(patterns.value[0]) : ''
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function loadMore(): Promise<void> {
  limit.value = Math.min(MAX, limit.value + PAGE)
  await load()
}

const rows = computed(() => filterPatterns(patterns.value, states.value, filter))
const viewList = computed(() => views(patterns.value))
const maxCount = computed(() => Math.max(1, ...patterns.value.map((p) => p.count)))
const selected = computed(() => patterns.value.find((p) => patKey(p) === selKey.value) ?? null)
const totalPatterns = computed(() => status.summary?.unknown.patterns ?? patterns.value.length)
const totalHits = computed(() => status.summary?.unknown.total ?? patterns.value.reduce((a, p) => a + p.count, 0))
const devsWithUnknown = computed(() => devices.value.filter((d) => (d.unknown ?? 0) > 0).length)
const pendingCount = computed(() => Object.values(states.value).filter((s) => s === 'pending').length)
const canLoadMore = computed(() => patterns.value.length >= limit.value && limit.value < MAX)
const aiConfigured = computed(() => !!status.summary?.ai.configured)
const allChecked = computed(() => rows.value.length > 0 && rows.value.every((p) => checked.value.has(patKey(p))))
const toSend = computed(() => patternsToSend(patterns.value, checked.value, states.value))

function toggle(p: UnknownPattern, on: boolean): void {
  const s = new Set(checked.value)
  if (on) s.add(patKey(p))
  else s.delete(patKey(p))
  checked.value = s
}
function toggleAll(on: boolean): void {
  const s = new Set(checked.value)
  for (const p of rows.value) {
    if (on) s.add(patKey(p))
    else s.delete(patKey(p))
  }
  checked.value = s
}

function showToast(msg: string): void {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3500)
}

const sendError = ref('')
async function send(list: string[]): Promise<void> {
  if (!list.length) return
  sending.value = true
  sendError.value = ''
  try {
    const r = await post<{ added: number; skipped: string[]; ids: number[] }>('/unknown-lines/review', { patterns: list })
    showToast(r.skipped.length ? t('unknown-lines.sentSkipped', { n: r.added, s: r.skipped.length }) : t('unknown-lines.sent', { n: r.added }))
    checked.value = new Set()
    states.value = (await get<{ states: Record<string, string> }>('/unknown-lines/states')).states
    void status.refresh()
  } catch (e) {
    sendError.value = errorText(e)
  } finally {
    sending.value = false
  }
}

function stateClass(s: PatState): string {
  return s === 'pending' ? 'pending' : s === 'approved' ? 'approved' : s === 'rejected' ? 'rejected' : ''
}

</script>

<template>
  <main class="main">
    <div class="page fill">
      <div class="ph" style="margin-bottom: 10px">
        <div class="ph-text">
          <h1>{{ $t('unknown-lines.title') }}</h1>
          <p class="ph-sub">{{ $t('unknown-lines.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" :disabled="loading" data-testid="refresh" @click="load"><Icon name="refresh" small /><span>{{ $t('c.refresh') }}</span></button>
        </div>
      </div>

      <div v-if="loading && !patterns.length" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>

      <div v-else-if="loadError" class="notice err" data-testid="load-error">
        <Icon name="err" /><div class="grow">{{ loadError }}</div>
        <button class="btn btn-sm" @click="load">{{ $t('c.retry') }}</button>
      </div>

      <section v-else-if="!patterns.length" class="panel" data-testid="unknown-empty">
        <div class="empty" style="padding: 56px 24px">
          <Icon name="ok" />
          <h3>{{ $t('unknown-lines.emptyTitle') }}</h3>
          <p>{{ devices.length ? $t('unknown-lines.emptyText', { n: devices.length }) : $t('unknown-lines.emptyNoDevices') }}</p>
          <router-link v-if="!devices.length" class="btn btn-primary" :to="{ name: 'devices', query: { import: '1' } }"><Icon name="upload" small />{{ $t('unknown-lines.importConfigs') }}</router-link>
        </div>
      </section>

      <template v-else>
        <div class="sumrow" data-testid="unknown-summary">
          <div><div class="v">{{ totalPatterns.toLocaleString() }}</div><div class="k">{{ $t('unknown-lines.sumPatterns') }}</div></div>
          <div><div class="v">{{ totalHits.toLocaleString() }}</div><div class="k">{{ $t('unknown-lines.sumHits') }}</div></div>
          <div><div class="v">{{ devsWithUnknown }} / {{ devices.length }}</div><div class="k">{{ $t('unknown-lines.sumConfigs') }}</div></div>
          <div><div class="v">{{ pendingCount }}</div><div class="k">{{ $t('unknown-lines.sumPending') }}</div></div>
        </div>

        <div class="toolbar" style="margin-bottom: 10px">
          <label class="input-wrap"><Icon name="search" small /><input v-model="filter.q" class="input" type="search" :placeholder="$t('unknown-lines.searchPh')" data-testid="unknown-search"></label>
          <select v-model="filter.view" class="select" data-testid="filter-view">
            <option value="">{{ $t('unknown-lines.allViews') }}</option>
            <option v-for="v in viewList" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filter.state" class="select" data-testid="filter-state">
            <option value="">{{ $t('unknown-lines.allStates') }}</option>
            <option value="new">{{ $t('unknown-lines.stNew') }}</option>
            <option value="pending">{{ $t('unknown-lines.stPending') }}</option>
            <option value="approved">{{ $t('unknown-lines.stApproved') }}</option>
            <option value="rejected">{{ $t('unknown-lines.stRejected') }}</option>
          </select>
          <span class="grow" />
          <span v-if="checked.size" class="small faint">{{ $t('unknown-lines.selected', { n: checked.size }) }}</span>
          <AiEntryButton :skills="['unknown-triage']" :busy="aiState === 'running'" small @run="runTriage" />
          <button class="btn btn-sm" :disabled="!toSend.length || sending" data-testid="batch-send" @click="send(toSend)">
            <Icon name="inbox" small /><span>{{ $t('unknown-lines.batchSend') }}</span>
          </button>
        </div>
        <div v-if="sendError" class="notice err" style="margin-bottom: 10px"><Icon name="err" /><div class="grow">{{ sendError }}</div></div>

        <div class="ul">
          <section class="panel ul-list">
            <div class="tbl-wrap">
              <table class="tbl" data-testid="unknown-table">
                <thead>
                  <tr>
                    <th style="width: 30px"><input type="checkbox" :checked="allChecked" :aria-label="$t('unknown-lines.selectAll')" @change="toggleAll(($event.target as HTMLInputElement).checked)"></th>
                    <th>{{ $t('unknown-lines.colPattern') }}</th>
                    <th class="col-view">{{ $t('unknown-lines.colView') }}</th>
                    <th class="right">{{ $t('unknown-lines.colCount') }}</th>
                    <th>{{ $t('unknown-lines.colState') }}</th>
                    <th data-testid="col-ai-triage">{{ $t('kb-ai.ut.col') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!rows.length"><td colspan="6"><div class="empty"><p>{{ $t('unknown-lines.noMatch') }}</p></div></td></tr>
                  <tr
                    v-for="p in rows" :key="patKey(p)" class="ul-row" :class="{ 'row-sel': patKey(p) === selKey }"
                    data-testid="unknown-row" @click="selKey = patKey(p)"
                  >
                    <td @click.stop><input type="checkbox" :checked="checked.has(patKey(p))" :aria-label="p.pattern" @change="toggle(p, ($event.target as HTMLInputElement).checked)"></td>
                    <td><span class="pat" :title="p.example"><template v-for="(part, i) in patternParts(p.pattern)" :key="i"><span v-if="part.ph" class="p">{{ part.text }}</span><template v-else>{{ part.text }}</template></template></span></td>
                    <td class="mono col-view"><span class="trunc" style="display: inline-block; max-width: 220px; vertical-align: bottom" :title="p.view">{{ p.view || '—' }}</span></td>
                    <td><div class="freq"><span class="b"><i :style="{ width: Math.max(4, Math.round((p.count / maxCount) * 100)) + '%' }" /></span><b>{{ p.count.toLocaleString() }}</b></div></td>
                    <td><span class="tag" :class="stateClass(stateOf(states, p.pattern))">{{ $t('unknown-lines.st_' + stateOf(states, p.pattern)) }}</span></td>
                    <td @click.stop="marks[p.pattern] && (aiOpen = true)"><TriageChip :mark="marks[p.pattern]" /></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="panel-f small faint">
              <span>{{ $t('unknown-lines.shown', { n: rows.length, t: totalPatterns }) }}</span>
              <span style="flex: 1" />
              <button v-if="canLoadMore" class="btn btn-xs" :disabled="loading" data-testid="load-more" @click="loadMore">{{ $t('unknown-lines.loadMore') }}</button>
            </div>
          </section>

          <UnknownTriage v-show="aiOpen" ref="triage" :patterns="triagePatterns" @marks="marks = $event" @state="aiState = $event" @close="aiOpen = false" />
          <aside v-show="!aiOpen" class="panel ul-detail" data-testid="unknown-detail">
            <div class="panel-h"><h3>{{ $t('unknown-lines.detail') }}</h3></div>
            <div v-if="!selected" class="body"><div class="empty"><p>{{ $t('unknown-lines.pickOne') }}</p></div></div>
            <template v-else>
              <div class="body">
                <div class="bigpat">{{ selected.example }}</div>
                <dl class="kv mt12">
                  <dt>{{ $t('unknown-lines.normalized') }}</dt>
                  <dd><span class="pat" style="max-width: none; white-space: pre-wrap"><template v-for="(part, i) in patternParts(selected.pattern)" :key="i"><span v-if="part.ph" class="p">{{ part.text }}</span><template v-else>{{ part.text }}</template></template></span></dd>
                  <dt>{{ $t('unknown-lines.view') }}</dt>
                  <dd class="mono">{{ selected.view || '—' }}</dd>
                  <dt>{{ $t('unknown-lines.occurrences') }}</dt>
                  <dd>{{ $t('unknown-lines.occN', { n: selected.count.toLocaleString() }) }}</dd>
                  <dt>{{ $t('unknown-lines.colState') }}</dt>
                  <dd>
                    <span class="tag" :class="stateClass(stateOf(states, selected.pattern))">{{ $t('unknown-lines.st_' + stateOf(states, selected.pattern)) }}</span>
                    <router-link v-if="stateOf(states, selected.pattern) !== 'new'" class="small" style="margin-left: 8px" :to="{ name: 'review', query: { kind: 'unknown_line' } }">{{ $t('unknown-lines.openReview') }}</router-link>
                  </dd>
                </dl>

                <div class="section-t" style="margin-top: 16px">{{ $t('unknown-lines.mapping') }}</div>
                <div class="cand">
                  <div class="h"><Icon name="inbox" small />{{ $t('unknown-lines.howTitle') }}</div>
                  <div class="why" style="margin-top: 0">{{ $t('unknown-lines.howText') }}</div>
                  <div class="row mt8">
                    <router-link class="btn btn-sm" :to="{ name: 'schema-edit' }">{{ $t('unknown-lines.toSchema') }}</router-link>
                    <router-link class="btn btn-sm" :to="{ name: 'ingest' }">{{ $t('unknown-lines.toIngest') }}</router-link>
                  </div>
                </div>
                <AiOffHint v-if="!aiConfigured" compact data-testid="ai-off"><div class="small muted">{{ $t('unknown-lines.aiOff') }}</div></AiOffHint>
                <div v-else class="ai-off" data-testid="ai-on">
                  <Icon name="spark" small />
                  <span>{{ $t('unknown-lines.aiOn') }}</span>
                </div>
              </div>
              <div class="panel-f">
                <template v-if="stateOf(states, selected.pattern) === 'pending'">
                  <span class="small faint" style="flex: 1">{{ $t('unknown-lines.inQueue') }}</span>
                  <router-link class="btn btn-sm" :to="{ name: 'review', query: { kind: 'unknown_line' } }">{{ $t('unknown-lines.goReview') }}</router-link>
                </template>
                <template v-else>
                  <span class="small faint" style="flex: 1">{{ stateOf(states, selected.pattern) === 'new' ? '' : $t('unknown-lines.resend') }}</span>
                  <button class="btn btn-sm btn-primary" :disabled="sending" data-testid="send-one" @click="send([selected.pattern])"><Icon name="inbox" small />{{ $t('unknown-lines.send') }}</button>
                </template>
              </div>
            </template>
          </aside>
        </div>
      </template>
    </div>
    <div v-if="toast" class="toast" role="status"><Icon name="check" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
.ul { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 420px; gap: 12px; }
@media (max-width: 1300px) { .ul { grid-template-columns: minmax(0, 1fr) 360px; } .pat { max-width: 300px; } .freq .b { display: none; } }
@media (max-width: 1100px) { .ul { grid-template-columns: minmax(0, 1fr) 320px; } .pat { max-width: 230px; } .col-view { display: none; } }
.tbl td.mono { white-space: nowrap; }
.ul-list, .ul-detail { display: flex; flex-direction: column; overflow: hidden; }
.ul-list .tbl-wrap { flex: 1; }
.ul-detail .body { flex: 1; overflow: auto; padding: 14px; }
.pat { font: 12px var(--font-mono); white-space: pre; overflow: hidden; text-overflow: ellipsis; max-width: 420px; display: block; }
.pat .p { color: var(--teal-ink); background: var(--teal-soft); border-radius: 3px; padding: 0 2px; }
.freq { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
.freq .b { width: 64px; height: 5px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
.freq .b i { display: block; height: 100%; background: var(--red); opacity: .75; }
.row-sel td { background: var(--blue-soft) !important; }
tr.ul-row { cursor: pointer; }
.tbl input[type=checkbox] { accent-color: var(--teal); }
.sumrow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-bottom: 12px; }
.sumrow > div { padding: 9px 14px; border-left: 1px solid var(--line); }
.sumrow > div:first-child { border-left: 0; }
.sumrow .v { font: 600 17px var(--font-display); }
.sumrow .k { font-size: 12px; color: var(--ink-2); }
.cand { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: var(--surface); }
.cand .h { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 8px; }
.cand .why { font-size: 12px; color: var(--ink-2); margin-top: 6px; }
.ai-off { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; color: var(--ink-3); padding: 8px 2px; }
.bigpat { font: 13px var(--font-mono); padding: 9px 11px; border-radius: 6px; background: var(--red-soft); border: 1px solid var(--red-line); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink); }
/* 详情面板较窄：字段名列不压缩、取值列可换行，长行不在右侧被截断（REQ-055-11） */
.ul-detail .kv { grid-template-columns: minmax(72px, max-content) minmax(0, 1fr); }
.ul-detail .kv dt { white-space: nowrap; }
.empty > .ico { width: 32px; height: 32px; color: var(--teal-ink); }
</style>
