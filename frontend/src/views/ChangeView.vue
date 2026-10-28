<script setup lang="ts">
/**
 * 增量变更（预览 DevelopDocs/ui-preview/M4/change.html）：选当前（设备 + 版本）与目标（设备版本或粘贴）→ POST /change →
 * 带说明的下发脚本（按视图分块、按原因着色、选中一条看“排在谁之后、为什么”）、回滚脚本、模拟执行的复检、影响摘要、下载。
 * 对象名按显示风格（华为 / Cisco）写成命令路径；脚本本身是设备自己的语法。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ModelApproxNote from '@/components/model-approx-note.vue'
import DevChip from '@/components/m4-dev.vue'
import ReportAiSummary from '@/components/ai-kb/ReportAiSummary.vue'
import type { SideSpec } from '@/components/ai-suggest/logic'
import { errorText, get, post } from '@/api'
import { useTerms } from '@/stores/terms'
import { postFile, saveBlob } from '@/views/check/report'
import { saveText } from '@/views/profiles/csv'
import type { Device } from '@/views/devices/logic'
import type { VersionInfo } from '@/views/compare/types'
import ScriptPane from './m4/ScriptPane.vue'
import { msg } from './m4/texts'
import { noteText } from '@/i18n/note'
import { stamp } from './m4/common'
import { isNokiaMd, vendorKey } from '@/vendor'
import { takeHandoff } from './m5/ask'
import IntentPanel from './ai-change/IntentPanel.vue'
import {
  ACTIONS, EDGE_VAR, REASON, chainOf, changeBody, contextBlock, dependents, edgeOf, fileName, fromQuery, opMap,
  pairRollback, ready, riskOps, rowsOf, toQuery, verifyChecks, viewLines, type ChangeResult, type Filter, type Op,
} from './m4/change'

interface ProfileLite { id: string; family: string; vendor: string }

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()

// ---------------------------------------------------------------- 基础数据
const devices = ref<Device[]>([])
const profiles = ref<ProfileLite[]>([])
const loadError = ref('')
const baseLoaded = ref(false) // 设备列表加载完之前下拉框显示“加载中”（带 ?device= 打开时不显示空白，REQ-055-20）
const versions = ref<Record<number, VersionInfo[]>>({})

async function loadBase(): Promise<void> {
  loadError.value = ''
  try {
    const [d, p] = await Promise.all([get<{ devices: Device[] }>('/devices'), get<{ profiles: ProfileLite[] }>('/kb/profiles')])
    devices.value = [...d.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    profiles.value = p.profiles
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    baseLoaded.value = true
  }
}
async function loadVersions(id: number | null): Promise<void> {
  if (id === null || versions.value[id]) return
  try {
    versions.value = { ...versions.value, [id]: (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions }
  } catch {
    versions.value = { ...versions.value, [id]: [] }
  }
}
const familyOf = (pid: string | null | undefined) => profiles.value.find((p) => p.id === pid)?.family ?? ''
const devById = (id: number | null) => devices.value.find((d) => d.id === id) ?? null

// ---------------------------------------------------------------- 当前与目标
const setup = ref(fromQuery(route.query))
const curDev = computed(() => devById(setup.value.device))
const curFamily = computed(() => familyOf(curDev.value?.profile))
/** 生效规则的文案键：按平台族（Nokia 区分 Classic / MD-CLI） */
function changeRuleKey(f: string): string {
  const v = vendorKey(f)
  return v === 'cisco' ? 'ruleCs' : v === 'nokia' ? (isNokiaMd(f) ? 'ruleNkMd' : 'ruleNk') : 'ruleHw'
}
const tgtDevId = computed(() => setup.value.tdevice ?? setup.value.device)
const vers = (id: number | null) => (id === null ? [] : versions.value[id] ?? [])

watch(() => setup.value.device, async (id, old) => {
  await loadVersions(id)
  if (old !== undefined && old !== null && id !== old) {
    setup.value.cv = null
    setup.value.tdevice = null
    setup.value.tv = null
  }
  defaultVersions()
}, { immediate: true })
watch(tgtDevId, (id) => { void loadVersions(id) })

/** 设备有两个以上版本、目标是同一设备时：当前默认取上一个版本，目标取最新版本。 */
function defaultVersions(): void {
  const s = setup.value
  if (s.device === null || s.tmode !== 'version' || (s.tdevice !== null && s.tdevice !== s.device)) return
  const vs = vers(s.device)
  if (vs.length >= 2 && s.cv === null && s.tv === null) s.cv = vs[1].id
}

const sameVersion = computed(() => {
  const s = setup.value
  return s.tmode === 'version' && s.device !== null && tgtDevId.value === s.device && (s.tv ?? -1) === (s.cv ?? -1)
})
const canRun = computed(() => ready(setup.value))

