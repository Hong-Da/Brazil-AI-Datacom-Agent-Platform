<script setup lang="ts">
/**
 * 配置检查项目工作区（REQ-031，预览 REQ-031/project.html）：左脚本与基线、中 CodeMirror 编辑器（边写边查）、右问题与模拟执行。
 * query.view 切换子页：reorder 按依赖重排、revisions 修订记录、diff 文本差异；query.script 是当前脚本。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import { api, del, errorText, get, post, put } from '@/api'
import { pickLang } from '@/i18n'
import { usePrefs } from '@/stores/prefs'
import { useTerms } from '@/stores/terms'
import { useProject } from '@/stores/project'
import ProjectSide from './check-projects/ProjectSide.vue'
import ScriptEditor from './check-projects/ScriptEditor.vue'
import IssuesPanel from './check-projects/IssuesPanel.vue'
import SimPanel from './check-projects/SimPanel.vue'
import ReorderPane from './check-projects/ReorderPane.vue'
import RevisionsPane from './check-projects/RevisionsPane.vue'
import DiffPane from './check-projects/DiffPane.vue'
import {
  aiFresh, gutterMarks, issuesByLine, Latest, mergeIssues, moveMarks, splitLines, squiggles, takeAiSnapshot, type AiSnapshot,
} from './check-projects/logic'
import type { AiRules, Category, CheckResult, Issue, Kind, Project, Revision, ScriptInfo, Severity } from './check-projects/types'
import '@/styles/req031.css'

const { t, locale } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})
const route = useRoute()
const router = useRouter()
const prefs = usePrefs()
const terms = useTerms()
// 只读成员（REQ-036）：可以查看、边写边查、对比，不能保存或修改设置
const proj = useProject()
const canWrite = computed(() => proj.canWrite)

const pid = computed(() => Number(route.params.id))
const view = computed(() => String(route.query.view || 'edit'))
const project = ref<Project | null>(null)
const loadErr = ref('')
const aiRules = ref<AiRules>({ configured: false, rules: [] })
const scripts = computed(() => project.value?.script_list ?? [])
const sid = ref<number | null>(null)
const cur = computed(() => scripts.value.find((s) => s.id === sid.value) ?? null)
const saved = ref('')
const draft = ref('')
const loadingScript = ref(false)
/** 切换脚本时保留的未保存内容 */
const drafts = ref(new Map<number, string>())
const dirty = computed(() => draft.value !== saved.value)
const dirtySet = computed(() => {
  const s = new Set(drafts.value.keys())
  if (sid.value !== null && dirty.value) s.add(sid.value)
  return s
})
const kind = computed<Kind>(() => cur.value?.kind ?? 'change')
const orderOn = computed(() => project.value?.order_check ?? true)
const aiActive = computed(() => aiRules.value.configured && !!project.value?.ai_check)

/* ---------------------------------------------------------------- 检查 */
const result = ref<CheckResult | null>(null)
const checking = ref(false)
const pending = ref(false)
const checkErr = ref('')
const aiSnap = ref<AiSnapshot | null>(null)
const aiBusy = ref(false)
const latest = new Latest()
let ctrl: AbortController | null = null
let timer = 0

