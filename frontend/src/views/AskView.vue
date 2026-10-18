<script setup lang="ts">
/**
 * AI 查询与护栏（预览 DevelopDocs/ui-preview/M5/ask.html，REQ-024）。
 * 问配置：AI 写图查询 → 代码执行（结果表）→ AI 组织回答，每句带引用角标与代码核对状态，可展开核对明细、查看发给 AI 的脱敏内容。
 * 生成配置：AI 起草 → 护栏（解析、入图、依赖、模板、冲突）逐行标 ✓ / ✕ / !，通过后才能交给增量变更。
 * 未配置 AI 时导航不显示入口（D-0089）；直接打开时显示降级说明，并保留“校验粘贴的配置”（护栏由代码完成，POST /guard）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import { ApiError, errorText, get, post } from '@/api'
import { pickLang } from '@/i18n'
import { useStatus } from '@/stores/status'
import { useTerms } from '@/stores/terms'
import type { Device } from '@/views/devices/logic'
import GuardResult from './m5/GuardResult.vue'
import {
  cellShow, queryParts, rowOf, saveHandoff, stmtCls, stmtCounts,
  type AskResult, type AskStatus, type GenerateResult, type GuardResult as Guard, type QRow, type Sent,
} from './m5/ask'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()
const status = useStatus()

const st = ref<AskStatus | null>(null)
const stError = ref('')
const devices = ref<Device[]>([])
const templates = ref<{ id: string; title: Record<string, string> }[]>([])
const on = computed(() => !!st.value?.configured)

async function loadStatus(): Promise<void> {
  stError.value = ''
  try { st.value = await get<AskStatus>('/ask/status') } catch (e) { stError.value = errorText(e) }
}
async function loadBase(): Promise<void> {
  try {
    const [d, tp] = await Promise.all([get<{ devices: Device[] }>('/devices'), get<{ templates: { id: string; title: Record<string, string> }[] }>('/templates').catch(() => ({ templates: [] }))])
    devices.value = [...d.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    templates.value = tp.templates
    if (!target.value && devices.value.length) target.value = devices.value[0].name
  } catch { /* 设备列表取不到时表单仍可用 */ }
}

const tab = ref<'ask' | 'gen'>(route.query.tab === 'gen' ? 'gen' : 'ask')
watch(tab, (v) => { void router.replace({ query: { ...route.query, tab: v === 'gen' ? 'gen' : undefined } }) })

const toast = ref('')
let tt = 0
function flash(s: string): void { toast.value = s; window.clearTimeout(tt); tt = window.setTimeout(() => { toast.value = '' }, 2600) }
function copy(s: string): void {
  const ok = () => flash(t('c.copied'))
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(ok, ok)
  else ok()
}
/** 409 not_configured：AI 在别处被关掉了，切到降级视图。 */
function notConfigured(e: unknown): boolean {
  if (e instanceof ApiError && e.status === 409 && (e.data as { status?: string } | null)?.status === 'not_configured') {
    st.value = st.value ? { ...st.value, configured: false, status: 'not_configured' } : null
    void status.refresh()
    return true
  }
  return false
}

// ---------------------------------------------------------------- 问配置
interface Turn { id: number; question: string; res: AskResult | null; error: string; busy: boolean }
const scope = ref<string[]>([])
const turns = ref<Turn[]>([])
const question = ref('')
let tid = 0
const SUGG = ['ask.sugg1', 'ask.sugg2', 'ask.sugg3']
const allScope = computed(() => !scope.value.length || scope.value.length === devices.value.length)
function toggleScope(n: string): void {
  const cur = scope.value.length ? scope.value : devices.value.map((d) => d.name)
  scope.value = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]
  if (!scope.value.length) scope.value = devices.value.map((d) => d.name)
}
async function ask(): Promise<void> {
  const q = question.value.trim()
  if (!q) return
  const turn: Turn = { id: ++tid, question: q, res: null, error: '', busy: true }
  turns.value = [...turns.value, turn]
  question.value = ''
  try {
    const r = await post<AskResult>('/ask', { question: q, devices: allScope.value ? null : scope.value, lang: lang.value })
    turn.res = r
    const first = r.answer?.statements.find((s) => s.cites.length)?.cites[0] ?? r.result?.rows[0]?.n
    if (first) pickCite(turn.id, first)
  } catch (e) {
    if (!notConfigured(e)) turn.error = errorText(e)
  } finally {
    turn.busy = false
    turns.value = [...turns.value]
  }
}
const selCite = ref<{ turn: number; n: number } | null>(null)
const selTurn = computed(() => turns.value.find((x) => x.id === selCite.value?.turn) ?? null)
const selRow = computed<QRow | null>(() => (selTurn.value?.res && selCite.value ? rowOf(selTurn.value.res.result, selCite.value.n) : null))
const selStatements = computed(() => (selTurn.value?.res?.answer?.statements ?? []).filter((s) => selCite.value && (s.cites.includes(selCite.value.n) || s.facts.some((f) => f.row === selCite.value!.n))))
const texts = ref<Record<number, string[]>>({})
async function pickCite(turn: number, n: number): Promise<void> {
  selCite.value = { turn, n }
  const row = rowOf(turns.value.find((x) => x.id === turn)?.res?.result ?? null, n)
  if (row?.device_id && !texts.value[row.device_id]) {
    try {
      const g = await get<{ text?: string }>(`/devices/${row.device_id}/graph?raw=true`)
      texts.value = { ...texts.value, [row.device_id]: (g.text ?? '').split('\n') }
    } catch { /* 只显示行号 */ }
  }
}
const evLines = computed(() => {
  const r = selRow.value
  if (!r?.device_id || !r.lines.length) return []
  const text = texts.value[r.device_id]
  if (!text) return []
  const hl = new Set(Object.values(r.cells).flatMap((c) => c.lines))
  return r.lines.slice(0, 40).map((n) => ({ n, t: text[n - 1] ?? '', hl: hl.has(n) }))
})
const hasDefault = computed(() => !!selRow.value && Object.values(selRow.value.cells).some((c) => c.origin === 'default'))
const stLabel = (s: string) => t(`ask.st.${s}`)
function factText(f: { field: string; value: unknown; actual: unknown; ok: boolean }): string {
  const v = (x: unknown) => (x === null || x === undefined ? t('ask.notSet') : Array.isArray(x) ? x.join(', ') : String(x))
  return f.ok ? `${f.field} = ${v(f.actual)}` : `${f.field}: ${v(f.value)} ≠ ${v(f.actual)}`
}

