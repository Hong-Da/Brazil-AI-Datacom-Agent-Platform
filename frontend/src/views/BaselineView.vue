<script setup lang="ts">
/**
 * 安全基线审计（预览 DevelopDocs/ui-preview/M4/baseline.html）：选基线（basic / strict）与设备（多台）→ POST /baseline →
 * 概况、设备 × 规则矩阵（得分）、设备的不符合项（证据行、按平台族写好的参考命令）、规则定义、报告（中 / 英，HTML / MD）与矩阵 CSV。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import ReportAiSummary from '@/components/ai-kb/ReportAiSummary.vue'
import WaiverDialog from '@/components/ai-kb/WaiverDialog.vue'
import { errorText, get, post } from '@/api'
import { pickLang } from '@/i18n'
import { useTerms } from '@/stores/terms'
import { postFile, saveBlob } from '@/views/check/report'
import { saveText, toCsv } from '@/views/profiles/csv'
import type { Device } from '@/views/devices/logic'
import { keyText } from './m4/texts'
import { lines as splitLines, snippet, stamp } from './m4/common'
import {
  cellOf, failuresByRule, matrixCsv, REMEDY_KEYS, remedyText, scoreBand, stripCounts,
  type BaselineResult, type DeviceResult, type Rule, type RulesInfo,
} from './m4/baseline'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()

const devices = ref<Device[]>([])
const info = ref<RulesInfo | null>(null)
const loadError = ref('')
const baseline = ref(String(route.query.baseline ?? 'basic'))
const picked = ref<Set<number>>(new Set())
const pickOpen = ref(false)
const allPicked = computed(() => devices.value.length > 0 && picked.value.size === devices.value.length)
const setLabel = computed(() => (allPicked.value ? t('baseline.allDevices', { n: devices.value.length }) : t('baseline.someDevices', { n: picked.value.size, total: devices.value.length })))
function toggle(id: number): void {
  const s = new Set(picked.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  picked.value = s
}

// ---------------------------------------------------------------- 审计
const running = ref(false)
const runError = ref('')
const result = ref<BaselineResult | null>(null)
const ranAt = ref('')
let lastBody: Record<string, unknown> | null = null
/** M8-5 报告摘要与例外说明用的范围（最近一次审计的基线与设备）；导出时是否包含 AI 摘要。 */
const aiBody = ref<{ baseline: string; device_ids: number[] } | null>(null)
const incAi = ref(true)
const waiver = ref<{ deviceId: number; deviceName: string; rule: string; baseline: string } | null>(null)
function openWaiver(device: string, rule: string): void {
  const d = devOf(device)
  if (d) waiver.value = { deviceId: d.id, deviceName: d.name, rule, baseline: aiBody.value?.baseline ?? baseline.value }
}