async function runCheck(withAi = false): Promise<void> {
  if (sid.value === null) return
  window.clearTimeout(timer)
  ctrl?.abort()
  const c = new AbortController()
  ctrl = c
  const k = latest.next()
  const content = draft.value
  const id = sid.value
  checking.value = true
  pending.value = false
  checkErr.value = ''
  if (withAi) aiBusy.value = true
  try {
    const r = await api<CheckResult>(`/check-projects/${pid.value}/scripts/${id}/check`, {
      method: 'POST',
      signal: c.signal,
      body: JSON.stringify({
        content, kind: kind.value, order: orderOn.value, ai: withAi, ai_rules: project.value?.ai_rules ?? [],
        style: terms.style, lang: prefs.lang,
      }),
    })
    if (!latest.isLatest(k) || id !== sid.value) return
    result.value = r
    if (withAi) aiSnap.value = takeAiSnapshot(r, content)
    if (r.script.saved && cur.value) {
      cur.value.last_check = { errors: r.summary.errors, warnings: r.summary.warnings, infos: r.summary.infos, order: orderOn.value, kind: r.kind, at: new Date().toISOString() }
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    if (latest.isLatest(k)) checkErr.value = errorText(e)
  } finally {
    if (latest.isLatest(k)) { checking.value = false; aiBusy.value = false }
  }
}
function schedule(): void {
  pending.value = true
  window.clearTimeout(timer)
  timer = window.setTimeout(() => { void runCheck(false) }, 500)
}
watch(draft, (v, old) => { if (!loadingScript.value && v !== old) schedule() })

const selRules = computed(() => new Set(project.value?.ai_rules ?? []))
const issues = computed<Issue[]>(() =>
  mergeIssues(result.value, aiSnap.value, draft.value, kind.value, aiActive.value)
    .filter((x) => x.source !== 'ai' || !x.rule || selRules.value.has(x.rule)),
)
const aiStale = computed(() => aiActive.value && !!aiSnap.value && !aiFresh(aiSnap.value, draft.value, kind.value))
const marks = computed(() => gutterMarks(issues.value))
const sq = computed(() => squiggles(issues.value))
const moves = computed(() => moveMarks(result.value))
const live = computed(() => (result.value && result.value.script.id === sid.value ? { errors: result.value.summary.errors, warnings: result.value.summary.warnings } : null))
const orderApplicable = computed(() => kind.value === 'change' && result.value?.order?.applicable !== false)
const canReorder = computed(() => {
  if (kind.value !== 'change') return false
  const o = result.value?.order
  if (!o || !o.enabled) return true
  return !!o.reorder?.changed
})
const moveTitle = (a: number, b: number) => T('moveTitle', { a, b })

/* ---------------------------------------------------------------- 选中问题 */
const sel = ref<string | null>(null)
const hl = ref<number | null>(null)
const hlTick = ref(0)
const sevF = ref(new Set<Severity>())
const catF = ref(new Set<Category>())
function pick(x: Issue): void { sel.value = x.id; hl.value = x.line; hlTick.value++ }
function pickLine(n: number): void {
  const x = issuesByLine(issues.value).get(n)?.[0]
  if (!x) return
  sevF.value = new Set()
  catF.value = new Set()
  pick(x)
}
function gotoLine(n: number): void { sel.value = null; hl.value = n; hlTick.value++ }

/* ---------------------------------------------------------------- 加载 */
async function loadProject(): Promise<void> {
  loadErr.value = ''
  try {
    const [p, a] = await Promise.all([
      get<Project>(`/check-projects/${pid.value}`),
      get<AiRules>('/check-projects/ai-rules').catch(() => ({ configured: false, rules: [] })),
    ])
    project.value = p
    aiRules.value = a
    const want = Number(route.query.script)
    const first = p.script_list?.find((s) => s.id === want) ?? p.script_list?.[0] ?? null
    if (first && first.id !== sid.value) await openScript(first.id)
    else if (!first) { sid.value = null; result.value = null }
  } catch (e) { loadErr.value = errorText(e) }
}

async function openScript(id: number): Promise<void> {
  if (sid.value !== null && dirty.value) drafts.value.set(sid.value, draft.value)
  else if (sid.value !== null) drafts.value.delete(sid.value)
  loadingScript.value = true
  sid.value = id
  result.value = null
  aiSnap.value = null
  sel.value = null
  hl.value = null
  sevF.value = new Set()
  catF.value = new Set()
  try {
    const s = await get<ScriptInfo>(`/check-projects/${pid.value}/scripts/${id}`)
    saved.value = s.content ?? ''
    draft.value = drafts.value.get(id) ?? saved.value
    drafts.value.delete(id)
  } catch (e) { checkErr.value = errorText(e) } finally { loadingScript.value = false }
  if (String(route.query.script) !== String(id)) void router.replace({ query: { ...route.query, script: String(id) } })
  await runCheck(false)
}

function patchScript(s: ScriptInfo): void {
  const list = project.value?.script_list
  if (!list) return
  const i = list.findIndex((x) => x.id === s.id)
  const { content: _c, ...info } = s as ScriptInfo & { revision?: unknown }
  void _c
  if (i >= 0) list[i] = { ...list[i], ...info }
}

/* ---------------------------------------------------------------- 操作 */
const toast = ref('')
let toastTimer = 0
function flash(s: string): void { toast.value = s; window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => { toast.value = '' }, 2600) }
const busy = ref(false)