// ---------------------------------------------------------------- 生成
const running = ref(false)
const runError = ref('')
const result = ref<ChangeResult | null>(null)
let lastBody: Record<string, unknown> | null = null
/** M8-5 报告摘要：范围取最近一次生成的当前 / 目标；导出时是否包含 AI 摘要。 */
const aiBody = ref<{ current: SideSpec; target: SideSpec } | null>(null)
const incAi = ref(true)

async function run(): Promise<void> {
  if (!canRun.value || running.value) return
  running.value = true
  runError.value = ''
  const body = changeBody(setup.value, terms.style, lang.value)
  try {
    result.value = await post<ChangeResult>('/change', body)
    lastBody = body
    aiBody.value = { current: body.current as SideSpec, target: body.target as SideSpec }
    sel.value = null
    filter.value = ''
    chainOpen.value = false
    void router.replace({ query: toQuery(setup.value) })
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}

// ---------------------------------------------------------------- 结果
const ops = computed(() => result.value?.ops ?? [])
const fwdMap = computed(() => opMap(ops.value))
const rbOps = computed(() => result.value?.rollback?.ops ?? [])
const rbMap = computed(() => opMap(rbOps.value))
const fwdRows = computed(() => rowsOf(result.value))
const rbRows = computed(() => rowsOf(result.value?.rollback))
const pairs = computed(() => pairRollback(ops.value, rbOps.value))
const counts = computed(() => result.value?.summary.by_action ?? { add: 0, modify: 0, delete: 0, side_effect: 0, mutex: 0 })
const highRisk = computed(() => ops.value.filter((o) => o.risk === 'high').length)
const checks = computed(() => verifyChecks(result.value?.verify, ops.value.length))
const verifyState = computed(() => (!result.value?.verify ? 'off' : result.value.verify.ok && (result.value.rollback?.verify?.ok ?? true) ? 'ok' : 'diff'))
const risks = computed(() => riskOps(ops.value))
const actionName = (a: string) => t(`change.rs.${a}`)
const depName = (k: string) => msg(`change.dep.${k}`, {}, lang.value)
const reasonText = (k: string) => msg(`change.risk_reason.${k}`, {}, lang.value)
const objName = (o: Op) => (o.object ? terms.describe(o.object) : o.label)

const filter = ref<Filter>('')
const sel = ref<number | null>(null)
const chainOpen = ref(false)
const selOp = computed(() => (sel.value === null ? null : fwdMap.value.get(sel.value) ?? null))
const chain = computed(() => (sel.value === null ? [] : chainOf(ops.value, sel.value)))
const directDeps = computed(() => selOp.value?.after.map((a) => a.seq) ?? [])
const depSeqs = computed(() => (chainOpen.value ? chain.value.map((c) => c.seq) : directDeps.value))
const arcs = computed<[number, string][]>(() => (chainOpen.value ? chain.value.map((c) => [c.seq, c.kind]) : (selOp.value?.after ?? []).map((a) => [a.seq, a.kind])))
const depOf = computed(() => (sel.value === null ? [] : dependents(ops.value, sel.value)))
const rbOfSel = computed(() => (sel.value === null ? [] : pairs.value.byFwd.get(sel.value) ?? []))

const fwdPane = ref<InstanceType<typeof ScriptPane>>()
const rbPane = ref<InstanceType<typeof ScriptPane>>()
function select(seq: number | null, scroll = false): void {
  if (seq === sel.value && !scroll) seq = null
  if (seq !== sel.value) chainOpen.value = false
  sel.value = seq
  if (seq === null) return
  void nextTick(() => {
    if (scroll) fwdPane.value?.reveal(seq)
    const r = pairs.value.byFwd.get(seq)?.[0]
    if (r !== undefined) rbPane.value?.reveal(r)
  })
}
function toggleFilter(f: Filter): void {
  filter.value = filter.value === f ? '' : f
}

const linesText = (o: Op) => t('change.srcLines', { cur: o.lines.current.join(', ') || '—', tgt: o.lines.target.join(', ') || '—' })

// ---------------------------------------------------------------- 影响摘要
const impact = computed(() => result.value?.impact ?? null)
const bizTypes = computed(() => Object.entries(impact.value?.by_business ?? {}).filter(([, v]) => v.length))
const impactLink = computed(() => {
  const r = result.value
  if (!r || setup.value.device === null) return null
  const seeds = (r.impact?.seeds ?? []).filter((s) => s.side === 'current').map((s) => s.node)
  if (!seeds.length) return null
  const q: Record<string, string | string[]> = { device: String(setup.value.device), node: seeds.slice(0, 12), from: 'change' }
  if (setup.value.cv !== null) q.version = String(setup.value.cv)
  return { name: 'impact', query: q }
})

// ---------------------------------------------------------------- 复制与下载
const toast = ref('')
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
const devName = computed(() => result.value?.current.device ?? curDev.value?.name ?? 'config')
function dl(kind: 'change' | 'rollback' | 'annotated'): void {
  const r = result.value
  if (!r) return
  const text = kind === 'change' ? r.script_plain : kind === 'annotated' ? r.script : r.rollback?.script_plain ?? ''
  saveText(fileName(devName.value, kind, stamp()), text, 'text/plain;charset=utf-8')
}
const reportFmt = ref<'html' | 'md'>('html')
const reporting = ref('')
async function report(rl: 'zh-CN' | 'en'): Promise<void> {
  if (!lastBody) return
  reporting.value = rl
  try {
    const name = `change-${devName.value.replace(/[^\w.@-]+/g, '_')}.${rl}.${reportFmt.value}`
    const f = await postFile('/change/report', { ...lastBody, report_lang: rl, format: reportFmt.value, include_ai_summary: incAi.value }, name)
    saveBlob(f.blob, f.name)
  } catch (e) {
    flash(t('change.reportFail', { e: errorText(e) }))
  } finally {
    reporting.value = ''
  }
}

onMounted(async () => {
  await loadBase()
  if (setup.value.device === null && devices.value.length) {
    setup.value.device = (devices.value.find((d) => d.versions >= 2) ?? devices.value[0]).id
  }
  if (route.query.run === '1' && canRun.value) void run()
  // 从 AI 查询页的护栏“交给增量变更”过来：目标是合并后的完整配置（放在会话存储里，见 views/m5/ask.ts）
  if (route.query.handoff === '1') {
    const h = takeHandoff()
    if (h) {
      setup.value.device = h.device
      setup.value.tmode = 'paste'
      setup.value.text = h.text
      if (h.profile && profiles.value.some((p) => p.id === h.profile)) setup.value.profile = h.profile
      if (canRun.value) void run()
    }
  }
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.chg') }}</span><span class="sep">/</span><span>{{ $t('nav.change') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('change.title') }}</h1>
          <p class="ph-sub">{{ $t('change.sub') }}</p>
        </div>
      </div>

      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadBase">{{ $t('c.retry') }}</button></div>

      <!-- ===================== 当前 → 目标 ===================== -->
      <section class="panel" aria-label="Setup" data-testid="chg-setup">
        <div class="panel-b setup">
          <div class="route">
            <div class="end">
              <div class="end-h"><span class="side-b">A</span><span>{{ $t('change.current') }}</span></div>
              <div class="end-sel">
                <select v-model="setup.device" class="select" :aria-label="$t('change.device')" data-testid="chg-device">
                  <option v-if="!devices.length" :value="baseLoaded ? null : setup.device">{{ baseLoaded ? $t('change.noDevices') : $t('c.loading') }}</option>
                  <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}{{ d.versions > 1 ? ` (${d.versions})` : '' }}</option>
                </select>
                <select v-model="setup.cv" class="select" :aria-label="$t('change.version')" data-testid="chg-cv">
                  <option :value="null">{{ $t('change.latest') }}</option>
                  <option v-for="v in vers(setup.device)" :key="v.id" :value="v.id">v{{ v.seq }} · {{ v.source_name }}{{ v.latest ? ` (${$t('change.latestTag')})` : '' }}</option>
                </select>
              </div>
              <div class="end-meta">
                <DevChip v-if="curDev" :name="curDev.name" :vendor="curDev.vendor" />
                <span v-if="curDev">Profile <code>{{ curDev.profile }}</code></span>
                <span v-if="curFamily">{{ curFamily }}</span>
              </div>
            </div>
            <div class="arrow"><Icon name="chevR" /></div>
            <div class="end">
              <div class="end-h">
                <span class="side-b t">B</span><span>{{ $t('change.target') }}</span>
                <div class="srcseg" role="group" style="margin-left: auto">
                  <button type="button" :aria-pressed="setup.tmode === 'version'" data-testid="chg-src-version" @click="setup.tmode = 'version'"><Icon name="history" small /><span>{{ $t('change.srcVersion') }}</span></button>
                  <button type="button" :aria-pressed="setup.tmode === 'paste'" data-testid="chg-src-paste" @click="setup.tmode = 'paste'"><Icon name="file" small /><span>{{ $t('change.srcPaste') }}</span></button>
                </div>
              </div>
              <div v-if="setup.tmode === 'version'" class="end-sel">
                <select :value="tgtDevId" class="select" :aria-label="$t('change.device')" data-testid="chg-tdevice" @change="setup.tdevice = Number(($event.target as HTMLSelectElement).value); setup.tv = null">
                  <option v-for="d in devices" :key="d.id" :value="d.id" :disabled="!!curFamily && familyOf(d.profile) !== curFamily">{{ d.name }}{{ curFamily && familyOf(d.profile) !== curFamily ? ` ${$t('change.otherFamily')}` : '' }}</option>
                </select>
                <select v-model="setup.tv" class="select" :aria-label="$t('change.version')" data-testid="chg-tv">
                  <option :value="null">{{ $t('change.latest') }}</option>
                  <option v-for="v in vers(tgtDevId)" :key="v.id" :value="v.id">v{{ v.seq }} · {{ v.source_name }}{{ v.latest ? ` (${$t('change.latestTag')})` : '' }}</option>
                </select>
              </div>
              <template v-else>
                <textarea v-model="setup.text" class="input mono paste" rows="5" :placeholder="$t('change.pastePh')" data-testid="chg-paste" />
                <select v-model="setup.profile" class="select" style="max-width: 320px" :aria-label="$t('change.autoProfile')">
                  <option value="">{{ $t('change.autoProfile') }}</option>
                  <option v-for="p in profiles.filter((x) => !curFamily || x.family === curFamily)" :key="p.id" :value="p.id">{{ p.id }}</option>
                </select>
              </template>
              <div class="end-meta">
                <span v-if="sameVersion" style="color: var(--amber-ink)">{{ $t('change.sameVersion') }}</span>
                <span v-else>{{ $t('change.compareNote') }}</span>
              </div>
            </div>
          </div>
          <div class="opts">
            <span v-if="curFamily" class="fixed-rule"><Icon name="check" small />{{ $t(`change.${changeRuleKey(curFamily)}`) }}</span>
            <span class="fixed-rule"><Icon name="check" small />{{ $t('change.ruleBlocks') }}</span>
            <label class="check"><input v-model="setup.rollback" type="checkbox" data-testid="chg-opt-rollback"><span>{{ $t('change.optRollback') }}</span></label>
            <label class="check"><input v-model="setup.verify" type="checkbox"><span>{{ $t('change.optVerify') }}</span></label>
            <button class="btn btn-primary btn-sm ml-auto" type="button" :disabled="!canRun || running" data-testid="chg-run" @click="run"><Icon name="play" small />{{ running ? $t('change.running') : $t('change.run') }}</button>
          </div>
        </div>
      </section>

      <div v-if="runError" class="notice err mt12" data-testid="chg-error"><Icon name="err" /><div class="grow">{{ runError }}</div><button class="btn btn-sm" type="button" @click="run">{{ $t('c.retry') }}</button></div>
      <div v-if="!result && !runError && !running" class="empty mt16" data-testid="chg-empty"><Icon name="branch" /><h3>{{ $t('change.emptyTitle') }}</h3><p>{{ $t('change.emptyText') }}</p></div>
      <div v-if="running && !result" class="empty mt16"><p>{{ $t('c.loading') }}</p></div>

      <!-- ===================== 变更意图转脚本（M8-4，AI） ===================== -->
      <IntentPanel :device-id="setup.device" :device-name="curDev?.name" />

      <!-- ===================== 结果 ===================== -->
      <template v-if="result">
        <ModelApproxNote :note="result.approx_profile" />
        <div class="res-head">
          <h2>{{ $t('change.result') }}</h2>
          <span class="meta">
            <DevChip :name="result.current.device ?? result.current.label" :vendor="result.family" />
            <span>{{ result.current.label }} → {{ result.target.label }}</span>
            <span>{{ result.family }}</span>
          </span>
          <span class="ml-auto" />
          <button class="btn btn-sm" type="button" :disabled="result.equal" data-testid="chg-copy" @click="copyText(result.script_plain)"><Icon name="copy" small />{{ $t('change.copy') }}</button>
          <router-link v-if="impactLink" class="btn btn-sm" :to="impactLink" data-testid="chg-to-impact"><Icon name="target" small />{{ $t('change.toImpact') }}</router-link>
        </div>

        <div v-if="result.equal" class="notice ok" data-testid="chg-equal"><Icon name="ok" /><div class="grow"><b>{{ $t('change.equalTitle') }}</b> {{ $t('change.equalText') }}</div></div>

        <template v-else>
          <div class="sumbar" data-testid="chg-sumbar">
            <div><span class="n">{{ ops.length }}<small>{{ $t('change.cmds') }}</small></span><span class="k">{{ $t('change.viewLines', { n: viewLines(fwdRows) }) }}</span></div>
            <button v-for="a in ACTIONS" :key="a" type="button" :aria-pressed="filter === a" :style="{ '--c': `var(--chg-${REASON[a]})` }" :data-testid="`chg-sum-${a}`" @click="toggleFilter(a)">
              <span class="n">{{ counts[a] ?? 0 }}</span><span class="k"><span class="rs" :class="REASON[a]">{{ actionName(a) }}</span></span>
            </button>
            <button type="button" :aria-pressed="filter === 'risk'" style="--c: var(--red)" data-testid="chg-sum-risk" @click="toggleFilter('risk')">
              <span class="n" style="color: var(--red-ink)">{{ highRisk }}</span><span class="k"><span class="risk cut"><Icon name="bolt" />{{ $t('change.risk.high') }}</span></span>
            </button>
          </div>

          <div class="verify" :class="verifyState" data-testid="chg-verify">
            <span class="vi"><Icon :name="verifyState === 'ok' ? 'ok' : verifyState === 'diff' ? 'warn' : 'info'" /></span>
            <div>
              <h3>{{ verifyState === 'off' ? $t('change.verifyOff') : verifyState === 'ok' ? $t('change.verifyOk') : $t('change.verifyBad') }}</h3>
              <div v-if="result.verify" class="rchk">
                <span v-for="c in checks" :key="c.k" :class="{ bad: !c.ok }"><Icon :name="c.ok ? 'check' : 'warn'" />{{ $t(`change.v.${c.k}`, { n: c.n ?? 0, total: ops.length }) }}</span>
                <span v-if="result.rollback?.verify" :class="{ bad: !result.rollback.verify.ok }"><Icon :name="result.rollback.verify.ok ? 'check' : 'warn'" />{{ result.rollback.verify.ok ? $t('change.vRollbackOk') : $t('change.vRollbackBad') }}</span>
              </div>
              <ul v-if="result.verify?.issues.length" class="issues">
                <li v-for="(i, n) in result.verify.issues" :key="n"><code>{{ i.kind }}</code> <span v-if="i.seq">#{{ i.seq }}</span> <code v-if="i.text">{{ i.text }}</code></li>
              </ul>
            </div>
          </div>

          <div class="work" data-testid="chg-work">
            <section class="panel pane" aria-label="Change script">
              <div class="tbar">
                <span class="side-b" style="border-color: var(--amber); color: var(--amber-ink)">→</span><b>{{ $t('change.applyScript') }}</b>
                <span class="fn">{{ fileName(devName, 'change', stamp()) }}</span><span class="ml-auto" />
                <button v-if="sel !== null" class="btn btn-xs btn-ghost" type="button" @click="select(null)"><Icon name="x" small />{{ $t('change.clearSel') }}</button>
              </div>
              <ScriptPane ref="fwdPane" :rows="fwdRows" :ops="fwdMap" side="f" :sel="sel" :deps="depSeqs" :arcs="arcs" :filter="filter" :action-name="actionName" testid="chg-script" @pick="(s) => select(s)" />
            </section>
            <section class="panel pane" aria-label="Rollback script">
              <div class="tbar">
                <span class="side-b" style="border-color: var(--blue); color: var(--blue-ink)"><Icon name="rollback" small /></span><b>{{ $t('change.rollbackScript') }}</b>
                <span v-if="result.rollback" class="fn">{{ fileName(devName, 'rollback', stamp()) }}</span>
              </div>
              <ScriptPane v-if="result.rollback" ref="rbPane" :rows="rbRows" :ops="rbMap" side="r" :sel="sel" :pairs="rbOfSel" :pair-of="pairs.byRb" :action-name="actionName" testid="chg-rollback" @pick="(s) => select(s, true)" />
              <div v-else class="empty"><p>{{ $t('change.noRollback') }}</p></div>
            </section>

            <!-- 详情 -->
            <section class="panel dpanel" aria-label="Details" data-testid="chg-side">
              <template v-if="!selOp">
                <div class="panel-h"><h3>{{ $t('change.risks') }}</h3><span class="meta">{{ $t('change.risksHint') }}</span></div>
                <div class="sb">
                  <p v-if="!risks.length" class="small muted">{{ $t('change.noRisks') }}</p>
                  <div v-for="o in risks" :key="o.seq" class="riskitem" :class="o.risk === 'high' ? '' : 'care'" tabindex="0" data-testid="chg-risk" @click="select(o.seq, true)" @keydown.enter="select(o.seq, true)">
                    <div class="rh">
                      <span v-if="o.risk === 'high'" class="risk cut"><Icon name="bolt" />{{ $t('change.risk.high') }}</span>
                      <span v-else class="risk care"><Icon name="warn" />{{ $t('change.risk.medium') }}</span>
                      <code>#{{ o.seq }} {{ o.text }}</code>
                    </div>
                    <div class="rt">{{ objName(o) }}</div>
                    <div v-if="o.risk_reasons.length" class="ra">{{ o.risk_reasons.map(reasonText).join('；') }}</div>
                  </div>

                  <div v-if="impact">
                    <div class="sec-k"><Icon name="ripple" small />{{ $t('change.impact') }}</div>
                    <p class="small">{{ $t('change.impactN', { objects: impact.summary.objects, business: impact.summary.business }) }}</p>
                    <p v-if="!bizTypes.length" class="small muted">{{ $t('change.impactNone') }}</p>
                    <div v-for="[k, list] in bizTypes" :key="k" class="bizgrp">
                      <div class="small muted">{{ $t(`change.biz.${k}`) }} {{ list.length }}</div>
                      <div class="chips"><code v-for="n in list.slice(0, 12)" :key="n" :title="n">{{ terms.describe(n) }}</code><span v-if="list.length > 12" class="small faint">+{{ list.length - 12 }}</span></div>
                    </div>
                  </div>

                  <div v-if="result.unsupported.length">
                    <div class="sec-k"><Icon name="warn" small />{{ $t('change.unsupported') }} {{ result.unsupported.length }}</div>
                    <p class="small muted">{{ $t('change.unsupportedHint') }}</p>
                    <div class="chips"><code v-for="(u, i) in result.unsupported" :key="i">{{ u.node ? terms.describe(u.node) : u.text }}</code></div>
                  </div>
                  <div v-if="result.warnings.length">
                    <div class="sec-k"><Icon name="info" small />{{ $t('change.warnings') }}</div>
                    <ul class="rules"><li v-for="(w, i) in result.warnings" :key="i">{{ w.key ? msg(w.key, { a: w.a, b: w.b, ...(w.params ?? {}) }, lang) : w.kind }}</li></ul>
                  </div>

                  <div class="sec-k"><Icon name="order" small />{{ $t('change.orderRules') }}</div>
                  <ol class="rules">
                    <li v-for="k in 5" :key="k">{{ $t(`change.rule${k}`) }}</li>
                  </ol>
                  <p class="small faint">{{ $t('change.rulesNote') }}</p>
                </div>
              </template>
              <template v-else>
                <div class="panel-h">
                  <h3>#{{ selOp.seq }}</h3>
                  <span class="rs" :class="REASON[selOp.action]">{{ actionName(selOp.action) }}</span>
                  <span v-if="selOp.risk === 'high'" class="risk cut"><Icon name="bolt" />{{ $t('change.risk.high') }}</span>
                  <span v-else-if="selOp.risk === 'medium'" class="risk care"><Icon name="warn" />{{ $t('change.risk.medium') }}</span>
                  <button class="btn btn-xs btn-ghost ml-auto" type="button" :aria-label="$t('change.clearSel')" @click="select(null)"><Icon name="x" small /></button>
                </div>
                <div class="sb" data-testid="chg-detail">
                  <div class="cmdbox">{{ contextBlock(selOp) }}</div>
                  <div>
                    <div class="sec-k">{{ $t('change.whyCmd') }}</div>
                    <div class="why">{{ $t(`change.why.${selOp.action}`, { obj: objName(selOp) }) }}</div>
                    <div class="small faint mt8">{{ linesText(selOp) }}</div>
                    <div class="small faint">Schema <code>{{ selOp.object }}</code></div>
                    <div v-if="selOp.fallback" class="notice warn mt8" style="font-size: 12px"><Icon name="warn" small /><span>{{ $t('change.fallback') }}</span></div>
                  </div>
                  <div v-if="selOp.risk_reasons.length" class="riskitem" :class="selOp.risk === 'high' ? '' : 'care'" style="cursor: default">
                    <div class="rh"><b class="small">{{ $t('change.riskReasons') }}</b></div>
                    <div class="rt">{{ selOp.risk_reasons.map(reasonText).join('；') }}</div>
                  </div>
                  <div>
                    <div class="sec-k"><Icon name="order" small />{{ $t('change.whyHere') }}</div>
                    <p v-if="!selOp.after.length" class="small muted">{{ $t('change.noDeps') }}</p>
                    <div v-else class="deps" data-testid="chg-deps">
                      <div v-for="a in selOp.after" :key="a.seq + a.kind" class="dep" tabindex="0" @click="select(a.seq, true)" @keydown.enter="select(a.seq, true)">
                        <span class="et" :style="{ color: EDGE_VAR[edgeOf(a.kind)] }"><i :style="{ background: EDGE_VAR[edgeOf(a.kind)] }" />{{ depName(a.kind) }}</span>
                        <div><span class="lnk">#{{ a.seq }}</span><code>{{ fwdMap.get(a.seq)?.text }}</code></div>
                        <div class="dt">{{ a.node ? terms.describe(a.node) : a.label }}<template v-if="noteText(a.note, lang)">：{{ noteText(a.note, lang) }}</template></div>
                      </div>
                    </div>
                    <template v-if="chain.length > selOp.after.length || chainOpen">
                      <button class="link-btn mt8" type="button" data-testid="chg-chain" @click="chainOpen = !chainOpen"><Icon :name="chainOpen ? 'chevD' : 'chevR'" small />{{ chainOpen ? $t('change.chainHide') : $t('change.chainShow', { n: chain.length }) }}</button>
                      <div v-if="chainOpen" class="chaintree mt8">
                        <div class="cur">#{{ selOp.seq }} {{ selOp.text }}</div>
                        <div v-for="c in chain" :key="c.seq" :style="{ paddingLeft: `${c.level * 14}px` }" @click="select(c.seq, true)"><span class="lv">└ {{ depName(c.kind) }} · </span>#{{ c.seq }} {{ fwdMap.get(c.seq)?.text }}</div>
                      </div>
                    </template>
                  </div>
                  <div v-if="depOf.length">
                    <div class="sec-k">{{ $t('change.dependents') }}</div>
                    <div class="deps">
                      <div v-for="d in depOf" :key="d.op.seq" class="dep" tabindex="0" @click="select(d.op.seq, true)">
                        <span class="et" :style="{ color: EDGE_VAR[edgeOf(d.kind)] }"><i :style="{ background: EDGE_VAR[edgeOf(d.kind)] }" />{{ depName(d.kind) }}</span>
                        <div><span class="lnk">#{{ d.op.seq }}</span><code>{{ d.op.text }}</code></div>
                      </div>
                    </div>
                  </div>
                  <div v-if="result.rollback">
                    <div class="sec-k"><Icon name="rollback" small />{{ $t('change.rollback') }}</div>
                    <p v-if="!rbOfSel.length" class="small muted">{{ $t('change.rollbackNone') }}</p>
                    <template v-else>
                      <div class="cmdbox">{{ rbOfSel.map((s) => rbMap.get(s)?.text).join('\n') }}</div>
                      <p v-if="rbOfSel.length === 1 && (pairs.byRb.get(rbOfSel[0])?.length ?? 0) > 1" class="small faint mt8">{{ $t('change.rollbackMany', { list: pairs.byRb.get(rbOfSel[0])!.map((s) => `#${s}`).join('、') }) }}</p>
                    </template>
                  </div>
                </div>
              </template>
            </section>
          </div>

          <div class="dlrow" data-testid="chg-downloads">
            <span class="k">{{ $t('change.download') }}</span>
            <button class="btn btn-sm" type="button" data-testid="chg-dl-change" @click="dl('change')"><Icon name="download" small />{{ $t('change.dlChange') }}</button>
            <button class="btn btn-sm" type="button" @click="dl('annotated')"><Icon name="download" small />{{ $t('change.dlAnnotated') }}</button>
            <button class="btn btn-sm" type="button" :disabled="!result.rollback" data-testid="chg-dl-rollback" @click="dl('rollback')"><Icon name="download" small />{{ $t('change.dlRollback') }}</button>
            <span class="sep-v" />
            <div class="seg" role="group" :aria-label="$t('change.reportFmt')">
              <button type="button" :aria-pressed="reportFmt === 'html'" @click="reportFmt = 'html'">HTML</button>
              <button type="button" :aria-pressed="reportFmt === 'md'" @click="reportFmt = 'md'">Markdown</button>
            </div>
            <button class="btn btn-sm" type="button" :disabled="!!reporting" data-testid="chg-report-zh" @click="report('zh-CN')"><Icon name="report" small />{{ $t('change.reportZh') }}</button>
            <button class="btn btn-sm" type="button" :disabled="!!reporting" data-testid="chg-report-en" @click="report('en')"><Icon name="report" small />{{ $t('change.reportEn') }}</button>
          </div>
          <ReportAiSummary v-model="incAi" kind="change" :params="aiBody" style="margin-top: 10px" />
        </template>
      </template>
    </div>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </main>
</template>

<style scoped>
.setup { display: flex; flex-direction: column; gap: 12px; }
.route { display: grid; grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1.25fr); gap: 10px; align-items: stretch; }
.end { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: var(--surface-2); display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.end-h { display: flex; align-items: center; gap: 8px; font-weight: 600; flex-wrap: wrap; }
.side-b { width: 20px; height: 20px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); border: 1.5px solid var(--blue); color: var(--blue-ink); flex: none; }
.side-b.t { border-color: var(--amber); color: var(--amber-ink); }
.end-sel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.end-meta { display: flex; gap: 6px 12px; flex-wrap: wrap; font-size: 12px; color: var(--ink-3); align-items: center; }
.route .arrow { display: flex; align-items: center; justify-content: center; color: var(--ink-3); }
.srcseg { display: flex; flex-wrap: wrap; border: 1px solid var(--line-strong); border-radius: var(--r-ctl); overflow: hidden; width: fit-content; background: var(--surface); }
.srcseg button { border: 0; background: transparent; font: inherit; font-size: 12px; height: 28px; padding: 0 10px; color: var(--ink-2); cursor: pointer; display: inline-flex; gap: 5px; align-items: center; }
.srcseg button + button { border-left: 1px solid var(--line); }
.srcseg button[aria-pressed="true"] { background: var(--amber-soft); color: var(--amber-ink); font-weight: 600; }
.paste { width: 100%; resize: vertical; min-height: 90px; font-size: 12px; }
.opts { display: flex; gap: 8px 18px; align-items: center; flex-wrap: wrap; }
.fixed-rule { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); border: 1px dashed var(--line-strong); border-radius: 4px; padding: 2px 8px; }
.fixed-rule :deep(.ico) { color: var(--teal-ink); }

