<script setup lang="ts">
/** 配置检查：按 DevelopDocs/ui-preview/M2/check.html。发现（筛选、列表、详情、忽略）、规则（开关与级别）、报告导出。 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import HiddenLegend from '@/components/hidden-legend.vue'
import { useTerms } from '@/stores/terms'
import { useProject } from '@/stores/project'
import { useAuth } from '@/stores/auth'
import { ApiError, del, errorText, get, post, put } from '@/api'
import type { Device } from './devices/logic'
import CheckTabs from './check/CheckTabs.vue'
import TargetBar from './check/TargetBar.vue'
import ExportDialog from './check/ExportDialog.vue'
import { target, targetBody } from './check/report'
import {
  cleanable, codeWindows, countBy, emptyFilter, findingKey, isComment, matches, nodeChips, orderWithCascade,
  renderText, ruleDesc, ruleSource, ruleTitle, severityCounts, sevIcon, sevOnly, splitLines, toggleIn, toggleSevOnly,
  type FindingFilter,
} from './check/logic'
import { SEVERITIES, type CheckResult, type Finding, type Rule, type Severity } from './check/types'

const { t, locale } = useI18n()
const project = useProject() // 只读成员不显示修改操作（REQ-036）
const terms = useTerms()
// 共享检查规则的开关与级别只限管理员与知识库维护员（REQ-036）；项目里的调整在项目设置
const auth = useAuth()
const route = useRoute()
const router = useRouter()
const lang = computed(() => String(locale.value))

const devices = ref<Device[]>([])
const devicesLoaded = ref(false)
const rules = ref<Rule[]>([])
const rulesError = ref('')
const result = ref<CheckResult | null>(null)
const lines = ref<string[]>([])
const kinds = ref(new Map<string, string>())
const origins = ref(new Map<string, string>())
const graphCounts = ref<{ objects: number; attrs: number } | null>(null)
const graphFor = ref<number | null>(null)
const loading = ref(false)
const failMsg = ref('')
const failIssues = ref<string[]>([])
const ranAt = ref('')
const tookMs = ref(0)
const filter = reactive<FindingFilter>(emptyFilter())
const selKey = ref('')
const ignoreOpen = ref(false)
const ignoreReason = ref('')
const ignoreErr = ref(false)
const busy = ref(false)
const exportOpen = ref(false)
const toast = ref<{ msg: string; err: boolean } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | undefined

const tab = computed<'findings' | 'rules'>(() => (route.hash === '#rules' ? 'rules' : 'findings'))
const rulesMap = computed(() => new Map(rules.value.map((r) => [r.id, r])))
const device = computed(() => devices.value.find((d) => d.id === target.deviceId) ?? null)
const deviceName = computed(() => result.value?.device || device.value?.name || null)
const findings = computed<Finding[]>(() => result.value?.findings ?? [])
const activeCount = computed(() => findings.value.filter((f) => !f.ignored).length)
const ignoredCount = computed(() => findings.value.length - activeCount.value)
const sevCounts = computed(() => severityCounts(findings.value))
const ruleCounts = computed(() => countBy(findings.value, (f) => f.rule))
const domainCounts = computed(() => countBy(findings.value, (f) => f.domain || '-'))
const rulesOn = computed(() => rules.value.filter((r) => r.enabled).length)
const rulesLabel = computed(() => (rules.value.length ? `${rulesOn.value} / ${rules.value.length}` : null))

function showToast(msg: string, err = false): void {
  toast.value = { msg, err }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = null), 2800)
}
onBeforeUnmount(() => clearTimeout(toastTimer))

const msgOf = (f: Finding) => renderText(f.message, lang.value, result.value?.texts ?? {}, rulesMap.value)
const sugOf = (f: Finding) => renderText(f.suggestion, lang.value, result.value?.texts ?? {}, rulesMap.value)
const titleOf = (rule: string) => ruleTitle(rule, lang.value, rulesMap.value)
const sevText = (s: Severity) => t(`check.sev${s[0].toUpperCase()}${s.slice(1)}`)

// ---------- 筛选项 ----------
const railRules = computed(() => {
  const ids = new Set([...rules.value.filter((r) => r.enabled).map((r) => r.id), ...Object.keys(ruleCounts.value), ...findings.value.map((f) => f.rule)])
  return [...ids].map((id) => ({ id, n: ruleCounts.value[id] ?? 0 })).sort((a, b) => b.n - a.n || a.id.localeCompare(b.id))
})
const railDomains = computed(() => {
  const ids = new Set([...Object.keys(domainCounts.value), ...findings.value.map((f) => f.domain || '-'), ...rules.value.map((r) => r.domain).filter((d): d is string => !!d)])
  return [...ids].map((id) => ({ id, n: domainCounts.value[id] ?? 0 })).sort((a, b) => a.id.localeCompare(b.id))
})

const visible = computed(() => findings.value.filter((f) => matches(f, filter, `${titleOf(f.rule)} ${msgOf(f)} ${f.nodes.map((n) => terms.describe(n)).join(' ')}`)))
const rows = computed(() => orderWithCascade(visible.value))
const selected = computed(() => rows.value.find((r) => r.key === selKey.value)?.f ?? rows.value[0]?.f ?? null)
watch(selected, () => { ignoreOpen.value = false; ignoreErr.value = false })

function resetFilter(): void { Object.assign(filter, emptyFilter()) }
function sevStrip(s: Severity | ''): void { filter.sev = toggleSevOnly(filter.sev, s) }
function onCheck(group: 'sev' | 'rules' | 'domains', v: string, e: Event): void {
  const on = (e.target as HTMLInputElement).checked
  if (group !== 'sev') { filter[group] = toggleIn(filter[group], v, on); return }
  // 严重度：空表示全部；全部勾上或全部取消都回到“全部”
  const next = toggleIn(filter.sev.length ? filter.sev : [...SEVERITIES], v as Severity, on)
  filter.sev = next.length === SEVERITIES.length ? [] : next
}
const sevChecked = (s: Severity) => !filter.sev.length || filter.sev.includes(s)
function onInline(group: 'sev' | 'rules' | 'domains', e: Event): void {
  const v = (e.target as HTMLSelectElement).value
  if (group === 'sev') filter.sev = v ? [v as Severity] : []
  else filter[group] = v ? [v] : []
}

// ---------- 加载与运行 ----------
async function loadDevices(): Promise<void> {
  try {
    devices.value = (await get<{ devices: Device[] }>('/devices')).devices
  } catch (e) {
    failMsg.value = errorText(e)
  } finally {
    devicesLoaded.value = true
  }
}
async function loadRules(): Promise<void> {
  rulesError.value = ''
  try {
    rules.value = (await get<{ rules: Rule[] }>('/kb/rules')).rules
    target.rulesOn = rulesOn.value
    target.rulesAll = rules.value.length
  } catch (e) {
    rulesError.value = errorText(e)
    if (e instanceof ApiError && Array.isArray((e.data as { issues?: unknown[] })?.issues)) failIssues.value = issuesText(e.data)
  }
}
function issuesText(data: unknown): string[] {
  const list = (data as { issues?: unknown[] })?.issues ?? []
  return list.map((x) => (typeof x === 'string' ? x : JSON.stringify(x)))
}

async function run(keepSel = false): Promise<void> {
  const body = targetBody()
  if (!body) return
  loading.value = true
  failMsg.value = ''
  failIssues.value = []
  const started = performance.now()
  try {
    const res = 'device_id' in body
      ? await get<CheckResult>(`/devices/${body.device_id}/check`)
      : await post<CheckResult>('/check', { text: body.text })
    tookMs.value = Math.round(performance.now() - started)
    ranAt.value = new Date().toLocaleTimeString(lang.value)
    // 依次请求原文与图（后端并发请求偶发失败，见 M1 报告）
    if ('device_id' in body) {
      if (graphFor.value !== body.device_id) {
        const g = await get<{ text?: string; nodes: { id: string; kind: string; origin?: string }[]; summary?: { kinds?: Record<string, number> } }>(`/devices/${body.device_id}/graph?raw=true`)
        lines.value = splitLines(g.text ?? '')
        kinds.value = new Map(g.nodes.map((n) => [n.id, n.kind]))
        origins.value = new Map(g.nodes.map((n) => [n.id, n.origin ?? 'explicit']))
        const k = g.summary?.kinds
        graphCounts.value = k ? { objects: k.object ?? 0, attrs: k.attr ?? 0 } : null
        graphFor.value = body.device_id
      }
    } else {
      lines.value = splitLines(body.text)
      kinds.value = new Map()
      origins.value = new Map()
      graphCounts.value = null
      graphFor.value = null
    }
    result.value = res
    target.findings = res.findings.filter((f) => !f.ignored).length
    if (!keepSel) selKey.value = ''
  } catch (e) {
    result.value = null
    failMsg.value = errorText(e)
    if (e instanceof ApiError) failIssues.value = issuesText(e.data)
  } finally {
    loading.value = false
  }
}

function onTargetChange(): void {
  result.value = null
  target.findings = null
  target.orphans = null
  failMsg.value = ''
  resetFilter()
  if (target.mode === 'device' && target.deviceId != null) {
    router.replace({ query: { ...route.query, device: String(target.deviceId) }, hash: route.hash })
    run()
  }
}

// ---------- 详情 ----------
const chips = computed(() => (selected.value ? nodeChips(selected.value, kinds.value, origins.value) : []))
const code = computed(() => (selected.value ? codeWindows(lines.value, selected.value.lines) : []))
const canIgnore = computed(() => target.mode === 'device' && target.deviceId != null)

async function confirmIgnore(): Promise<void> {
  const f = selected.value
  const why = ignoreReason.value.trim()
  if (!f || !why) { ignoreErr.value = true; return }
  busy.value = true
  try {
    await post('/check/ignores', { device_id: target.deviceId, rule: f.rule, node: f.node, reason: why })
    ignoreReason.value = ''
    ignoreOpen.value = false
    showToast(t('check.ignoredToast'))
    selKey.value = findingKey(f)
    await run(true)
  } catch (e) {
    showToast(errorText(e), true)
  } finally {
    busy.value = false
  }
}
async function unignore(): Promise<void> {
  const f = selected.value
  if (!f || f.ignore_id == null) return
  busy.value = true
  try {
    await del(`/check/ignores/${encodeURIComponent(String(f.ignore_id))}`)
    showToast(t('check.unignoredToast'))
    selKey.value = findingKey(f)
    await run(true)
  } catch (e) {
    showToast(errorText(e), true)
  } finally {
    busy.value = false
  }
}

// ---------- 规则 ----------
async function saveRule(r: Rule, patch: { enabled?: boolean; severity?: Severity }): Promise<void> {
  const before = { enabled: r.enabled, severity: r.severity }
  Object.assign(r, patch)
  try {
    const upd = await put<Rule | null>(`/kb/rules/${encodeURIComponent(r.id)}`, patch)
    if (upd && typeof upd === 'object' && 'id' in upd) Object.assign(r, upd)
    target.rulesOn = rulesOn.value
    const src = ruleSource(r)
    showToast(src === 'builtin' ? t('check.savedBuiltin') : t('check.savedFile', { file: src }))
  } catch (e) {
    Object.assign(r, before)
    showToast(errorText(e), true)
  }
}

onMounted(async () => {
  const q = Number(route.query.device)
  if (q > 0) { target.mode = 'device'; target.deviceId = q }
  await loadDevices()
  if (target.mode === 'device' && target.deviceId == null && devices.value.length) target.deviceId = devices.value[0].id
  await loadRules()
  if (targetBody() && (target.mode === 'device' || target.text.trim())) await run()
})
</script>

<template>
  <main class="main">
    <div class="page fill">
      <div class="crumbs"><span>{{ $t('grp.dev') }}</span><span class="sep">/</span><span>{{ $t('nav.check') }}</span></div>
      <div class="ck-head">
        <div class="ph-text">
          <h1>{{ $t('nav.check') }}</h1>
          <TargetBar :devices="devices" :profile="result?.profile ?? device?.profile" :kb-version="result?.kb_version" @change="onTargetChange" />
          <div v-if="result" class="ck-meta" data-testid="run-meta">
            <span>{{ $t('check.ranAt') }} <b>{{ ranAt }}</b></span>
            <span>{{ $t('check.took') }} <b>{{ tookMs }} ms</b></span>
            <span v-if="rulesLabel">{{ $t('check.rulesOn') }} <b>{{ rulesLabel }}</b></span>
            <span v-if="graphCounts">{{ $t('check.objects') }} <b>{{ graphCounts.objects }}</b> · {{ $t('check.attrs') }} <b>{{ graphCounts.attrs }}</b></span>
            <span v-if="ignoredCount">{{ $t('check.ignoredN') }} <b>{{ ignoredCount }}</b></span>
          </div>
        </div>
        <div class="ph-actions">
          <button class="btn" type="button" :disabled="!result" data-testid="btn-export" @click="exportOpen = true"><Icon name="report" small />{{ $t('check.export') }}</button>
          <button class="btn btn-primary" type="button" :disabled="loading || !targetBody()" data-testid="btn-run" @click="run()">
            <Icon :name="loading ? 'refresh' : 'play'" small />{{ $t('check.run') }}
          </button>
        </div>
      </div>

      <CheckTabs :active="tab" :findings="result ? activeCount : null" :rules="rulesLabel" :orphans="target.orphans" />

      <!-- 发现 -->
      <section v-if="tab === 'findings'" class="ck-body" data-testid="tab-findings-panel">
        <div v-if="failMsg" class="notice err" data-testid="check-error">
          <Icon name="err" />
          <div class="grow">
            <b>{{ $t('check.failTitle') }}</b>
            <p class="mt8">{{ failIssues.length ? $t('check.rulesInvalid', { n: failIssues.length }) : failMsg }}</p>
            <ul v-if="failIssues.length" class="issues mono small"><li v-for="(x, i) in failIssues" :key="i">{{ x }}</li></ul>
            <div class="row mt12"><button class="btn btn-sm" type="button" @click="run()"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div>
          </div>
        </div>

        <div v-else-if="devicesLoaded && target.mode === 'device' && !devices.length" class="panel full-empty">
          <div class="empty"><h3>{{ $t('check.noDevices') }}</h3>
            <router-link class="btn btn-sm btn-primary" :to="{ name: 'devices' }">{{ $t('check.goImport') }}</router-link></div>
        </div>

        <div v-else-if="!result && loading" class="panel full-empty"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>

        <div v-else-if="!result" class="panel full-empty" data-testid="check-start">
          <div class="empty"><Icon name="shield" /><h3>{{ $t('check.startTitle') }}</h3><p>{{ $t('check.startHint') }}</p>
            <button class="btn btn-sm btn-primary" type="button" :disabled="!targetBody()" @click="run()"><Icon name="play" small />{{ $t('check.run') }}</button></div>
        </div>

        <div v-else-if="!findings.length || (!activeCount && !filter.showIgnored)" class="panel full-empty" data-testid="check-clean">
          <div class="empty">
            <svg class="art" viewBox="0 0 120 84" aria-hidden="true"><path d="M60 8 30 20v20c0 18 12.8 31 30 36 17.2-5 30-18 30-36V20z" fill="var(--teal-soft)" stroke="var(--teal)" stroke-width="2" /><path d="m47 42 9 9 18-19" fill="none" stroke="var(--teal-ink)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /></svg>
            <h3>{{ $t('check.cleanTitle') }}</h3>
            <p>{{ $t('check.cleanBody', { n: rulesOn || result.rules_loaded, dev: deviceName || '—' }) }}</p>
            <p v-if="ignoredCount">{{ $t('check.allIgnoredBody') }}</p>
            <div class="row" style="justify-content: center">
              <label v-if="ignoredCount" class="check small"><input v-model="filter.showIgnored" type="checkbox" /><span>{{ $t('check.showIgnored') }}</span></label>
              <button class="btn btn-sm" type="button" @click="exportOpen = true"><Icon name="report" small />{{ $t('check.export') }}</button>
            </div>
          </div>
        </div>

        <template v-else>
          <div class="sevstrip" data-testid="sev-strip">
            <button type="button" class="total" :aria-pressed="!filter.sev.length" @click="sevStrip('')">
              <Icon name="shield" /><span><span class="n">{{ activeCount }}</span><br /><span class="k">{{ $t('check.sevAll') }}</span></span>
            </button>
            <button v-for="s in SEVERITIES" :key="s" type="button" :class="s" :aria-pressed="sevOnly(filter.sev) === s" :data-testid="`sev-${s}`" @click="sevStrip(s)">
              <Icon :name="sevIcon(s)" /><span><span class="n">{{ sevCounts[s] }}</span><br /><span class="k">{{ sevText(s) }}</span></span>
            </button>
          </div>
          <div class="ck-work">
            <aside class="panel rail" :aria-label="$t('c.filter')" data-testid="filter-rail">
              <div class="panel-h"><h3>{{ $t('c.filter') }}</h3><button class="btn btn-xs btn-ghost" type="button" @click="resetFilter">{{ $t('check.filterReset') }}</button></div>
              <div class="rail-b">
                <h4>{{ $t('check.fSeverity') }}</h4>
                <label v-for="s in SEVERITIES" :key="s" class="fopt" :class="{ zero: !sevCounts[s] }">
                  <input type="checkbox" :checked="sevChecked(s)" @change="onCheck('sev', s, $event)" />
                  <span class="lbl"><span class="sev" :class="s"><span class="sevdot" :class="s"></span>{{ sevText(s) }}</span></span><span class="c">{{ sevCounts[s] }}</span>
                </label>
                <h4>{{ $t('check.fRule') }}</h4>
                <label v-for="r in railRules" :key="r.id" class="fopt" :class="{ zero: !r.n }" :title="r.id">
                  <input type="checkbox" :checked="filter.rules.includes(r.id)" @change="onCheck('rules', r.id, $event)" />
                  <span class="lbl">{{ titleOf(r.id) }}</span><span class="c">{{ r.n }}</span>
                </label>
                <h4>{{ $t('check.fDomain') }}</h4>
                <label v-for="d in railDomains" :key="d.id" class="fopt" :class="{ zero: !d.n }">
                  <input type="checkbox" :checked="filter.domains.includes(d.id)" @change="onCheck('domains', d.id, $event)" />
                  <span class="lbl mono">{{ d.id }}</span><span class="c">{{ d.n }}</span>
                </label>
              </div>
            </aside>

            <section class="panel" aria-label="Findings">
              <div class="rail-inline" data-testid="filter-inline">
                <select class="select" :value="sevOnly(filter.sev)" :aria-label="$t('check.fSeverity')" @change="onInline('sev', $event)">
                  <option value="">{{ $t('check.allSev') }}</option>
                  <option v-for="s in SEVERITIES" :key="s" :value="s">{{ sevText(s) }}</option>
                </select>
                <select class="select" :value="filter.rules.length === 1 ? filter.rules[0] : ''" :aria-label="$t('check.fRule')" @change="onInline('rules', $event)">
                  <option value="">{{ $t('check.allRules') }}</option>
                  <option v-for="r in railRules" :key="r.id" :value="r.id">{{ titleOf(r.id) }} ({{ r.n }})</option>
                </select>
                <select class="select" :value="filter.domains.length === 1 ? filter.domains[0] : ''" :aria-label="$t('check.fDomain')" @change="onInline('domains', $event)">
                  <option value="">{{ $t('check.allDomains') }}</option>
                  <option v-for="d in railDomains" :key="d.id" :value="d.id">{{ d.id }} ({{ d.n }})</option>
                </select>
              </div>
              <div class="lbar">
                <label class="input-wrap"><Icon name="search" small /><input v-model="filter.q" class="input" type="search" :placeholder="$t('check.searchPh')" data-testid="finding-search" /></label>
                <label class="check small"><input v-model="filter.showIgnored" type="checkbox" data-testid="show-ignored" /><span>{{ $t('check.showIgnored') }}</span></label>
                <span class="meta">{{ rows.length }} / {{ findings.length }}</span>
              </div>
              <div class="flist" data-testid="finding-list">
                <div v-if="!rows.length" class="empty">
                  <Icon name="filter" /><h3>{{ $t('check.noMatch') }}</h3><p>{{ $t('check.noMatchHint') }}</p>
                  <button class="btn btn-sm" type="button" @click="resetFilter">{{ $t('check.resetFilters') }}</button>
                </div>
                <div
                  v-for="r in rows" :key="r.key" class="fi"
                  :class="{ 'is-sel': selected === r.f, cascade: r.depth > 0, 'is-ignored': r.f.ignored }"
                  :style="r.depth > 1 ? { paddingLeft: `${12 + 24 * r.depth}px` } : undefined"
                  tabindex="0" role="button" :aria-pressed="selected === r.f" data-testid="finding-row"
                  @click="selKey = r.key" @keydown.enter.space.prevent="selKey = r.key"
                >
                  <span class="si" :class="r.f.severity" :title="sevText(r.f.severity)"><Icon :name="sevIcon(r.f.severity)" /></span>
                  <div style="min-width: 0">
                    <div class="ft">{{ msgOf(r.f) }}</div>
                    <div class="fm">
                      <span class="tag mono" :title="titleOf(r.f.rule)">{{ r.f.rule }}</span>
                      <span v-if="r.cascade" class="tag t-violet">{{ $t('check.cascade') }}</span>
                      <span v-if="r.f.ignored" class="tag">{{ $t('check.ignored') }}</span>
                      <span>{{ r.f.domain }}</span>
                    </div>
                    <div class="fm"><span class="path" :title="`${$t('hid.canonical')}: ${r.f.node}`">{{ terms.describe(r.f.node) }}</span></div>
                  </div>
                </div>
              </div>
            </section>

            <aside class="panel" aria-label="Finding details" data-testid="finding-detail">
              <div class="panel-h"><h3>{{ $t('check.detailTitle') }}</h3></div>
              <div v-if="!selected" class="d-scroll"><div class="empty"><p>{{ $t('check.selectHint') }}</p></div></div>
              <template v-else>
                <div class="d-scroll">
                  <div class="d-sev">
                    <span class="sev" :class="selected.severity"><Icon :name="sevIcon(selected.severity)" />{{ sevText(selected.severity) }}</span>
                    <span class="tag mono">{{ selected.rule }}</span>
                    <span v-if="selected.rule === 'ref.orphan_cascade'" class="tag t-violet">{{ $t('check.cascade') }}</span>
                  </div>
                  <div class="d-title">{{ titleOf(selected.rule) }}</div>
                  <p class="d-msg">{{ msgOf(selected) }}</p>
                  <div v-if="selected.ignored" class="notice mt12"><Icon name="eyeOff" /><div class="grow small"><b>{{ $t('check.ignored') }}</b>：{{ selected.ignore_reason }}</div></div>

                  <div class="section-t mt16 nodes-h">{{ $t('check.nodes') }}<HiddenLegend v-if="chips.some((c) => c.origin)" /></div>
                  <div class="nchips" data-testid="detail-nodes">
                    <div v-for="c in chips" :key="c.id" class="nchip" :class="[{ missing: c.kind === 'missing' }, c.origin === 'default' ? 'hid-default' : c.origin === 'derived' ? 'hid-derived' : '']" :title="`${$t('hid.canonical')}: ${c.id}`">
                      <span class="nk">{{ $t(`check.kind${c.kind[0].toUpperCase()}${c.kind.slice(1)}`) }}</span>
                      <span class="nl">{{ terms.describe(c.id) }}<span v-if="terms.describe(c.id) !== c.id" class="canon">{{ c.id }}</span></span>
                      <span v-if="c.kind === 'missing'" class="tag t-red">{{ $t('check.kindMissing') }}</span>
                      <span v-if="c.origin === 'default' || c.origin === 'derived'" class="tag" :class="c.origin">{{ $t(`hid.${c.origin}`) }}</span>
                    </div>
                  </div>

                  <div class="section-t">{{ $t('check.configLines') }}</div>
                  <div v-if="code.length" class="d-code" data-testid="detail-lines">
                    <div class="src"><span class="mono">{{ deviceName || '—' }}</span><span>{{ $t('check.linesAt', { list: selected.lines.join(', ') }) }}</span></div>
                    <div class="code">
                      <template v-for="(row, i) in code" :key="i">
                        <div v-if="row.type === 'gap'" class="gap">⋯ {{ row.n }} {{ $t('c.lines') }}</div>
                        <div v-else class="l" :class="{ 'is-hl': row.hl, 'c-cmt': isComment(row.text) }"><span class="n">{{ row.no }}</span><span class="g"></span><span class="t">{{ row.text }}</span></div>
                      </template>
                    </div>
                  </div>
                  <p v-else class="small faint">{{ $t('check.noLines') }}</p>

                  <div class="section-t">{{ $t('check.fix') }}</div>
                  <div class="fixbox"><p>{{ sugOf(selected) }}</p><p class="small faint mt8">{{ $t('check.fixNote') }}</p></div>
                </div>

                <div v-if="ignoreOpen" class="ignore-box" data-testid="ignore-box">
                  <label class="field-label" for="ckIgnReason">{{ $t('check.ignoreReason') }}</label>
                  <textarea id="ckIgnReason" v-model="ignoreReason" class="textarea" :class="{ 'is-error': ignoreErr && !ignoreReason.trim() }" rows="2" :placeholder="$t('check.ignorePh')" data-testid="ignore-reason" />
                  <p v-if="ignoreErr && !ignoreReason.trim()" class="small err-text">{{ $t('check.reasonRequired') }}</p>
                  <div class="row">
                    <button class="btn btn-sm btn-primary" type="button" :disabled="busy || !ignoreReason.trim()" data-testid="ignore-ok" @click="confirmIgnore">{{ $t('check.ignoreOk') }}</button>
                    <button class="btn btn-sm btn-ghost" type="button" @click="ignoreOpen = false">{{ $t('c.cancel') }}</button>
                  </div>
                </div>
                <div class="d-actions">
                  <router-link v-if="target.mode === 'device' && target.deviceId != null" class="btn btn-sm" data-testid="open-graph"
                    :to="{ name: 'device-graph', params: { id: String(target.deviceId) }, query: { node: selected.node } }">
                    <Icon name="graph" small />{{ $t('check.openGraph') }}
                  </router-link>
                  <router-link v-if="cleanable(selected)" class="btn btn-sm btn-blue" :to="{ name: 'cleanup' }" data-testid="go-cleanup"><Icon name="broom" small />{{ $t('check.goCleanup') }}</router-link>
                  <template v-if="canIgnore">
                    <button v-if="selected.ignored && project.canWrite" class="btn btn-sm btn-ghost ml-auto" type="button" :disabled="busy" data-testid="btn-unignore" @click="unignore">{{ $t('check.unignore') }}</button>
                    <button v-else-if="!ignoreOpen && project.canWrite" class="btn btn-sm btn-ghost ml-auto" type="button" data-testid="btn-ignore" @click="ignoreOpen = true"><Icon name="eyeOff" small />{{ $t('check.ignore') }}</button>
                  </template>
                  <span v-else class="small faint ml-auto">{{ $t('check.ignoreTextMode') }}</span>
                </div>
              </template>
            </aside>
          </div>
        </template>
      </section>

      <!-- 规则 -->
      <section v-else class="ck-rules" data-testid="tab-rules-panel">
        <div class="notice info rules-note"><Icon name="info" /><div class="grow">{{ $t('check.rulesNote') }}</div></div>
        <div v-if="!auth.isKbEditor" class="ro-ribbon rules-note" data-testid="rules-ro"><Icon name="lock" small /><div class="grow">{{ $t('kbsugg.kbEditorOnly') }}</div></div>
        <div v-if="rulesError" class="notice err rules-note">
          <Icon name="err" /><div class="grow">{{ rulesError }}
            <ul v-if="failIssues.length" class="issues mono small"><li v-for="(x, i) in failIssues" :key="i">{{ x }}</li></ul>
            <div class="row mt8"><button class="btn btn-sm" type="button" @click="loadRules"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div></div>
        </div>
        <div class="panel">
          <div class="tbl-wrap">
            <table class="tbl rules" data-testid="rules-table">
              <thead><tr>
                <th>{{ $t('check.colOn') }}</th><th>{{ $t('check.colRule') }}</th><th>{{ $t('check.colName') }}</th><th>{{ $t('check.colDomain') }}</th>
                <th>{{ $t('check.colSeverity') }}</th><th>{{ $t('check.colSource') }}</th><th v-if="result" class="num">{{ $t('check.colHits') }}</th><th>{{ $t('check.colDesc') }}</th>
              </tr></thead>
              <tbody>
                <tr v-for="r in rules" :key="r.id" :class="{ off: !r.enabled }" data-testid="rule-row">
                  <td><label class="switch"><input type="checkbox" :checked="r.enabled" :aria-label="titleOf(r.id)" :disabled="!auth.isKbEditor" :data-testid="`rule-on-${r.id}`" @change="saveRule(r, { enabled: ($event.target as HTMLInputElement).checked })" /><span></span></label></td>
                  <td class="mono nowrap">{{ r.id }}</td>
                  <td>{{ titleOf(r.id) }}</td>
                  <td class="mono">{{ r.domain || $t('check.allDomainsShort') }}</td>
                  <td>
                    <select class="select" :value="r.severity" :aria-label="$t('check.colSeverity')" :disabled="!auth.isKbEditor" @change="saveRule(r, { severity: ($event.target as HTMLSelectElement).value as Severity })">
                      <option v-for="s in SEVERITIES" :key="s" :value="s">{{ sevText(s) }}</option>
                    </select>
                  </td>
                  <td><span v-if="ruleSource(r) === 'builtin'" class="tag">{{ $t('check.builtin') }}</span><span v-else class="tag t-teal mono">{{ ruleSource(r) }}</span></td>
                  <td v-if="result" class="num" :class="{ hits0: !ruleCounts[r.id] }">{{ r.enabled ? (ruleCounts[r.id] ?? 0) : '—' }}</td>
                  <td class="desc">{{ ruleDesc(r, lang) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    <ExportDialog v-if="exportOpen" :device="deviceName" @close="exportOpen = false" @toast="showToast" />
    <div v-if="toast" class="toast" role="status" data-testid="check-toast"><Icon :name="toast.err ? 'err' : 'ok'" small />{{ toast.msg }}</div>
  </main>
</template>

<style scoped>
.ck-head { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
.ck-head .ph-text { flex: 1; min-width: 300px; }
.ck-meta { display: flex; gap: 14px; color: var(--ink-3); font-size: 12px; flex-wrap: wrap; margin-top: 6px; }
.ck-meta b { color: var(--ink-2); font-weight: 600; }
.ck-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.ck-rules { flex: 1; min-height: 0; overflow: auto; }
.issues { margin: 6px 0 0 18px; }
.err-text { color: var(--red-ink); }

.sevstrip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-bottom: 10px; }
.sevstrip button { border: 0; background: transparent; font: inherit; color: inherit; text-align: left; padding: 9px 14px; border-left: 1px solid var(--line); cursor: pointer; display: flex; align-items: center; gap: 10px; min-width: 0; }
.sevstrip button:first-child { border-left: 0; }
.sevstrip button:hover { background: var(--surface-2); }
.sevstrip button[aria-pressed="true"] { box-shadow: inset 0 -2px 0 var(--sel-ring); background: var(--surface-2); }
.sevstrip .n { font: 600 20px/1.2 var(--font-display); }
.sevstrip .k { font-size: 12px; color: var(--ink-2); }
.sevstrip :deep(.ico) { width: 18px; height: 18px; flex: none; }
.sevstrip .error :deep(.ico), .sevstrip .error .n { color: var(--red-ink); }
.sevstrip .warning :deep(.ico), .sevstrip .warning .n { color: var(--amber-ink); }
.sevstrip .info :deep(.ico), .sevstrip .info .n { color: var(--blue-ink); }
.sevstrip .total :deep(.ico) { color: var(--ink-3); }
@media (max-width: 640px) { .sevstrip { grid-template-columns: repeat(2, minmax(0, 1fr)); } .sevstrip button:nth-child(3) { border-left: 0; } .sevstrip button:nth-child(n+3) { border-top: 1px solid var(--line); } }

.ck-work { flex: 1; min-height: 0; display: grid; gap: 10px; grid-template-columns: 220px minmax(0, 1fr) 420px; }
@media (max-width: 1400px) { .ck-work { grid-template-columns: 200px minmax(0, 1fr) 360px; } }
@media (max-width: 1100px) { .ck-work { grid-template-columns: minmax(0, 1fr) 320px; } .rail { display: none !important; } .rail-inline { display: flex !important; } }
@media (max-width: 760px) { .ck-work { grid-template-columns: minmax(0, 1fr); } .ck-work > .panel { min-height: 320px; } }
.ck-work > .panel { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.rail-b { overflow: auto; padding: 10px 12px 14px; }
.rail h4 { font-size: 12px; color: var(--ink-2); font-weight: 600; margin: 12px 0 6px; }
.rail h4:first-child { margin-top: 2px; }
.fopt { display: flex; align-items: center; gap: 7px; padding: 3px 4px; border-radius: 4px; cursor: pointer; font-size: 12.5px; }
.fopt:hover { background: var(--surface-2); }
.fopt input { accent-color: var(--teal); margin: 0; }
.fopt .lbl { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fopt .lbl.mono { font: 11.5px var(--font-mono); }
.fopt .c { color: var(--ink-3); font-size: 11.5px; }
.fopt.zero { opacity: .55; }
.rail-inline { display: none; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.rail-inline .select { width: auto; max-width: 100%; height: 26px; font-size: 12px; }

.lbar { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.lbar .input-wrap { flex: 1; max-width: 300px; min-width: 140px; }
.lbar .input { height: 28px; }
.lbar .meta { margin-left: auto; color: var(--ink-3); font-size: 12px; white-space: nowrap; }
.flist { overflow: auto; flex: 1; }
.fi { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 8px; padding: 9px 12px; border-bottom: 1px solid var(--line); cursor: pointer; position: relative; }
.fi:hover { background: var(--surface-2); }
.fi:focus-visible { outline: 2px solid var(--sel-ring); outline-offset: -2px; }
.fi.is-sel { background: var(--blue-soft); }
.fi.is-sel::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--sel-ring); }
.fi.cascade { padding-left: 36px; }
.fi.cascade::after { content: ""; position: absolute; left: 20px; top: 0; height: 50%; width: 10px; border-left: 1px solid var(--line-strong); border-bottom: 1px solid var(--line-strong); border-bottom-left-radius: 4px; }
.fi.is-ignored { opacity: .55; }
.fi .si { padding-top: 1px; }
.fi .si :deep(.ico) { width: 17px; height: 17px; }
.fi .si.error { color: var(--red-ink); } .fi .si.warning { color: var(--amber-ink); } .fi .si.info { color: var(--blue-ink); }
.fi .ft { font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; }
.fi .fm { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 4px; font-size: 12px; color: var(--ink-3); }
.fi .fm .path { font: 11.5px var(--font-mono); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }

.d-scroll { flex: 1; overflow: auto; padding: 14px; }
.d-sev { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.d-title { font: 600 14.5px/1.45 var(--font-display); margin: 8px 0 6px; }
.d-msg { color: var(--ink-2); overflow-wrap: anywhere; }
.nchips { display: flex; flex-direction: column; gap: 5px; }
.nchip { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface-2); min-width: 0; }
.nchip .nk { font-size: 11px; color: var(--ink-3); min-width: 32px; }
.nchip .nl { font: 12px var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.nchip .nl .canon { display: block; overflow: hidden; text-overflow: ellipsis; }
.nchip.hid-default, .nchip.hid-derived { border-color: transparent; background: transparent; outline-offset: 0; }
.nodes-h { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.nchip.missing { border-style: dashed; border-color: var(--red-line); background: transparent; }
.nchip.missing .nl { color: var(--red-ink); text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--red) 50%, transparent); }
.d-code { border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.d-code .code { max-height: 260px; }
.d-code .gap { font: 11px var(--font-mono); color: var(--ink-3); padding: 1px 0 1px 64px; background: var(--surface-2); border-top: 1px dashed var(--line); border-bottom: 1px dashed var(--line); }
.d-code .src { display: flex; justify-content: space-between; gap: 8px; padding: 5px 10px; font-size: 11.5px; color: var(--ink-3); background: var(--surface-2); border-bottom: 1px solid var(--line); }
.fixbox { border: 1px solid var(--teal-line); border-radius: 6px; background: color-mix(in srgb, var(--teal-soft) 55%, transparent); padding: 10px 12px; }
.fixbox p { color: var(--ink); overflow-wrap: anywhere; }
.d-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 10px 14px; border-top: 1px solid var(--line); }
.ignore-box { padding: 10px 14px; border-top: 1px solid var(--line); background: var(--surface-2); display: flex; flex-direction: column; gap: 8px; }

.rules-note { margin-bottom: 10px; }
.rules .switch { vertical-align: middle; }
.rules td.desc { color: var(--ink-2); font-size: 12px; min-width: 260px; }
.rules .select { height: 26px; width: auto; font-size: 12px; }
.rules tr.off td:not(:first-child) { opacity: .5; }
.rules .hits0 { color: var(--ink-3); }
.full-empty { flex: 1; display: flex; align-items: center; justify-content: center; min-height: 260px; }
</style>