async function save(): Promise<void> {
  if (sid.value === null) return
  busy.value = true
  try {
    const content = draft.value
    const r = await put<ScriptInfo & { revision: Revision | null }>(`/check-projects/${pid.value}/scripts/${sid.value}`, { content, summary: result.value?.summary ?? null })
    saved.value = content
    patchScript(r)
    flash(r.revision ? T('savedRev', { n: r.revision.seq }) : T('noChange'))
    await runCheck(aiActive.value)
  } catch (e) { flash(errorText(e)) } finally { busy.value = false }
}

async function setKind(k: Kind): Promise<void> {
  if (!cur.value || cur.value.kind === k) return
  try {
    patchScript(await put<ScriptInfo>(`/check-projects/${pid.value}/scripts/${cur.value.id}`, { kind: k }))
    sel.value = null
    catF.value = new Set()
    flash(k === 'full' ? T('recheckedFull') : T('recheckedChange'))
    await runCheck(false)
  } catch (e) { flash(errorText(e)) }
}

async function patchProject(body: Record<string, unknown>): Promise<boolean> {
  try {
    const p = await put<Project>(`/check-projects/${pid.value}`, body)
    if (project.value) project.value = { ...p, script_list: p.script_list ?? project.value.script_list }
    return true
  } catch (e) { flash(errorText(e)); return false }
}
async function setOrder(v: boolean): Promise<void> {
  if (await patchProject({ order_check: v })) { sel.value = null; await runCheck(false) }
}
async function setAi(v: boolean): Promise<void> {
  if (await patchProject({ ai_check: v })) { if (v) await runCheck(true) }
}
async function toggleRule(id: string, on: boolean): Promise<void> {
  const cur2 = new Set(project.value?.ai_rules ?? [])
  if (on) cur2.add(id)
  else cur2.delete(id)
  await patchProject({ ai_rules: [...cur2] })
}
async function setBaseline(deviceId: number | null, versionId: number | null): Promise<void> {
  if (await patchProject({ device_id: deviceId, version_id: versionId })) {
    flash(T('baselineChanged'))
    await runCheck(false)
  }
}

/* 新建 / 改名 / 删除脚本 */
const showNew = ref(false)
const nsName = ref('')
const nsKind = ref<Kind>('change')
const nsErr = ref('')
function openNew(): void {
  nsName.value = `script-${scripts.value.length + 1}.txt`
  nsKind.value = project.value?.default_kind ?? 'change'
  nsErr.value = ''
  showNew.value = true
}
async function createScript(): Promise<void> {
  if (!nsName.value.trim()) return
  busy.value = true
  nsErr.value = ''
  try {
    let content = ''
    const p = project.value
    if (nsKind.value === 'full' && p?.device_id) {
      // 完整配置从基线设备的配置复制一份
      let vid = p.version_id
      if (vid === null) {
        const vs = (await get<{ versions: { id: number; latest: boolean; current?: boolean }[] }>(`/devices/${p.device_id}/versions`)).versions
        vid = (vs.find((v) => v.current) ?? vs.find((v) => v.latest) ?? vs[0])?.id ?? null
      }
      if (vid !== null) content = (await get<{ text: string }>(`/devices/${p.device_id}/versions/${vid}/text`)).text ?? ''
    } else if (nsKind.value === 'change') {
      content = (p?.device?.vendor || p?.device?.profile || '').toLowerCase().startsWith('cisco') ? 'configure terminal\n\nend\n' : 'system-view\n\ncommit\n'
    }
    const s = await post<ScriptInfo>(`/check-projects/${pid.value}/scripts`, { name: nsName.value.trim(), kind: nsKind.value, content })
    project.value?.script_list?.push({ ...s, content: undefined })
    if (project.value) project.value.scripts++
    showNew.value = false
    await openScript(s.id)
  } catch (e) { nsErr.value = errorText(e) } finally { busy.value = false }
}
async function renameScript(id: number, name: string): Promise<void> {
  try { patchScript(await put<ScriptInfo>(`/check-projects/${pid.value}/scripts/${id}`, { name })) } catch (e) { flash(errorText(e)) }
}
const delTarget = ref<ScriptInfo | null>(null)
async function deleteScript(): Promise<void> {
  const s = delTarget.value
  if (!s || !project.value?.script_list) return
  try {
    await del(`/check-projects/${pid.value}/scripts/${s.id}`)
    project.value.script_list = project.value.script_list.filter((x) => x.id !== s.id)
    project.value.scripts--
    drafts.value.delete(s.id)
    delTarget.value = null
    flash(T('scriptDeleted'))
    if (s.id === sid.value) {
      sid.value = null
      saved.value = draft.value = ''
      const next = project.value.script_list[0]
      if (next) await openScript(next.id)
      else { result.value = null; void router.replace({ query: { ...route.query, script: undefined } }) }
    }
  } catch (e) { flash(errorText(e)) }
}