// 发送内容
const sentOpen = ref<{ sent: Sent[]; q: string } | null>(null)
const lastSent = computed(() => {
  const last = [...turns.value].reverse().find((x) => x.res)?.res
  if (last) return { sent: last.sent, q: last.question_sent }
  if (gen.value) return { sent: gen.value.sent, q: gen.value.request_sent }
  return null
})

// ---------------------------------------------------------------- 生成配置 / 校验粘贴的配置
const target = ref('')
const tpl = ref('')
const mode = ref<'ai' | 'paste'>('ai')
const request = ref('')
const paste = ref('')
const gen = ref<GenerateResult | null>(null)
const genRound = ref(0)
const guard = ref<Guard | null>(null)
const busy = ref(false)
const genError = ref('')
const shown = computed<Guard | null>(() => (mode.value === 'ai' && on.value ? gen.value?.rounds.find((r) => r.round === genRound.value)?.guard ?? gen.value?.final.guard ?? null : guard.value))
const merged = ref('')
async function generate(): Promise<void> {
  if (!request.value.trim() || !target.value) return
  busy.value = true
  genError.value = ''
  try {
    const r = await post<GenerateResult>('/generate', { request: request.value, device: target.value, template: tpl.value || null, rounds: 2, lang: lang.value, merged: true })
    gen.value = r
    genRound.value = r.final.round
    merged.value = r.final.guard.merged_text ?? ''
  } catch (e) {
    if (!notConfigured(e)) genError.value = errorText(e)
  } finally { busy.value = false }
}
async function check(): Promise<void> {
  if (!paste.value.trim() || !target.value) return
  busy.value = true
  genError.value = ''
  try {
    const body: Record<string, unknown> = { text: paste.value, device: target.value, template: tpl.value || null, lang: lang.value, merged: true }
    guard.value = await post<Guard>('/guard', body)
    merged.value = guard.value.merged_text ?? ''
  } catch (e) { genError.value = errorText(e) } finally { busy.value = false }
}
function editRecheck(): void {
  const g = shown.value
  if (!g) return
  paste.value = g.lines.filter((l) => l.status !== 'skip').map((l) => l.text).join('\n')
  mode.value = 'paste'
  guard.value = null
}
function handoff(): void {
  const dev = devices.value.find((d) => d.name === target.value)
  if (!dev || !merged.value) { flash(t('ask.handoffFail')); return }
  if (!saveHandoff({ device: dev.id, text: merged.value, profile: shown.value?.profile })) { flash(t('ask.handoffFail')); return }
  void router.push({ name: 'change', query: { device: String(dev.id), mode: 'paste', handoff: '1' } })
}
watch(mode, () => { genError.value = '' })
const tplTitle = (x: { id: string; title: Record<string, string> }) => pickLang(x.title, lang.value) || x.id