async function run(): Promise<void> {
  if (!picked.value.size || running.value) return
  running.value = true
  runError.value = ''
  const body = { baseline: baseline.value, device_ids: [...picked.value] }
  try {
    result.value = await post<BaselineResult>('/baseline', body)
    lastBody = body
    aiBody.value = body
    ranAt.value = new Date().toLocaleString()
    const keep = mode.value === 'dev' && result.value.devices.some((d) => d.device === selDev.value)
    if (!keep) {
      const worst = [...result.value.devices].sort((a, b) => a.score - b.score)[0]
      selDev.value = worst?.device ?? null
      mode.value = 'dev'
    }
    cell.value = null
    const q: Record<string, string> = { baseline: baseline.value }
    if (!allPicked.value) q.devices = [...picked.value].join(',')
    void router.replace({ query: q })
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}
watch(baseline, () => { if (result.value) void run() })

const rules = computed(() => {
  const r = result.value
  if (!r) return [] as Rule[]
  const by = new Map(r.rules.map((x) => [x.id, x]))
  return r.matrix.rules.map((id) => by.get(id)).filter((x): x is Rule => !!x)
})
const ruleById = computed(() => new Map((result.value?.rules ?? info.value?.rules ?? []).map((x) => [x.id, x])))
const title = (id: string) => pickLang(ruleById.value.get(id)?.title, lang.value) || id
const strip = computed(() => (result.value ? stripCounts(result.value) : null))
const devRes = (name: string) => result.value?.devices.find((d) => d.device === name) ?? null
const devOf = (name: string) => devices.value.find((d) => d.name === name) ?? null
const sevIcon = (s: string) => (s === 'error' ? 'err' : s === 'warning' ? 'warn' : 'info')
const SYM = { pass: '✓', fail: '✕', na: '–' }
const ringLen = 2 * Math.PI * 23

// ---------------------------------------------------------------- 详情
const mode = ref<'dev' | 'rule'>('dev')
const selDev = ref<string | null>(null)
const selRule = ref<string | null>(null)
const cell = ref<string | null>(null)
const dr = computed<DeviceResult | null>(() => (selDev.value ? devRes(selDev.value) : null))
const groups = computed(() => (dr.value ? failuresByRule(dr.value, result.value?.matrix.rules ?? []) : []))
const texts = ref<Record<string, string[]>>({})
async function loadText(name: string | null): Promise<void> {
  const d = name ? devOf(name) : null
  if (!d || !d.latest_version_id || texts.value[d.name]) return
  try {
    const r = await get<{ text: string }>(`/devices/${d.id}/versions/${d.latest_version_id}/text`)
    texts.value = { ...texts.value, [d.name]: splitLines(r.text) }
  } catch { /* 证据只显示行号 */ }
}
watch(selDev, (n) => { void loadText(n) })
const evidence = (lines: number[]) => (selDev.value && texts.value[selDev.value] ? snippet(texts.value[selDev.value], lines, 0) : [])
const remedyAll = computed(() => (dr.value ? remedyText(dr.value, title) : ''))
const ruleInfo = computed(() => (selRule.value ? ruleById.value.get(selRule.value) ?? null : null))

function pickDev(name: string): void {
  mode.value = 'dev'
  selDev.value = name
  cell.value = null
}
function pickRule(id: string): void {
  mode.value = 'rule'
  selRule.value = id
}
function pickCell(rule: string, dev: string): void {
  mode.value = 'dev'
  selDev.value = dev
  cell.value = `${dev}|${rule}`
  setTimeout(() => document.getElementById(`bl-it-${rule}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 80)
}

// ---------------------------------------------------------------- 导出
const toast = ref('')
let toastTimer = 0
function flash(s: string): void {
  toast.value = s
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2400)
}
function copyText(s: string): void {
  const done = () => flash(t('c.copied'))
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(done, done)
  else done()
}
const reportFmt = ref<'html' | 'md'>('html')
const reporting = ref('')
async function report(rl: 'zh-CN' | 'en'): Promise<void> {
  if (!lastBody) return
  reporting.value = rl
  try {
    const f = await postFile('/baseline/report', { ...lastBody, lang: rl, format: reportFmt.value, style: terms.style, include_ai_summary: incAi.value }, `baseline-${baseline.value}.${rl}.${reportFmt.value}`)
    saveBlob(f.blob, f.name)
  } catch (e) {
    flash(t('baseline.reportFail', { e: errorText(e) }))
  } finally {
    reporting.value = ''
  }
}
function exportCsv(): void {
  if (result.value) saveText(`baseline-${baseline.value}-matrix-${stamp()}.csv`, toCsv(matrixCsv(result.value, title)))
}

onMounted(async () => {
  try {
    const [d, r] = await Promise.all([get<{ devices: Device[] }>('/devices'), get<RulesInfo>('/baseline/rules')])
    devices.value = [...d.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    info.value = r
  } catch (e) {
    loadError.value = errorText(e)
  }
  const one = String(route.query.device ?? '')
  const want = (one || String(route.query.devices ?? '')).split(',').filter((x) => /^\d+$/.test(x)).map(Number)
  picked.value = new Set(want.length ? want.filter((id) => devices.value.some((d) => d.id === id)) : devices.value.map((d) => d.id))
  if (picked.value.size) void run()
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.ana') }}</span><span class="sep">/</span><span>{{ $t('nav.baseline') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('baseline.title') }}</h1>
          <p class="ph-sub">{{ $t('baseline.sub') }}</p>
        </div>
        <div class="ph-actions dlrow">
          <div class="seg" role="group" :aria-label="$t('baseline.reportFmt')">
            <button type="button" :aria-pressed="reportFmt === 'html'" @click="reportFmt = 'html'">HTML</button>
            <button type="button" :aria-pressed="reportFmt === 'md'" @click="reportFmt = 'md'">Markdown</button>
          </div>
          <button class="btn btn-sm" type="button" :disabled="!result || !!reporting" data-testid="bl-report-zh" @click="report('zh-CN')"><Icon name="download" small />{{ $t('baseline.reportZh') }}</button>
          <button class="btn btn-sm" type="button" :disabled="!result || !!reporting" data-testid="bl-report-en" @click="report('en')"><Icon name="download" small />{{ $t('baseline.reportEn') }}</button>
          <button class="btn btn-sm" type="button" :disabled="!result" data-testid="bl-csv" @click="exportCsv"><Icon name="matrix" small />{{ $t('baseline.matrixCsv') }}</button>
        </div>
      </div>
      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div></div>

      <div class="ctl" data-testid="bl-ctl">
        <div class="field">
          <label class="field-label" for="bl-base">{{ $t('baseline.baseline') }}</label>
          <select id="bl-base" v-model="baseline" class="select" data-testid="bl-baseline">
            <option v-for="p in info?.profiles ?? []" :key="p.id" :value="p.id">{{ pickLang(p.title, lang) }}（{{ $t('baseline.rulesN', { n: p.rules ?? 0 }) }}）</option>
          </select>
        </div>
        <div class="field">
          <span class="field-label">{{ $t('baseline.devices') }}</span>
          <div class="pickwrap">
            <button class="btn" type="button" data-testid="bl-pick" @click="pickOpen = !pickOpen"><Icon name="server" small />{{ setLabel }}<Icon :name="pickOpen ? 'chevD' : 'chevR'" small /></button>
            <div v-if="pickOpen" class="pickpop">
              <div class="row" style="gap: 8px"><button class="link-btn" type="button" @click="picked = new Set(devices.map((d) => d.id))">{{ $t('baseline.pickAll') }}</button><button class="link-btn" type="button" @click="picked = new Set()">{{ $t('baseline.pickNone') }}</button></div>
              <label v-for="d in devices" :key="d.id" class="check"><input type="checkbox" :checked="picked.has(d.id)" @change="toggle(d.id)"><DevChip :name="d.name" :vendor="d.vendor" /></label>
            </div>
          </div>
        </div>
        <button class="btn btn-primary" type="button" :disabled="!picked.size || running" data-testid="bl-run" @click="pickOpen = false; run()"><Icon name="refresh" small />{{ running ? $t('baseline.running') : result ? $t('baseline.rerun') : $t('baseline.run') }}</button>
        <span v-if="ranAt" class="when"><Icon name="clock" small />{{ $t('baseline.when', { t: ranAt }) }}</span>
      </div>
      <p v-if="result" class="small muted" style="margin: -4px 0 12px">{{ pickLang(result.baseline_info.description, lang) }}</p>

      <div v-if="runError" class="notice err" data-testid="bl-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
      <div v-if="!result && !runError" class="empty mt16"><Icon name="shield" /><h3>{{ running ? $t('c.loading') : $t('baseline.emptyTitle') }}</h3><p v-if="!running">{{ $t('baseline.emptyText') }}</p></div>

      <template v-if="result && strip">
        <div class="strip bstrip" data-testid="bl-strip">
          <div><div class="k">{{ $t('baseline.s.score') }}</div><div class="v" :class="`sc-${scoreBand(result.summary.score)}`">{{ result.summary.score }}</div><div class="s">{{ $t('baseline.s.scoreHint') }}</div></div>
          <div><div class="k"><Icon name="err" small />{{ $t('baseline.s.fail') }}</div><div class="v" style="color: var(--red-ink)">{{ result.summary.failures }}</div><div class="s">{{ $t('baseline.s.failHint') }}</div></div>
          <div><div class="k"><Icon name="check" small />{{ $t('baseline.s.pass') }}</div><div class="v">{{ result.summary.pass }}<small>/ {{ result.summary.pass + result.summary.fail }}</small></div><div class="s">{{ $t('baseline.s.passHint', { n: result.summary.na }) }}</div></div>
          <div><div class="k"><Icon name="server" small />{{ $t('baseline.s.affected') }}</div><div class="v">{{ strip.affected }}<small>/ {{ result.devices.length }}</small></div><div class="s">{{ $t('baseline.s.affectedHint') }}</div></div>
          <div><div class="k">{{ $t('baseline.s.bySev') }}</div><div class="sevrow"><span v-for="s in (['error', 'warning', 'info'] as const)" :key="s" class="sev" :class="s"><Icon :name="sevIcon(s)" small />{{ $t(`baseline.sev.${s}`) }}<b>{{ strip.bySev[s] }}</b></span></div></div>
        </div>
        <ReportAiSummary v-model="incAi" kind="baseline" :params="aiBody" style="margin-bottom: 12px" />

        <div class="bl">
          <section class="panel">
            <div class="panel-h"><h2>{{ $t('baseline.matrix') }}</h2><span class="meta">{{ $t('baseline.matrixHint') }}</span></div>
            <div class="mxwrap">
              <table class="mxt" data-testid="bl-matrix">
                <thead><tr>
                  <th class="rh">{{ $t('baseline.rule') }}</th>
                  <th v-for="d in result.matrix.devices" :key="d" class="colh" :class="{ 'is-col': mode === 'dev' && selDev === d }" tabindex="0" data-testid="bl-col" @click="pickDev(d)" @keydown.enter="pickDev(d)">
                    <DevChip :name="d" :vendor="devRes(d)?.family" /><span class="sc" :class="scoreBand(devRes(d)?.score ?? 100)">{{ devRes(d)?.score ?? '—' }}</span>
                  </th>
                </tr></thead>
                <tbody>
                  <tr v-for="r in rules" :key="r.id" :class="{ 'is-row': mode === 'rule' && selRule === r.id }">
                    <th tabindex="0" data-testid="bl-rule" @click="pickRule(r.id)" @keydown.enter="pickRule(r.id)">
                      <div><span class="rname">{{ pickLang(r.title, lang) }}</span></div>
                      <div class="rmeta"><span class="sev" :class="r.severity"><Icon :name="sevIcon(r.severity)" small />{{ $t(`baseline.sev.${r.severity}`) }}</span><span class="rid">{{ r.id }}</span><span>{{ $t('baseline.passN', { ok: result.summary.by_rule[r.id]?.pass ?? 0, app: (result.summary.by_rule[r.id]?.pass ?? 0) + (result.summary.by_rule[r.id]?.fail ?? 0) }) }}</span></div>
                    </th>
                    <td v-for="d in result.matrix.devices" :key="d" :class="{ 'is-col': mode === 'dev' && selDev === d, cur: cell === `${d}|${r.id}` }" @click="pickCell(r.id, d)">
                      <span class="mx" :class="cellOf(result, r.id, d)" :title="$t(`baseline.c.${cellOf(result, r.id, d)}`)" :data-testid="`bl-cell-${cellOf(result, r.id, d)}`">{{ SYM[cellOf(result, r.id, d)] }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="mxleg">
              <span><span class="mx pass">✓</span>{{ $t('baseline.c.pass') }}</span>
              <span><span class="mx fail">✕</span>{{ $t('baseline.c.fail') }}</span>
              <span><span class="mx na">–</span>{{ $t('baseline.c.na') }}</span>
            </div>
          </section>

          <section class="panel det" data-testid="bl-detail">
            <!-- 规则 -->
            <template v-if="mode === 'rule' && ruleInfo">
              <div class="panel-h"><h2>{{ pickLang(ruleInfo.title, lang) }}</h2><button class="btn btn-xs btn-ghost" type="button" @click="mode = 'dev'"><Icon name="chevL" small />{{ $t('baseline.backDev') }}</button></div>
              <div class="rdef">
                <div class="row wrap" style="gap: 8px 14px"><span class="sev" :class="ruleInfo.severity"><Icon :name="sevIcon(ruleInfo.severity)" small />{{ $t(`baseline.sev.${ruleInfo.severity}`) }}</span><code class="small">{{ ruleInfo.id }}</code><span v-for="tg in ruleInfo.tags" :key="tg" class="tag">{{ tg }}</span></div>
                <div class="cond"><h4>{{ $t('baseline.whatFails') }}</h4><p>{{ pickLang(ruleInfo.message, lang) }}</p></div>
                <div class="cond"><h4>{{ $t('baseline.suggestion') }}</h4><p>{{ pickLang(ruleInfo.suggestion, lang) }}</p></div>
                <template v-for="rk in REMEDY_KEYS" :key="rk.key">
                  <div v-if="ruleInfo.remedy[rk.key]?.length" class="cond" :data-testid="`bl-remedy-${rk.key}`"><h4><DevChip :name="$t(rk.label)" :vendor="rk.key" /></h4><pre class="block">{{ ruleInfo.remedy[rk.key]!.join('\n') }}</pre></div>
                </template>
                <dl class="kv"><dt>{{ $t('baseline.ruleSource') }}</dt><dd class="mono">knowledge/rules/{{ ruleInfo.source }}#{{ ruleInfo.id }}</dd><dt>{{ $t('baseline.inBaselines') }}</dt><dd>{{ ruleInfo.profiles.join(', ') }}</dd></dl>
                <div>
                  <div class="sec-k">{{ $t('baseline.perDevice') }}</div>
                  <div class="per">
                    <div v-for="d in result.matrix.devices" :key="d" @click="pickCell(ruleInfo!.id, d)">
                      <span class="mx" :class="cellOf(result, ruleInfo.id, d)">{{ SYM[cellOf(result, ruleInfo.id, d)] }}</span><DevChip :name="d" :vendor="devRes(d)?.family" />
                      <span class="why">{{ devRes(d)?.failures.filter((f) => f.rule === ruleInfo!.id).map((f) => keyText(f.message, lang, result!.texts)).join('；') }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            <!-- 设备 -->
            <template v-else-if="dr">
              <div class="panel-h"><h2><DevChip :name="dr.device" :vendor="dr.family" /></h2><span class="meta">{{ dr.profile }}</span></div>
              <div class="score">
                <svg class="ring" viewBox="0 0 54 54" aria-hidden="true"><circle class="bg" cx="27" cy="27" r="23" /><circle class="fg" :class="scoreBand(dr.score)" cx="27" cy="27" r="23" :stroke-dasharray="`${(ringLen * dr.score / 100).toFixed(1)} ${ringLen.toFixed(1)}`" /><text x="27" y="27">{{ dr.score }}</text></svg>
                <div class="meta"><span><b>{{ dr.summary.pass }} / {{ dr.summary.pass + dr.summary.fail }}</b> {{ $t('baseline.rulesPass') }}</span><span>{{ $t('baseline.s.passHint', { n: dr.summary.na }) }}</span></div>
                <router-link v-if="devOf(dr.device)" class="btn btn-xs ml-auto" :to="{ name: 'device-graph', params: { id: String(devOf(dr.device)!.id) } }"><Icon name="graph" small />{{ $t('baseline.toGraph') }}</router-link>
              </div>
              <div v-if="!groups.length" class="okall"><Icon name="ok" /><p>{{ $t('baseline.okAll') }}</p></div>
              <div v-else class="items">
                <div v-for="g in groups" :id="`bl-it-${g.rule}`" :key="g.rule" class="it" :class="[`k-${g.items[0].severity === 'error' ? 'fail' : 'warn'}`, { cur: cell === `${dr.device}|${g.rule}` }]" data-testid="bl-failure">
                  <div class="ih"><span class="nm">{{ title(g.rule) }}</span><span class="sev" :class="g.items[0].severity"><Icon :name="sevIcon(g.items[0].severity)" small />{{ $t(`baseline.sev.${g.items[0].severity}`) }}</span><span class="rid">{{ g.rule }}</span><span v-if="g.items.length > 1" class="small faint">{{ $t('baseline.instances', { n: g.items.length }) }}</span><button v-if="devOf(dr.device)" class="btn btn-xs btn-aio ml-auto" type="button" :data-testid="`baseline-waiver-open-${g.rule}`" @click="openWaiver(dr.device, g.rule)"><Icon name="spark" small />{{ $t('ai-kb.bw.open') }}</button></div>
                  <div v-for="(f, k) in g.items" :key="k" class="inst">
                    <div class="risk-t">{{ keyText(f.message, lang, result.texts) }}</div>
                    <div class="small muted">{{ keyText(f.suggestion, lang, result.texts) }}</div>
                    <div v-if="f.lines.length" class="code">
                      <template v-for="(x, i) in evidence(f.lines)" :key="i">
                        <div v-if="x" class="l is-hl"><span class="n">{{ x.no }}</span><span class="g" /><span class="t">{{ x.text }}</span></div>
                      </template>
                      <div v-if="!evidence(f.lines).length" class="l"><span class="n">·</span><span class="g" /><span class="t">{{ f.lines.map((n) => $t('baseline.lineN', { n })).join('，') }}</span></div>
                    </div>
                    <p v-else class="small faint mt8">{{ $t('baseline.noEvidence') }}</p>
                    <div v-if="f.evidence.length" class="chips"><code v-for="e in f.evidence" :key="e" :title="e">{{ terms.describe(e) }}</code></div>
                    <div v-if="f.remedy.length" class="act">
                      <pre class="block">{{ f.remedy.join('\n') }}</pre>
                      <button class="btn btn-xs" type="button" @click="copyText(f.remedy.join('\n'))"><Icon name="copy" small />{{ $t('baseline.copyOne') }}</button>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="remedyAll" class="fixwrap">
                <h3><Icon name="terminal" small />{{ $t('baseline.allRemedy') }}</h3>
                <pre class="block" data-testid="bl-remedy">{{ remedyAll }}</pre>
                <div class="fx-act">
                  <button class="btn btn-sm" type="button" @click="copyText(remedyAll)"><Icon name="copy" small />{{ $t('baseline.copyAll') }}</button>
                  <router-link v-if="devOf(dr.device)" class="btn btn-sm btn-blue" :to="{ name: 'change', query: { device: String(devOf(dr.device)!.id), mode: 'paste' } }"><Icon name="branch" small />{{ $t('baseline.toChange') }}</router-link>
                </div>
                <p class="hint">{{ $t('baseline.remedyHint') }}</p>
              </div>
            </template>
          </section>
        </div>
      </template>
    </div>
    <WaiverDialog v-if="waiver" :device-id="waiver.deviceId" :device-name="waiver.deviceName" :rule="waiver.rule" :rule-title="title(waiver.rule)" :baseline="waiver.baseline" @close="waiver = null" />
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </main>
</template>

<style scoped>
.dlrow { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.ctl { display: flex; gap: 10px 14px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 12px; }
.ctl .field { margin: 0; min-width: 220px; display: flex; flex-direction: column; gap: 4px; }
.ctl .select { min-width: 240px; }
.ctl .when { font-size: 12px; color: var(--ink-3); display: inline-flex; gap: 6px; align-items: center; padding-bottom: 6px; }
.pickwrap { position: relative; }
.pickpop { position: absolute; z-index: 30; top: 36px; left: 0; width: 320px; max-height: 420px; overflow: auto; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 6px; box-shadow: var(--shadow-pop); padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.bstrip { grid-template-columns: repeat(4, minmax(0, 1fr)) minmax(0, 1.4fr); margin-bottom: 12px; }
.bstrip .sevrow { display: flex; gap: 10px; margin-top: 6px; flex-wrap: wrap; }
.bstrip .sevrow .sev b { font: 600 15px var(--font-display); color: var(--ink); margin-left: 2px; }
.v.sc-lo { color: var(--red-ink); } .v.sc-mid { color: var(--amber-ink); } .v.sc-hi { color: var(--teal-ink); }
.bl { display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 12px; align-items: start; }
.mxwrap { overflow: auto; max-height: 78vh; }
.mxt { border-collapse: separate; border-spacing: 0; width: 100%; }
.mxt th, .mxt td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: center; vertical-align: middle; }
.mxt thead th { background: var(--surface-2); font-weight: 600; font-size: 12px; color: var(--ink-2); position: sticky; top: 0; z-index: 1; }
.mxt thead th.rh { text-align: left; }
.mxt thead th.colh { cursor: pointer; padding: 8px 6px; }
.mxt thead th.colh:hover { background: var(--surface-3); }
.mxt thead th.colh .dev { font-size: 11px; }
.mxt thead th.colh .sc { display: block; font: 600 11px var(--font-ui); color: var(--teal-ink); margin-top: 3px; }
.mxt thead th.colh .sc.mid { color: var(--amber-ink); }
.mxt thead th.colh .sc.lo { color: var(--red-ink); }
.mxt tbody th { text-align: left; font-weight: 400; cursor: pointer; min-width: 260px; }
.mxt tbody th:hover { background: var(--surface-2); }
.mxt .rid { font: 11px var(--font-mono); color: var(--ink-3); }
.mxt .rname { font-weight: 600; font-size: 12.5px; }
.mxt .rmeta { display: flex; gap: 10px; align-items: center; margin-top: 2px; font-size: 11.5px; color: var(--ink-3); flex-wrap: wrap; }
.mxt td { cursor: pointer; }
.mxt td:hover .mx { outline: 2px solid var(--focus); outline-offset: 1px; }
.mxt .is-col { background: color-mix(in srgb, var(--blue-soft) 55%, transparent); }
.mxt thead th.is-col { background: var(--blue-soft); box-shadow: inset 0 -2px 0 var(--blue); }
.mxt tr.is-row th, .mxt tr.is-row td { background: color-mix(in srgb, var(--amber-soft) 60%, transparent); }
.mxt tr.is-row th { box-shadow: inset 3px 0 0 var(--amber); }
.mxt td.cur .mx { outline: 2px solid var(--amber); outline-offset: 1px; }
.mxleg { display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 10px 14px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-2); align-items: center; }
.mxleg span { display: inline-flex; gap: 6px; align-items: center; }
.mxleg .mx { width: 22px; height: 18px; font-size: 11px; }
.det { max-height: 86vh; overflow: auto; }
.det .panel-h { flex-wrap: wrap; position: sticky; top: 0; background: var(--surface); z-index: 2; }
.score { display: flex; align-items: center; gap: 14px; padding: 12px 14px; border-bottom: 1px solid var(--line); }
.score .ring { width: 54px; height: 54px; flex: none; }
.score .ring circle { fill: none; stroke-width: 6; }
.score .ring .bg { stroke: var(--surface-3); }
.score .ring .fg { stroke: var(--teal); stroke-linecap: round; transform: rotate(-90deg); transform-box: fill-box; transform-origin: center; }
.score .ring .fg.lo { stroke: var(--red); }
.score .ring .fg.mid { stroke: var(--amber); }
.score .ring text { font: 600 13px var(--font-display); fill: var(--ink); text-anchor: middle; dominant-baseline: central; }
.score .meta { font-size: 12px; color: var(--ink-2); display: flex; flex-direction: column; gap: 3px; }
.score .meta b { color: var(--ink); }
.items { display: flex; flex-direction: column; }
.it { padding: 10px 14px; border-bottom: 1px solid var(--line); position: relative; }
.it::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bar, transparent); }
.it.k-fail { --bar: var(--red); } .it.k-warn { --bar: var(--amber); }
.it.cur { background: color-mix(in srgb, var(--amber-soft) 55%, transparent); }
.it .ih { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.it .ih .rid { font: 11px var(--font-mono); color: var(--ink-3); }
.it .ih .nm { font-weight: 600; font-size: 12.5px; }
.inst { margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--line); }
.inst:first-of-type { border-top: 0; }
.it .risk-t { font-size: 12.5px; color: var(--ink); }
.it .code { margin-top: 8px; border: 1px solid var(--line); border-radius: 5px; }
.it .code .l .n { width: 44px; }
.it .act { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.it .act pre.block { width: 100%; margin: 0; font-size: 11.5px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.chips code { font-size: 11px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 3px; padding: 0 4px; }
.fixwrap { padding: 12px 14px; border-top: 1px solid var(--line); }
.fixwrap h3 { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.fixwrap pre.block { max-height: 300px; overflow: auto; font-size: 11.5px; line-height: 1.6; }
.fixwrap .fx-act { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; align-items: center; }
.fixwrap .hint { font-size: 12px; color: var(--ink-3); margin-top: 6px; }
.okall { padding: 22px 14px; text-align: center; color: var(--teal-ink); }
.rdef { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
.rdef .cond { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
.rdef .cond h4 { font-size: 12px; margin-bottom: 4px; display: flex; gap: 6px; align-items: center; }
.rdef .cond p { font-size: 12.5px; color: var(--ink-2); }
.rdef .cond pre.block { margin: 4px 0 0; font-size: 11.5px; }
.sec-k { font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
.rdef .per { display: flex; flex-direction: column; }
.rdef .per > div { display: flex; gap: 8px; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--line); font-size: 12px; cursor: pointer; }
.rdef .per > div:last-child { border-bottom: 0; }
.rdef .per .why { color: var(--ink-3); margin-left: auto; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 55%; }
.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--surface); padding: 8px 14px; border-radius: 6px; font-size: 12.5px; z-index: 60; box-shadow: var(--shadow-pop); }
@media (max-width: 1360px) { .bl { grid-template-columns: minmax(0, 1fr); } .det { max-height: none; } }
@media (max-width: 900px) {
  .bstrip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ctl .field, .ctl .select { min-width: 0; width: 100%; }
}
</style>