/* 子页 */
function go(v: string, extra: Record<string, string | undefined> = {}): void {
  void router.push({ query: { script: sid.value === null ? undefined : String(sid.value), view: v === 'edit' ? undefined : v, ...extra } })
}
/** 重排采用 / 修订恢复后：编辑器换成新内容并重新检查 */
async function replaced(content: string, info?: ScriptInfo | null): Promise<void> {
  loadingScript.value = true
  saved.value = content
  draft.value = content
  loadingScript.value = false
  if (info) patchScript(info)
  else if (cur.value) {
    cur.value.lines = splitLines(content).length
    try { patchScript(await get<ScriptInfo>(`/check-projects/${pid.value}/scripts/${cur.value.id}`)) } catch { /* 计数稍后刷新 */ }
  }
  aiSnap.value = null
  await runCheck(false)
}
async function switchScript(id: number): Promise<void> { await openScript(id) }

/* 规则下拉 */
const ruleDd = ref<HTMLDetailsElement>()
function onDocClick(e: MouseEvent): void {
  if (ruleDd.value?.open && !ruleDd.value.contains(e.target as Node)) ruleDd.value.open = false
}
function onBeforeUnload(e: BeforeUnloadEvent): void { if (dirtySet.value.size) { e.preventDefault(); e.returnValue = '' } }
onMounted(() => {
  void loadProject()
  document.addEventListener('click', onDocClick)
  window.addEventListener('beforeunload', onBeforeUnload)
})
onBeforeUnmount(() => {
  ctrl?.abort()
  window.clearTimeout(timer)
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('beforeunload', onBeforeUnload)
})
onBeforeRouteLeave(() => (dirtySet.value.size ? window.confirm(T('leaveConfirm')) : true))
watch(() => route.params.id, (v, old) => { if (v && v !== old) { sid.value = null; drafts.value = new Map(); void loadProject() } })
watch(() => route.query.script, (v) => {
  const n = Number(v)
  if (v && n !== sid.value && scripts.value.some((s) => s.id === n)) void openScript(n)
})
// 显示风格或语言变化时，后端文字按新风格 / 语言重新渲染
watch(() => [terms.style, prefs.lang], () => { if (sid.value !== null) void runCheck(false) })
</script>