.res-head { display: flex; align-items: center; gap: 12px; margin: 18px 0 10px; flex-wrap: wrap; }
.res-head h2 { font-size: 15px; }
.res-head .meta { color: var(--ink-3); font-size: 12px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.sumbar { display: grid; grid-template-columns: minmax(0, 1.1fr) repeat(5, minmax(0, 1fr)) minmax(0, 1fr); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; }
.sumbar > button, .sumbar > div { all: unset; box-sizing: border-box; padding: 10px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 4px; min-width: 0; position: relative; }
.sumbar > :first-child { border-left: 0; }
.sumbar > button { cursor: pointer; }
.sumbar > button:hover { background: var(--surface-2); }
.sumbar > button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.sumbar > button[aria-pressed="true"] { background: var(--surface-3); }
.sumbar > button[aria-pressed="true"]::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--c, var(--ink-3)); }
.sumbar .n { font: 600 22px/1.2 var(--font-display); }
.sumbar .n small { font: 400 12px var(--font-ui); color: var(--ink-3); margin-left: 6px; }
.sumbar .k { font-size: 12px; color: var(--ink-2); display: flex; gap: 6px; align-items: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.verify { margin-top: 10px; }
.rchk { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 4px; font-size: 12px; color: var(--ink-2); }
.rchk span { display: inline-flex; align-items: center; gap: 5px; }
.rchk :deep(.ico) { color: var(--teal-ink); width: 14px; height: 14px; }
.rchk .bad { color: var(--amber-ink); }
.rchk .bad :deep(.ico) { color: var(--amber-ink); }
.issues { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: var(--ink-2); }

.work { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr) 372px; gap: 10px; margin-top: 10px; height: min(74vh, 820px); min-height: 520px; }
.pane { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.pane .tbar { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 1px solid var(--line); font-size: 12px; white-space: nowrap; overflow: hidden; }
.pane .tbar .side-b { border-color: var(--line-strong); }
.pane .tbar .fn { font: 11.5px var(--font-mono); color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; }
.pane :deep(.scr) { flex: 1; min-height: 0; }

.dpanel { display: flex; flex-direction: column; overflow: hidden; }
.dpanel .panel-h { flex: none; gap: 8px; }
.dpanel .sb { flex: 1; overflow: auto; padding: 12px 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.sec-k { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--ink-2); margin: 2px 0 6px; }
.cmdbox { font: 12px/1.6 var(--font-mono); background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.why { color: var(--ink); font-size: 12.5px; line-height: 1.6; }
.deps { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.dep { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 10px; padding: 8px 10px; border-top: 1px solid var(--line); cursor: pointer; align-items: start; }
.dep:first-child { border-top: 0; }
.dep:hover { background: var(--surface-2); }
.dep .et { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.dep .et i { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
.dep code { font-size: 11.5px; overflow-wrap: anywhere; }
.dep .dt { grid-column: 2; font-size: 12px; color: var(--ink-2); overflow-wrap: anywhere; }
.dep .lnk { font: 11px var(--font-ui); color: var(--ink-3); margin-right: 6px; }
.chaintree { font: 11.5px/1.9 var(--font-mono); color: var(--ink-2); border-left: 2px solid var(--teal-line); padding: 2px 0 2px 10px; }
.chaintree div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
.chaintree div:hover { color: var(--blue-ink); }
.chaintree .lv { color: var(--ink-3); }
.chaintree .cur { color: var(--amber-ink); font-weight: 700; }
.riskitem { border: 1px solid var(--line); border-left: 3px solid var(--red); border-radius: 6px; padding: 8px 10px; cursor: pointer; display: flex; flex-direction: column; gap: 5px; }
.riskitem.care { border-left-color: var(--amber); }
.riskitem:hover { background: var(--surface-2); }
.riskitem .rh { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.riskitem .rh code { font-size: 11.5px; color: var(--ink-2); overflow-wrap: anywhere; }
.riskitem .rt { font-size: 12.5px; color: var(--ink); overflow-wrap: anywhere; }
.riskitem .ra { font-size: 12px; color: var(--ink-2); }
.rules { margin: 0; padding-left: 18px; color: var(--ink-2); font-size: 12px; line-height: 1.7; }
.bizgrp { margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.chips code { font-size: 11px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 3px; padding: 0 4px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dlrow { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.dlrow .k { font-size: 12px; color: var(--ink-2); margin-right: 4px; }
.sep-v { width: 1px; height: 20px; background: var(--line); margin: 0 4px; }
.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--surface); padding: 8px 14px; border-radius: 6px; font-size: 12.5px; z-index: 60; box-shadow: var(--shadow-pop); }

@media (max-width: 1360px) {
  .work { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); height: auto; grid-template-rows: min(66vh, 700px) auto; }
  .work .dpanel { grid-column: 1 / -1; max-height: 640px; }
  .sumbar { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .sumbar > :nth-child(5) { border-left: 0; }
  .sumbar > :nth-child(n+5) { border-top: 1px solid var(--line); }
}
@media (max-width: 900px) {
  .route { grid-template-columns: minmax(0, 1fr); }
  .route .arrow { transform: rotate(90deg); height: 28px; }
  .work { grid-template-columns: minmax(0, 1fr); grid-template-rows: 460px 380px auto; }
  .work .dpanel { grid-column: 1; }
  .sumbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sumbar > * { border-left: 0 !important; border-top: 1px solid var(--line); }
  .sumbar > :first-child { grid-column: 1 / -1; border-top: 0; }
  .end-sel { grid-template-columns: minmax(0, 1fr); }
}
</style>