onMounted(async () => {
  await Promise.all([loadStatus(), loadBase()])
  if (!on.value) mode.value = 'paste'
})
watch(on, (v) => { if (!v) mode.value = 'paste' })
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.home') }}</span><span class="sep">/</span><span>{{ $t('nav.ask') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('ask.title') }}</h1>
          <p class="ph-sub">{{ $t('ask.sub') }}</p>
        </div>
      </div>

      <div v-if="stError" class="notice err"><Icon name="err" /><div class="grow">{{ stError }}</div><button class="btn btn-sm" type="button" @click="loadStatus">{{ $t('c.retry') }}</button></div>
      <div v-else-if="!st" class="empty"><p>{{ $t('c.loading') }}</p></div>

      <!-- ===================== AI 已配置 ===================== -->
      <template v-else-if="on">
        <section class="panel" aria-label="AI interface" data-testid="ask-on">
          <div class="aistrip">
            <span class="it"><Icon name="spark" small />{{ $t('ask.iface') }} <b>{{ st.provider }}</b></span>
            <span class="it"><Icon name="cpu" small />{{ $t('ask.mAsk') }} <b class="mono">{{ st.models.ask }}</b></span>
            <span class="it"><Icon name="cpu" small />{{ $t('ask.mGen') }} <b class="mono">{{ st.models.generate }}</b></span>
            <span class="it"><Icon name="sanitize" small />{{ $t('ask.sanitize') }} <span class="tag t-teal">{{ $t('ask.alwaysOn') }}</span></span>
            <router-link class="ml-auto small" :to="{ name: 'ai-settings' }">{{ $t('ask.aiSettings') }} →</router-link>
          </div>
          <div class="rule">
            <div><span class="n ai">AI</span><div><b>{{ $t('ask.r1') }}</b><span>{{ $t('ask.r1d') }}</span></div></div>
            <div><span class="n code">✓</span><div><b>{{ $t('ask.r2') }}</b><span>{{ $t('ask.r2d') }}</span></div></div>
            <div><span class="n code"><Icon name="sanitize" small /></span><div><b>{{ $t('ask.r3') }}</b><span>{{ $t('ask.r3d') }}</span> <button class="link-btn small" type="button" :disabled="!lastSent" data-testid="ask-sent-last" @click="sentOpen = lastSent">{{ $t('ask.seeLast') }}</button></div></div>
          </div>
        </section>

        <div class="tabs main-tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="tab === 'ask'" data-testid="ask-tab-ask" @click="tab = 'ask'"><Icon name="chat" small /><span>{{ $t('ask.tabAsk') }}</span></button>
          <button type="button" role="tab" :aria-selected="tab === 'gen'" data-testid="ask-tab-gen" @click="tab = 'gen'"><Icon name="shield" small /><span>{{ $t('ask.tabGen') }}</span></button>
        </div>

        <div v-if="tab === 'ask'" class="aw">
          <section class="panel thread" aria-label="Conversation">
            <div class="scope">
              <span class="k">{{ $t('ask.scope') }}</span>
              <span class="row wrap" style="gap: 6px">
                <button v-for="d in devices" :key="d.id" type="button" class="scopechip" :aria-pressed="allScope || scope.includes(d.name)" @click="toggleScope(d.name)"><DevChip :name="d.name" :vendor="d.vendor" /></button>
              </span>
              <span class="k ml-auto">{{ $t('ask.latestNote') }}</span>
            </div>
            <div v-if="!turns.length" class="empty" style="padding: 36px 16px"><Icon name="chat" /><h3>{{ $t('ask.emptyTitle') }}</h3><p>{{ $t('ask.emptyText') }}</p></div>
            <div v-for="tn in turns" :key="tn.id" class="qa" :data-testid="`ask-turn-${tn.id}`">
              <div class="q">
                <span class="who">{{ $t('ask.q') }}</span>
                <div class="txt">{{ tn.question }}</div>
                <div v-if="tn.res?.answer" class="vsum">
                  <span v-if="stmtCounts(tn.res.answer.statements).passed" class="vs ok">{{ $t('ask.cPassed', { n: stmtCounts(tn.res.answer.statements).passed }) }}</span>
                  <span v-if="stmtCounts(tn.res.answer.statements).corrected" class="vs fix">{{ $t('ask.cCorrected', { n: stmtCounts(tn.res.answer.statements).corrected }) }}</span>
                  <span v-if="stmtCounts(tn.res.answer.statements).unverifiable" class="vs na">{{ $t('ask.cNa', { n: stmtCounts(tn.res.answer.statements).unverifiable }) }}</span>
                </div>
              </div>
              <div v-if="tn.busy" class="astep small muted">{{ $t('ask.thinking') }}</div>
              <div v-if="tn.error" class="notice err astep"><Icon name="err" small /><div class="grow">{{ tn.error }}</div></div>
              <template v-if="tn.res">
                <!-- 1 -->
                <div class="astep">
                  <div class="astep-h"><span class="sn">1</span><span>{{ $t('ask.s1') }}</span><span class="by"><span class="ailabel"><Icon name="spark" small />AI</span> <span class="faint small">{{ $t('ask.s1by') }}</span></span></div>
                  <div v-for="(a, i) in tn.res.attempts.filter((x) => x.error)" :key="`e${i}`" class="rejected"><span class="vs bad">{{ $t('ask.rejected') }}</span><code>{{ a.query }}</code></div>
                  <div v-if="tn.res.query_text" class="gq" data-testid="ask-query"><template v-for="(p, k) in queryParts(tn.res.query_text)" :key="k"><span :class="p.c">{{ p.s }}</span></template></div>
                  <div v-else class="notice warn"><Icon name="warn" small /><div class="grow">{{ $t('ask.queryInvalid') }}</div></div>
                </div>
                <!-- 2 -->
                <div v-if="tn.res.result" class="astep">
                  <div class="astep-h"><span class="sn">2</span><span>{{ $t('ask.s2') }}</span><span class="by"><span class="tag t-teal">{{ $t('ask.byCode') }}</span> <span class="faint small">{{ $t('ask.nRows', { n: tn.res.result.count }) }}<template v-if="tn.res.result.truncated"> · {{ $t('ask.truncated', { n: tn.res.result.rows.length }) }}</template></span></span></div>
                  <div class="rtbl">
                    <table class="tbl compact" data-testid="ask-result">
                      <thead><tr><th style="width: 34px">#</th><th>{{ $t('ask.object') }}</th><th v-for="c in tn.res.result.columns" :key="c.field">{{ c.field }}</th><th>{{ $t('ask.device') }}</th></tr></thead>
                      <tbody>
                        <tr v-for="r in tn.res.result.rows.slice(0, 50)" :key="r.n" :class="{ 'is-cite': selCite?.turn === tn.id && selCite?.n === r.n }" style="cursor: pointer" @click="pickCite(tn.id, r.n)">
                          <td><span class="cite"><b>{{ r.n }}</b></span></td>
                          <td class="mono" :title="r.node">{{ r.label }}</td>
                          <td v-for="c in tn.res.result.columns" :key="c.field" class="mono">
                            <template v-for="v in [cellShow(r.cells[c.field])]" :key="0">
                              <span v-if="v.kind === 'def'" class="dv" :data-k="$t('src.default')">{{ v.text }}</span>
                              <span v-else-if="v.kind === 'secret'"><Icon name="lock" small />{{ r.cells[c.field].value ? $t('ask.configured') : $t('ask.notConfigured') }}</span>
                              <span v-else :class="{ faint: v.kind === 'none' }">{{ v.text }}</span>
                            </template>
                          </td>
                          <td><DevChip :name="r.device" :vendor="devices.find((d) => d.name === r.device)?.vendor" /></td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-if="tn.res.result.rows.length > 50" class="small faint" style="padding: 6px 10px">{{ $t('ask.moreRows', { n: tn.res.result.rows.length - 50 }) }}</div>
                  </div>
                </div>
                <!-- 3 -->
                <div v-if="tn.res.answer" class="astep">
                  <div class="astep-h"><span class="sn">3</span><span>{{ $t('ask.s3') }}</span><span class="by"><span class="ailabel"><Icon name="spark" small />AI</span> <span class="faint small">{{ $t('ask.s3by') }}</span></span></div>
                  <div class="aiblk answer" data-testid="ask-answer">
                    <template v-for="(s, i) in tn.res.answer.statements" :key="i"><span class="cl" :class="stmtCls(s.status)" :title="stLabel(s.status)" :data-status="s.status">{{ s.text }}</span><sup v-for="c in s.cites" :key="c" class="cn" :class="{ bad: s.status === 'corrected' }" @click="pickCite(tn.id, c)">{{ c }}</sup>{{ ' ' }}</template>
                  </div>
                  <div v-if="tn.res.answer.statements.some((s) => s.corrected_text)" class="fixed" data-testid="ask-fixed">
                    <div class="fh"><span class="vs fix">{{ $t('ask.corrected') }}</span>{{ $t('ask.correctedBy') }}</div>
                    <template v-for="(s, i) in tn.res.answer.statements.filter((x) => x.corrected_text)" :key="i">{{ s.corrected_text }}<sup v-for="c in s.cites" :key="c" class="cn" @click="pickCite(tn.id, c)">{{ c }}</sup>{{ ' ' }}</template>
                  </div>
                  <details class="claims" :open="tn.res.answer.statements.some((s) => s.status !== 'passed')">
                    <summary><Icon name="chevR" small class="chev" />{{ $t('ask.checkDetails') }}<span class="faint">· {{ $t('ask.nStatements', { n: tn.res.answer.statements.length }) }}</span></summary>
                    <table class="tbl compact" data-testid="ask-claims">
                      <thead><tr><th>{{ $t('ask.statement') }}</th><th>{{ $t('ask.cites') }}</th><th>{{ $t('ask.result') }}</th><th>{{ $t('ask.basis') }}</th></tr></thead>
                      <tbody>
                        <tr v-for="(s, i) in tn.res.answer.statements" :key="i">
                          <td>{{ s.text }}</td>
                          <td class="nowrap"><template v-if="s.cites.length"><span v-for="c in s.cites" :key="c" class="cite" :class="{ bad: s.status === 'corrected' }" @click="pickCite(tn.id, c)"><b>{{ c }}</b></span></template><span v-else class="faint">—</span></td>
                          <td><span class="vs" :class="s.status === 'corrected' ? 'fix' : stmtCls(s.status)">{{ stLabel(s.status) }}</span></td>
                          <td class="small muted">
                            <div v-for="(f, k) in s.facts" :key="k" :class="{ bad: !f.ok }">#{{ f.row }} {{ factText(f) }}</div>
                            <div v-if="s.count !== null && s.count !== undefined">{{ $t('ask.countBasis', { claimed: String(s.count), n: tn.res.result?.count ?? 0 }) }}</div>
                            <div v-if="s.status === 'unverifiable'">{{ $t('ask.naBasis') }}</div>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </details>
                </div>
                <div class="afoot">
                  <span><Icon name="sanitize" small />{{ $t('ask.sentSanitized') }}</span>
                  <span><Icon name="spark" small />{{ tn.res.ai.model }} · {{ $t('ask.calls', { n: tn.res.ai.calls }) }} · {{ tn.res.ai.tokens_in + tn.res.ai.tokens_out }} tokens · {{ (tn.res.ai.ms / 1000).toFixed(1) }} s</span>
                  <span class="ml-auto"><button class="link-btn" type="button" data-testid="ask-sent" @click="sentOpen = { sent: tn.res.sent, q: tn.res.question_sent }">{{ $t('ask.seeSent') }}</button> · <router-link :to="{ name: 'ai-settings' }">{{ $t('ask.callLog') }}</router-link></span>
                </div>
              </template>
            </div>
            <div class="composer">
              <div class="box">
                <textarea v-model="question" class="textarea" rows="2" :placeholder="$t('ask.askPh')" data-testid="ask-input" @keydown.enter.exact.prevent="ask" />
                <button class="btn btn-primary" type="button" :disabled="!question.trim()" data-testid="ask-submit" @click="ask"><Icon name="send" small /><span>{{ $t('ask.askBtn') }}</span></button>
              </div>
              <div class="sugg"><button v-for="s in SUGG" :key="s" type="button" @click="question = $t(s)">{{ $t(s) }}</button></div>
            </div>
          </section>

          <aside class="panel side-sticky evp" aria-label="Evidence" data-testid="ask-evidence">
            <div class="panel-h"><h2>{{ $t('ask.evidence') }}</h2><span class="meta">{{ $t('ask.evHint') }}</span></div>
            <div v-if="!selRow" class="panel-b"><div class="empty"><Icon name="graph" /><p>{{ $t('ask.evEmpty') }}</p></div></div>
            <div v-else class="panel-b stack" style="gap: 12px">
              <div>
                <div class="ev-h"><DevChip :name="selRow.device" :vendor="devices.find((d) => d.name === selRow!.device)?.vendor" /><span class="tag">{{ terms.name(selRow.schema) }}</span><span class="cite" style="margin-left: auto"><b>{{ selRow.n }}</b>{{ $t('ask.cite') }}</span></div>
                <div class="ev-path" :title="selRow.node">{{ terms.describe(selRow.node) }}</div>
              </div>
              <div>
                <div class="section-t">{{ $t('ask.attrs') }}</div>
                <table class="tbl compact"><tbody>
                  <tr v-for="(c, f) in selRow.cells" :key="f">
                    <td class="mono" style="color: var(--ink-2)">{{ f }}</td>
                    <td class="mono"><template v-for="v in [cellShow(c)]" :key="0"><span v-if="v.kind === 'def'" class="dv" :data-k="$t('src.default')">{{ v.text }}</span><span v-else-if="v.kind === 'secret'">{{ c.value ? $t('ask.configured') : $t('ask.notConfigured') }}</span><span v-else :class="{ faint: v.kind === 'none' }">{{ v.text }}</span></template></td>
                    <td class="right"><span v-if="c.origin === 'default' || c.origin === 'explicit' || c.origin === 'derived'" class="tag" :class="c.origin">{{ $t(`src.${c.origin}`) }}</span></td>
                  </tr>
                </tbody></table>
              </div>
              <div>
                <div class="section-t">{{ $t('ask.configText') }}</div>
                <div v-if="evLines.length" class="code"><div v-for="l in evLines" :key="l.n" class="l" :class="{ 'is-hl': l.hl }"><span class="n">{{ l.n }}</span><span class="t"> {{ l.t }}</span></div><div v-if="hasDefault" class="l c-cmt"><span class="n" /><span class="t"> {{ $t('ask.defNoLine') }}</span></div></div>
                <p v-else class="small faint">{{ selRow.lines.length ? $t('ask.linesOnly', { lines: selRow.lines.join(', ') }) : $t('ask.defNoLine') }}</p>
              </div>
              <div v-if="selStatements.length">
                <div class="section-t">{{ $t('ask.howChecked') }}</div>
                <dl v-for="(s, i) in selStatements" :key="i" class="vcheck">
                  <dt>{{ $t('ask.aiStatement') }}</dt><dd>{{ s.text }}</dd>
                  <dt>{{ $t('ask.graphValue') }}</dt><dd class="mono">{{ s.facts.filter((f) => f.row === selRow!.n).map(factText).join('; ') || (s.count !== null && s.count !== undefined ? $t('ask.countBasis', { claimed: String(s.count), n: selTurn?.res?.result?.count ?? 0 }) : '—') }}</dd>
                  <dt>{{ $t('ask.result') }}</dt><dd><span class="vs" :class="s.status === 'corrected' ? 'fix' : stmtCls(s.status)">{{ stLabel(s.status) }}</span><div v-if="s.corrected_text" class="small muted mt8">{{ s.corrected_text }}</div><div v-else-if="s.status === 'unverifiable'" class="small muted mt8">{{ $t('ask.naBasis') }}</div></dd>
                </dl>
              </div>
              <div class="row wrap">
                <router-link v-if="selRow.device_id" class="btn btn-sm" :to="{ name: 'device-graph', params: { id: String(selRow.device_id) }, query: { node: selRow.node } }"><Icon name="graph" small />{{ $t('ask.openGraph') }}</router-link>
                <router-link v-if="selRow.device_id" class="btn btn-sm btn-ghost" :to="{ name: 'history', params: { id: String(selRow.device_id) }, query: { tab: 'object', obj: selRow.node } }"><Icon name="history" small />{{ $t('ask.objHistory') }}</router-link>
              </div>
            </div>
          </aside>
        </div>
      </template>

      <!-- ===================== AI 未配置 ===================== -->
      <template v-else>
        <section class="panel off-hero" aria-label="AI not configured" data-testid="ask-off">
          <div>
            <span class="offbadge"><i /><span>{{ $t('ask.offBadge') }}</span></span>
            <h2>{{ $t('ask.offTitle') }}</h2>
            <p>{{ $t('ask.offText') }}</p>
            <div class="row wrap mt16" style="gap: 8px">
              <router-link class="btn btn-primary" :to="{ name: 'ai-settings' }" data-testid="ask-setup-ai"><Icon name="spark" small /><span>{{ $t('ask.setupAi') }}</span></router-link>
              <span class="small faint">{{ $t('ask.offNote') }}</span>
            </div>
          </div>
          <div>
            <h3>{{ $t('ask.altTitle') }}</h3>
            <div class="mt8">
              <router-link class="alt" :to="{ name: 'device-graph' }"><Icon name="graph" /><b>{{ $t('ask.alt1') }}</b><span>{{ $t('ask.alt1d') }}</span></router-link>
              <router-link class="alt" :to="{ name: 'export' }"><Icon name="table" /><b>{{ $t('ask.alt2') }}</b><span>{{ $t('ask.alt2d') }}</span></router-link>
              <router-link class="alt" :to="{ name: 'features' }"><Icon name="feature" /><b>{{ $t('ask.alt3') }}</b><span>{{ $t('ask.alt3d') }}</span></router-link>
              <a class="alt" href="#guard"><Icon name="shield" /><b>{{ $t('ask.alt4') }}</b><span>{{ $t('ask.alt4d') }}</span></a>
            </div>
          </div>
        </section>
        <div id="guard" class="tabs main-tabs" role="tablist">
          <button type="button" role="tab" aria-selected="false" disabled class="dis"><Icon name="chat" small /><span>{{ $t('ask.tabAskOff') }}</span></button>
          <button type="button" role="tab" aria-selected="true"><Icon name="shield" small /><span>{{ $t('ask.tabCheck') }}</span></button>
        </div>
      </template>

      <!-- ===================== 生成 / 校验 ===================== -->
      <template v-if="st && (!on || tab === 'gen')">
        <section class="panel" data-testid="gen-form">
          <div class="gform">
            <div class="field"><label>{{ $t('ask.target') }}</label>
              <select v-model="target" class="select" data-testid="gen-device">
                <option v-for="d in devices" :key="d.id" :value="d.name">{{ d.name }} · {{ d.profile }}</option>
              </select>
            </div>
            <div class="field"><label>{{ $t('ask.template') }}</label>
              <select v-model="tpl" class="select" data-testid="gen-template"><option value="">{{ $t('ask.noTemplate') }}</option><option v-for="x in templates" :key="x.id" :value="x.id">{{ tplTitle(x) }}</option></select>
            </div>
            <div v-if="on" class="field"><label>{{ $t('ask.mode') }}</label>
              <div class="seg" role="group"><button type="button" :aria-pressed="mode === 'ai'" data-testid="gen-mode-ai" @click="mode = 'ai'"><Icon name="spark" small />{{ $t('ask.modeAi') }}</button><button type="button" :aria-pressed="mode === 'paste'" data-testid="gen-mode-paste" @click="mode = 'paste'"><Icon name="file" small />{{ $t('ask.modePaste') }}</button></div>
            </div>
            <div v-else />
            <div />
            <template v-if="on && mode === 'ai'">
              <div class="field span-all"><label>{{ $t('ask.describe') }}</label><textarea v-model="request" class="textarea" rows="2" :placeholder="$t('ask.describePh')" data-testid="gen-request" /></div>
              <div><button class="btn btn-primary" type="button" :disabled="busy || !request.trim() || !target" data-testid="gen-run" @click="generate"><Icon name="spark" small />{{ busy ? $t('c.running') : $t('ask.genBtn') }}</button></div>
            </template>
            <template v-else>
              <div class="field span-all"><label>{{ $t('ask.pasteLabel') }}</label><textarea v-model="paste" class="textarea mono" rows="6" :placeholder="$t('ask.pastePh')" data-testid="guard-input" /></div>
              <div><button class="btn btn-primary" type="button" :disabled="busy || !paste.trim() || !target" data-testid="guard-run" @click="check"><Icon name="shield" small />{{ busy ? $t('c.running') : $t('ask.checkBtn') }}</button></div>
            </template>
          </div>
          <p v-if="!on || mode === 'paste'" class="small faint form-note">{{ devices.length ? $t('ask.pasteNote') : $t('ask.pasteNoDevices') }}</p>
        </section>
        <div v-if="genError" class="notice err mt12" data-testid="gen-error"><Icon name="err" /><div class="grow">{{ genError }}</div></div>
        <GuardResult
          v-if="shown" :g="shown" :ai="on && mode === 'ai'" :busy="busy"
          :rounds="on && mode === 'ai' ? gen?.rounds.map((r) => r.round) : undefined" :round="genRound"
          @round="(n) => (genRound = n)" @regen="generate" @edit="editRecheck" @handoff="handoff" @copy="copy"
        />
        <div v-if="on && mode === 'ai' && gen" class="afoot" style="margin-left: 0">
          <span><Icon name="sanitize" small />{{ $t('ask.sentSanitized') }}</span>
          <span><Icon name="spark" small />{{ gen.ai.model }} · {{ $t('ask.calls', { n: gen.ai.calls }) }} · {{ gen.ai.tokens_in + gen.ai.tokens_out }} tokens</span>
          <span class="ml-auto"><button class="link-btn" type="button" @click="sentOpen = { sent: gen.sent, q: gen.request_sent }">{{ $t('ask.seeSent') }}</button></span>
        </div>
      </template>
    </div>

    <!-- 发送内容 -->
    <div v-if="sentOpen" class="modal-back" @click.self="sentOpen = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(860px, 100%)" data-testid="ask-sent-dialog">
        <div class="modal-h"><h2>{{ $t('ask.sentTitle') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="sentOpen = null"><Icon name="x" /></button></div>
        <div class="modal-b stack" style="gap: 12px">
          <div class="notice info"><Icon name="info" /><div>{{ $t('ask.sentInfo') }}</div></div>
          <div><div class="section-t">{{ $t('ask.sentQuestion') }}</div><pre class="block">{{ sentOpen.q }}</pre></div>
          <div v-for="(s, i) in sentOpen.sent" :key="i">
            <div class="section-t">{{ $t('ask.sentStep', { n: i + 1, step: s.step }) }}</div>
            <details><summary class="small muted">{{ $t('ask.sentSystem') }}</summary><pre class="block">{{ s.system }}</pre></details>
            <pre class="block">{{ s.prompt }}</pre>
            <template v-if="s.reply"><div class="small muted">{{ $t('ask.sentReply') }}</div><pre class="block aiblk">{{ s.reply }}</pre></template>
          </div>
        </div>
        <div class="modal-f"><button class="btn" type="button" @click="sentOpen = null">{{ $t('c.close') }}</button></div>
      </div>
    </div>
    <div v-if="toast" class="m5-toast" role="status">{{ toast }}</div>
  </main>
</template>

<style scoped>
.aistrip { display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: center; padding: 9px 14px; font-size: 12.5px; color: var(--ink-2); }
.aistrip b { color: var(--ink); font-weight: 600; }
.aistrip .it { display: inline-flex; align-items: center; gap: 6px; }
.aistrip .it :deep(.ico) { color: var(--ink-3); }
.rule { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--line); }
.rule > div { padding: 10px 14px; border-left: 1px solid var(--line); display: flex; gap: 10px; align-items: flex-start; font-size: 12.5px; color: var(--ink-2); }
.rule > div:first-child { border-left: 0; }
.rule .n { width: 22px; height: 22px; border-radius: 50%; flex: none; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); }
.rule .n.ai { background: var(--ai-soft); color: var(--ai-ink); border: 1px solid var(--ai-line); }
.rule .n.code { background: var(--teal-soft); color: var(--teal-ink); border: 1px solid var(--teal-line); }
.rule b { color: var(--ink); display: block; margin-bottom: 2px; }
.main-tabs { margin: 14px 0 12px; }
.main-tabs .dis { opacity: .5; cursor: not-allowed; }
.aw { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 12px; align-items: start; }
.side-sticky { position: sticky; top: 0; max-height: 92vh; overflow: auto; }
.thread { display: flex; flex-direction: column; }
.scope { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); font-size: 12.5px; }
.scope .k { color: var(--ink-3); }
.scopechip { border: 1px solid var(--line-strong); border-radius: 5px; background: var(--surface); padding: 2px 6px; cursor: pointer; font: inherit; color: var(--ink); }
.scopechip[aria-pressed="false"] { opacity: .5; border-style: dashed; }
.qa { border-bottom: 1px solid var(--line); padding: 14px 16px 16px; }
.q { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.q .who { width: 26px; height: 26px; border-radius: 50%; background: var(--blue-soft); color: var(--blue-ink); display: inline-flex; align-items: center; justify-content: center; flex: none; font: 700 11px var(--font-ui); }
.q .txt { font-size: 14px; font-weight: 600; padding-top: 2px; flex: 1; min-width: 200px; }
.q .vsum { flex: none; display: flex; gap: 4px; flex-wrap: wrap; }
.astep { margin: 12px 0 0 36px; }
.astep-h { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-2); font-weight: 600; margin-bottom: 6px; flex-wrap: wrap; }
.astep-h .sn { width: 18px; height: 18px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font: 700 10.5px var(--font-ui); background: var(--surface-3); color: var(--ink-2); }
.astep-h .by { margin-left: auto; font-weight: 400; }
.gq { font: 12px/1.65 var(--font-mono); background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: 7px 10px; white-space: pre-wrap; color: var(--ink); }
.gq .k { color: var(--blue-ink); font-weight: 600; }
.gq .s { color: var(--teal-ink); }
.rejected { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; font-size: 12px; }
.rejected code { text-decoration: line-through; color: var(--ink-3); overflow-wrap: anywhere; }
.rtbl { border: 1px solid var(--line); border-radius: 6px; overflow: auto; max-height: 360px; }
.rtbl tr.is-cite td { background: var(--hl-line); }
.answer { font-size: 13.5px; line-height: 1.75; }
.answer .cl { border-radius: 3px; padding: 1px 0; }
.answer .cl.bad { text-decoration: line-through; text-decoration-color: var(--red); color: var(--ink-3); }
.answer .cl.na { color: var(--ink-2); font-style: italic; }
.answer .cl:hover { background: color-mix(in srgb, var(--blue-soft) 70%, transparent); }
.fixed { margin-top: 8px; padding: 8px 10px; border: 1px solid var(--amber-line); background: color-mix(in srgb, var(--amber-soft) 60%, var(--surface)); border-radius: 6px; font-size: 13.5px; line-height: 1.7; }
.fixed .fh { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--amber-ink); font-weight: 600; margin-bottom: 2px; flex-wrap: wrap; }
.claims { margin-top: 10px; border: 1px solid var(--line); border-radius: 6px; }
.claims summary { cursor: pointer; padding: 7px 10px; font-size: 12px; color: var(--ink-2); display: flex; gap: 8px; align-items: center; list-style: none; }
.claims summary::-webkit-details-marker { display: none; }
.claims summary .chev { transition: transform .15s; }
.claims[open] summary .chev { transform: rotate(90deg); }
.claims .tbl td { vertical-align: top; font-size: 12.5px; }
.claims .bad { color: var(--red-ink); }
.afoot { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; margin: 10px 0 0 36px; font-size: 11.5px; color: var(--ink-3); }
.afoot :deep(.ico) { width: 12px; height: 12px; }
.afoot > span { display: inline-flex; align-items: center; gap: 5px; }
.composer { padding: 12px 14px; border-top: 1px solid var(--line); background: var(--surface-2); border-radius: 0 0 var(--r-panel) var(--r-panel); }
.composer .box { display: flex; gap: 8px; align-items: flex-end; }
.composer textarea { min-height: 38px; flex: 1; }
.sugg { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.sugg button { border: 1px dashed var(--line-strong); background: var(--surface); color: var(--ink-2); border-radius: 12px; height: 24px; padding: 0 10px; font: inherit; font-size: 12px; cursor: pointer; }
.sugg button:hover { border-color: var(--blue); color: var(--blue-ink); }
.ev-h { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ev-path { font: 12px var(--font-mono); color: var(--ink-2); margin-top: 4px; overflow-wrap: anywhere; }
.evp .code { border: 1px solid var(--line); border-radius: 6px; max-height: 240px; overflow: auto; }
.vcheck { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 10px; font-size: 12.5px; padding: 10px; border-radius: 6px; background: var(--surface-2); border: 1px solid var(--line); margin: 0 0 8px; }
.vcheck dt { color: var(--ink-3); }
.vcheck dd { margin: 0; overflow-wrap: anywhere; }
.gform { display: grid; grid-template-columns: 240px 260px auto minmax(0, 1fr); gap: 12px; align-items: end; padding: 12px 14px; }
.gform .span-all { grid-column: 1 / -2; }
.gform .textarea { min-height: 54px; }
.form-note { padding: 0 14px 12px; margin: 0; }
.off-hero { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); }
.off-hero > div { padding: 20px 22px; }
.off-hero > div + div { border-left: 1px solid var(--line); }
.off-hero h2 { font-size: 17px; margin: 8px 0 6px; }
.off-hero p { color: var(--ink-2); max-width: 60ch; }
.alt { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 2px 10px; padding: 9px 0; border-top: 1px solid var(--line); text-decoration: none; color: var(--ink); }
.alt:first-of-type { border-top: 0; }
.alt:hover { text-decoration: none; }
.alt:hover b { text-decoration: underline; color: var(--blue-ink); }
.alt :deep(.ico) { width: 20px; height: 20px; color: var(--blue); grid-row: span 2; margin-top: 2px; }
.alt span { color: var(--ink-2); font-size: 12.5px; }
.offbadge { display: inline-flex; gap: 6px; align-items: center; height: 22px; padding: 0 9px; border-radius: 11px; border: 1px dashed var(--line-strong); color: var(--ink-2); font-size: 12px; }
.offbadge i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); display: inline-block; }
.modal pre.block { max-height: 300px; overflow: auto; white-space: pre-wrap; }
@media (max-width: 1400px) {
  .aw { grid-template-columns: minmax(0, 1fr) 340px; }
  .gform { grid-template-columns: 1fr 1fr; }
  .gform .span-all { grid-column: 1 / -1; }
}
@media (max-width: 1000px) { .aw, .off-hero, .rule { grid-template-columns: minmax(0, 1fr); } .off-hero > div + div { border-left: 0; border-top: 1px solid var(--line); } .side-sticky { position: static; } }
</style>