<template>
  <main class="main">
    <div class="page r31 ws-page">
      <div class="crumbs">
        <span>{{ proj.info?.name }}</span><span class="sep">/</span>
        <router-link :to="{ name: 'scripts' }">{{ $t('nav.scripts') }}</router-link><span class="sep">/</span>
        <template v-if="view !== 'edit' && project">
          <a href="#" @click.prevent="go('edit')">{{ project.name }}</a><span class="sep">/</span><span>{{ T(`view.${view}`) }}</span>
        </template>
        <span v-else>{{ project?.name }}</span>
      </div>

      <div v-if="loadErr" class="notice err"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="loadProject">{{ $t('c.retry') }}</button></div>
      <section v-else-if="!project" class="panel"><div class="empty">{{ $t('c.loading') }}</div></section>

      <template v-else-if="view === 'edit'">
        <div class="wsh">
          <h1 data-testid="cp-title">{{ project.name }}</h1>
          <span v-if="project.device" class="basechip" data-testid="cp-basechip">
            <DevChip :name="project.device.name" :vendor="project.device.vendor || project.device.profile" />
            <span>{{ project.device.profile }}</span>
            <b>{{ project.version_id === null ? T('latest') : (result?.baseline?.label || T('pinned')) }}</b>
          </span>
          <span v-else class="basechip">{{ T('noBaseline') }}</span>
          <span v-if="project.description" class="small faint">{{ project.description }}</span>
        </div>

        <div class="wsp">
          <ProjectSide
            :project="project" :scripts="scripts" :cur="sid" :dirty="dirtySet" :live="live"
            @select="openScript" @new="openNew" @rename="renameScript" @delete="(s) => (delTarget = s)" @baseline="setBaseline"
          />

          <section class="panel edp" style="display: flex; flex-direction: column; min-height: 0">
            <template v-if="cur">
              <div class="edbar">
                <span class="fn" data-testid="cp-fn">{{ cur.name }}</span>
                <span class="rev">{{ T('revN', { n: cur.revisions }) }}<template v-if="dirty">{{ T('unsavedSuffix') }}</template></span>
                <div class="seg type" role="group" :aria-label="T('scriptType')" data-testid="cp-kind">
                  <button type="button" :aria-pressed="kind === 'change'" :title="T('kindDesc.change')" data-kind="change" :disabled="!canWrite" @click="setKind('change')">{{ T('kind.change') }}</button>
                  <button type="button" :aria-pressed="kind === 'full'" :title="T('kindDesc.full')" data-kind="full" :disabled="!canWrite" @click="setKind('full')">{{ T('kind.full') }}</button>
                </div>
                <span class="grow" />
                <span v-if="checkErr" class="chk-state" style="color: var(--red-ink)" :title="checkErr"><Icon name="err" small /><span>{{ T('checkFailed') }}</span><button class="btn btn-xs" type="button" @click="runCheck(false)">{{ $t('c.retry') }}</button></span>
                <span v-else-if="checking || pending" class="chk-state run" aria-live="polite" data-testid="cp-state" data-state="run"><span class="spin" /><span>{{ aiBusy ? T('aiChecking') : T('checking') }}</span></span>
                <span v-else-if="result" class="chk-state ok" aria-live="polite" data-testid="cp-state" data-state="ok"><Icon name="ok" small /><span>{{ T('checkedMs', { n: result.ms }) }}</span></span>
                <button v-if="canWrite" class="btn btn-sm btn-primary" type="button" :disabled="busy" :title="T('saveTip')" data-testid="cp-save" @click="save"><Icon name="check" small /><span>{{ $t('c.save') }}</span></button>
              </div>
              <div class="edbar opts">
                <label class="tgl" :class="{ 'is-disabled': !orderApplicable }" :title="orderApplicable ? T('orderTip') : T('orderNa')" data-testid="cp-order">
                  <span class="switch"><input type="checkbox" :checked="orderOn && orderApplicable" :disabled="!orderApplicable || !canWrite" data-testid="cp-order-input" @change="setOrder(($event.target as HTMLInputElement).checked)"><span /></span>
                  <span>{{ T('orderCheck') }}</span>
                </label>
                <template v-if="aiRules.configured">
                  <span class="sep" />
                  <label class="tgl" :title="T('aiTip')" data-testid="cp-ai">
                    <span class="switch"><input type="checkbox" :checked="project.ai_check" :disabled="!canWrite" @change="setAi(($event.target as HTMLInputElement).checked)"><span /></span>
                    <Icon name="spark" small style="color: var(--ai)" /><span>{{ T('aiCheck') }}</span>
                  </label>
                  <details ref="ruleDd" class="dd" data-testid="cp-ai-rules">
                    <summary><span>{{ T('rules') }}</span> <b>{{ project.ai_rules.length }}/{{ aiRules.rules.length }}</b><Icon name="chevD" small /></summary>
                    <div class="dd-pop">
                      <div class="h">{{ T('rulesHead') }}</div>
                      <div v-if="!aiRules.rules.length" class="small faint" style="padding: 6px 4px">{{ T('noAiRules') }}</div>
                      <label v-for="r in aiRules.rules" :key="r.id">
                        <input type="checkbox" :checked="project.ai_rules.includes(r.id)" :disabled="!canWrite" @change="toggleRule(r.id, ($event.target as HTMLInputElement).checked)">
                        <span>{{ pickLang(r.title, String(locale)) }}</span><small>{{ r.id }}</small>
                      </label>
                      <div class="f"><Icon name="shield" /><span>{{ T('rulesFoot') }}</span></div>
                    </div>
                  </details>
                  <button v-if="aiActive" class="btn btn-sm" type="button" :disabled="aiBusy || !project.ai_rules.length" data-testid="cp-ai-run" @click="runCheck(true)"><Icon name="spark" small /><span class="wl">{{ T('aiRun') }}</span></button>
                </template>
                <span class="grow" />
                <button class="btn btn-sm" type="button" :disabled="!canReorder" :title="canReorder ? T('reorderTip') : T('reorderNa')" data-testid="cp-reorder" @click="go('reorder')"><Icon name="order" small /><span class="wl">{{ T('reorderBtn') }}</span></button>
                <button class="btn btn-sm" type="button" :title="T('view.revisions')" data-testid="cp-revisions" @click="go('revisions')"><Icon name="history" small /><span class="wl">{{ T('view.revisions') }}</span></button>
                <button class="btn btn-sm" type="button" :title="T('view.diff')" data-testid="cp-diff" @click="go('diff')"><Icon name="compare" small /><span class="wl">{{ T('compare') }}</span></button>
              </div>
              <ScriptEditor
                v-model="draft" :marks="marks" :moves="moves" :squiggles="sq" :hl="hl" :hl-tick="hlTick" :move-title="moveTitle"
                @pick-line="pickLine"
              />
              <div class="ed-foot">
                <span class="lg"><i style="background: var(--sq-err)" /><span>{{ T('sev.error') }}</span></span>
                <span class="lg"><i style="background: var(--sq-warn)" /><span>{{ T('sev.warning') }}</span></span>
                <span class="lg"><i style="background: var(--sq-info)" /><span>{{ T('sev.info') }}</span></span>
                <span v-if="aiRules.configured" class="lg"><i style="box-shadow: inset 0 0 0 2px var(--ink-3)" /><span>{{ T('legendAi') }}</span></span>
                <span v-if="moves.size" class="lg"><b style="color: var(--mv); font-size: 11px">↓n</b><span>{{ T('legendMove') }}</span></span>
                <span class="grow" style="flex: 1" />
                <span>{{ T('autoCheck') }}</span>
              </div>
            </template>
            <div v-else class="empty" data-testid="cp-no-script">
              <h3>{{ T('noScripts') }}</h3>
              <button v-if="canWrite" class="btn btn-primary" type="button" @click="openNew"><Icon name="plus" small /><span>{{ T('newScript') }}</span></button>
            </div>
          </section>

          <div class="col col-r">
            <IssuesPanel
              v-model:sev="sevF" v-model:cat="catF"
              :issues="issues" :kind="kind" :ai-active="aiActive" :ai-info="aiSnap?.info ?? null" :ai-stale="aiStale" :ai-rules="aiRules.rules"
              :order-off="kind === 'change' && !orderOn" :sel="sel"
              @pick="pick" @reorder="go('reorder')"
            />
            <SimPanel :result="result" :kind="kind" @diff-baseline="go('diff', { a: 'base', b: `script:${sid}` })" @line="gotoLine" />
          </div>
        </div>
      </template>

      <ReorderPane
        v-else-if="view === 'reorder' && cur && !loadingScript" :pid="pid" :script="cur" :content="draft" :dirty="dirty"
        @back="go('edit')" @adopted="(c, s) => replaced(c, s)" @revisions="go('revisions')" @diff="(a, b) => go('diff', { a, b })"
      />
      <RevisionsPane
        v-else-if="view === 'revisions' && cur && !loadingScript" :pid="pid" :script="cur" :scripts="scripts"
        @switch="switchScript" @restored="(c, s) => replaced(c, s)" @diff="(a, b) => go('diff', { a, b })" @back="go('edit')"
      />
      <DiffPane
        v-else-if="view === 'diff' && !loadingScript" :project="project" :scripts="scripts" :cur="sid" :draft="dirty ? draft : null"
        :init-a="(route.query.a as string) || ''" :init-b="(route.query.b as string) || ''" @back="go('edit')"
      />
      <section v-else class="panel"><div v-if="loadingScript" class="empty">{{ $t('c.loading') }}</div><div v-else class="empty">{{ T('noScripts') }} <a href="#" @click.prevent="go('edit')">{{ T('backWs') }}</a></div></section>
    </div>

    <div v-if="showNew" class="modal-back r31" data-testid="cp-new-script-modal" @click.self="showNew = false" @keydown.esc="showNew = false">
      <div class="modal sm" role="dialog" aria-modal="true" aria-labelledby="mNewT">
        <div class="modal-h"><h2 id="mNewT">{{ T('newScript') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="showNew = false"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 12px">
          <div class="field"><label for="nsName">{{ T('fileName') }}</label><input id="nsName" v-model="nsName" class="input mono" data-testid="cp-ns-name" @keydown.enter="createScript"></div>
          <div class="field">
            <span class="field-label">{{ T('type') }}</span>
            <div class="radio-cards">
              <label class="radio-card"><input v-model="nsKind" type="radio" value="change" data-testid="cp-ns-change"><div><div class="rc-t">{{ T('kind.change') }}<template v-if="project?.default_kind === 'change'">{{ T('projectDefault') }}</template></div><div class="rc-d">{{ T('nsChangeDesc') }}</div></div></label>
              <label class="radio-card"><input v-model="nsKind" type="radio" value="full" data-testid="cp-ns-full"><div><div class="rc-t">{{ T('kind.full') }}<template v-if="project?.default_kind === 'full'">{{ T('projectDefault') }}</template></div><div class="rc-d">{{ project?.device_id ? T('nsFullDesc') : T('nsFullBlank') }}</div></div></label>
            </div>
          </div>
          <div v-if="nsErr" class="notice err"><Icon name="err" /><div>{{ nsErr }}</div></div>
        </div>
        <div class="modal-f"><button class="btn" type="button" @click="showNew = false">{{ $t('c.cancel') }}</button><button class="btn btn-primary" type="button" :disabled="busy" data-testid="cp-ns-create" @click="createScript">{{ T('createScript') }}</button></div>
      </div>
    </div>

    <div v-if="delTarget" class="modal-back r31" @click.self="delTarget = null" @keydown.esc="delTarget = null">
      <div class="modal sm" role="dialog" aria-modal="true" aria-labelledby="mDelT">
        <div class="modal-h"><h2 id="mDelT">{{ T('deleteScript') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="delTarget = null"><Icon name="x" /></button></div>
        <div class="modal-b"><p>{{ T('deleteConfirm', { name: delTarget.name }) }}</p></div>
        <div class="modal-f"><button class="btn" type="button" @click="delTarget = null">{{ $t('c.cancel') }}</button><button class="btn btn-danger-solid" type="button" data-testid="cp-del-ok" @click="deleteScript">{{ T('deleteScript') }}</button></div>
      </div>
    </div>

    <div v-if="toast" class="toast" role="status" data-testid="cp-toast">{{ toast }}</div>
  </main>
</template>

<style scoped>
.ws-page { padding-top: 12px; padding-bottom: 20px; }
.col.col-r > .iss-p { flex: 1.25; }
.col.col-r > .sim { flex: 1; }
.modal.sm { width: min(480px, 100%); }
@media (max-width: 1366px) {
  .edbar .wl { display: none; }
}
</style>
