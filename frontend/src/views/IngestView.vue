<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError, download, errorText, get, post, waitTask, type Task } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import {
  DOMAINS, STAGES, TASK_TAG, canApply, durationSec, fmtBytes, fmtDuration, fmtTime, groupByDir, ingestBody, ingestStats,
  isImportPlan, parseIso, stageStates, validateIngest, type Extractor, type ImportPlan, type IngestForm, type IngestResult,
} from './ingest/logic'
import type { AiStatus } from './ai/logic'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const status = useStatus()

// ---------- 标签页 ----------
const tab = ref<'docs' | 'pkg'>(route.query.tab === 'pkg' ? 'pkg' : 'docs')
watch(tab, (v) => router.replace({ query: { ...route.query, tab: v === 'pkg' ? 'pkg' : undefined } }))

// ---------- 抽取规则、AI 状态、最近任务 ----------
const extractors = ref<Extractor[]>([])
const ai = ref<AiStatus | null>(null)
const tasks = ref<Task<IngestResult>[]>([])
const loading = ref(true)
const loadErr = ref('')

async function loadBase(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    const [ex, st] = await Promise.all([get<{ extractors: Extractor[] }>('/kb/extractors'), get<AiStatus>('/ai/status')])
    extractors.value = ex.extractors
    ai.value = st
    if (!form.rules && ex.extractors.length) form.rules = ex.extractors[0].name
    await loadTasks()
  } catch (e) {
    loadErr.value = errorText(e)
  } finally {
    loading.value = false
  }
}

const tasksErr = ref('')
async function loadTasks(): Promise<void> {
  tasksErr.value = ''
  try {
    tasks.value = (await get<{ tasks: Task<IngestResult>[] }>('/tasks?kind=ingest&limit=20')).tasks
    const live = tasks.value.find((x) => x.status === 'queued' || x.status === 'running')
    if (live && !current.value) follow(live)
  } catch (e) {
    tasksErr.value = errorText(e)
  }
}

// ---------- 新建任务 ----------
const form = reactive<IngestForm>({ doc_dir: '', rules: '', domains: [...DOMAINS], version: '', use_ai: false })
const aiOn = computed(() => !!ai.value?.configured)
const problems = ref<string[]>([])
const starting = ref(false)
const startErr = ref('')
const selRule = computed(() => extractors.value.find((x) => x.name === form.rules))

async function start(): Promise<void> {
  problems.value = validateIngest(form, aiOn.value)
  startErr.value = ''
  if (problems.value.length) return
  starting.value = true
  try {
    const { task_id } = await post<{ task_id: string }>('/kb/ingest', ingestBody(form))
    follow({ id: task_id, kind: 'ingest', status: 'queued', progress: 0, message: '', result: null, created_at: null, updated_at: null })
    void loadTasks()
  } catch (e) {
    startErr.value = e instanceof ApiError && e.status === 404 ? t('ingest.errDocDirMissing', { p: form.doc_dir.trim() }) : errorText(e)
  } finally {
    starting.value = false
  }
}

// ---------- 跟踪任务 ----------
const current = ref<Task<IngestResult> | null>(null)
let disposed = false
let followId = ''
const now = ref(Date.now())
const clock = window.setInterval(() => { now.value = Date.now() }, 1000)

function follow(task: Task<IngestResult>): void {
  current.value = task
  if (task.status === 'done' || task.status === 'failed') return
  const id = (followId = task.id)
  waitTask<IngestResult>(id, (x) => {
    if (disposed || followId !== id) throw new Error('stopped') // 离开页面或切换任务时停止轮询
    current.value = x
  }).then((x) => {
    if (x.status === 'done') void status.refresh()
    void loadTasks()
  }).catch(() => { /* 停止轮询或网络中断：最近任务列表里仍可重新查看 */ })
}

function newTask(): void {
  followId = ''
  current.value = null
}

const phase = computed<'form' | 'run' | 'done' | 'failed'>(() => {
  const s = current.value?.status
  if (!s) return 'form'
  return s === 'done' ? 'done' : s === 'failed' ? 'failed' : 'run'
})
const stages = computed(() => stageStates(current.value?.progress ?? 0, current.value?.status ?? ''))
const stats = computed(() => ingestStats(current.value?.result))
const elapsed = computed(() => {
  const c = current.value
  if (!c?.created_at) return null
  return phase.value === 'run' ? Math.max(0, Math.round((now.value - parseIso(c.created_at)) / 1000)) : durationSec(c.created_at, c.updated_at)
})

function saveResult(): void {
  const c = current.value
  if (!c?.result) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(c.result, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `ingest-${c.result.rules ?? 'result'}-${c.id}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function taskMeta(x: Task<IngestResult>): string {
  const time = fmtTime(x.created_at)
  if (x.status === 'done' && x.result) {
    const s = ingestStats(x.result)
    return t('ingest.taskMetaDone', { time, cards: s.cards.toLocaleString(), review: s.review.toLocaleString() })
  }
  if (x.status === 'failed') return `${time} · ${x.message || t('c.failed')}`
  return `${time} · ${x.progress}%`
}

// ---------- 知识库包 ----------
const exporting = ref(false)
const exportErr = ref('')
const kbVersion = computed(() => status.summary?.kb.version ?? '')
const exportName = computed(() => `lmesh-kb-${kbVersion.value || 'current'}.zip`)

async function doExport(): Promise<void> {
  exporting.value = true
  exportErr.value = ''
  try {
    await download('/kb/export', exportName.value)
  } catch (e) {
    exportErr.value = errorText(e)
  } finally {
    exporting.value = false
  }
}

const pkgFile = ref<File | null>(null)
const plan = ref<ImportPlan | null>(null)
const planErr = ref('')
const checking = ref(false)
const importing = ref(false)
const imported = ref<ImportPlan | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

async function sendPackage(dryRun: boolean): Promise<ImportPlan | null> {
  if (!pkgFile.value) return null
  const fd = new FormData()
  fd.append('file', pkgFile.value)
  try {
    return await post<ImportPlan>(`/kb/import?dry_run=${dryRun}`, fd)
  } catch (e) {
    // 校验不通过时后端返回 422，data 是计划（含 issues）
    if (e instanceof ApiError && isImportPlan(e.data)) return e.data
    const d = e instanceof ApiError ? (e.data as { detail?: string } | null) : null
    planErr.value = d?.detail ? `${errorText(e)}：${d.detail}` : errorText(e)
    return null
  }
}

async function pickFile(ev: Event): Promise<void> {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  pkgFile.value = f
  plan.value = null
  imported.value = null
  planErr.value = ''
  checking.value = true
  plan.value = await sendPackage(true)
  checking.value = false
}

async function doImport(): Promise<void> {
  importing.value = true
  planErr.value = ''
  const res = await sendPackage(false)
  importing.value = false
  if (!res) return
  if (res.applied) {
    imported.value = res
    plan.value = null
    pkgFile.value = null
    if (fileInput.value) fileInput.value.value = ''
    void status.refresh()
  } else {
    plan.value = res
  }
}

const errorIssues = computed(() => plan.value?.issues ?? [])

onMounted(() => {
  void loadBase()
  if (!status.summary) void status.refresh()
})
onBeforeUnmount(() => {
  disposed = true
  window.clearInterval(clock)
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.ingest') }}</h1>
          <p class="ph-sub">{{ $t('ingest.sub') }}</p>
        </div>
      </div>

      <div class="tabs" role="tablist">
        <button role="tab" :aria-selected="tab === 'docs'" data-testid="ingest-tab-docs" @click="tab = 'docs'">
          <Icon name="book" small /><span>{{ $t('ingest.tabDocs') }}</span>
        </button>
        <button role="tab" :aria-selected="tab === 'pkg'" data-testid="ingest-tab-pkg" @click="tab = 'pkg'">
          <Icon name="zip" small /><span>{{ $t('ingest.tabPkg') }}</span>
        </button>
      </div>

      <!-- =================== 产品文档 =================== -->
      <section v-if="tab === 'docs'">
        <div class="grid g-side collapse">
          <div class="stack">
            <div v-if="loading" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
            <div v-else-if="loadErr" class="panel">
              <div class="empty">
                <p>{{ loadErr }}</p>
                <button class="btn" data-testid="ingest-retry" @click="loadBase"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
              </div>
            </div>

            <!-- 新建任务 -->
            <div v-else-if="phase === 'form'" class="panel" data-testid="ingest-form">
              <div class="panel-h"><h2>{{ $t('ingest.newTask') }}</h2></div>
              <div class="panel-b">
                <div class="field">
                  <label for="ing-dir">{{ $t('ingest.docDir') }}</label>
                  <div class="srcbox">
                    <Icon name="folder" />
                    <input
                      id="ing-dir" v-model="form.doc_dir" class="input mono" :class="{ 'is-error': problems.includes('errDocDir') }"
                      :placeholder="$t('ingest.docDirPh')" data-testid="ingest-doc-dir" spellcheck="false"
                    >
                  </div>
                  <span class="hint">{{ $t('ingest.docDirHint') }}</span>
                </div>

                <div class="field mt16">
                  <span class="field-label">{{ $t('ingest.formats') }}</span>
                  <div class="fmt">
                    <div v-for="f in ['md', 'html', 'pdf', 'chm']" :key="f" class="fmt-card">
                      <div class="rc-t">{{ $t(`ingest.fmt_${f}`) }}</div>
                      <div class="rc-d">{{ $t(`ingest.fmt_${f}_d`) }}</div>
                    </div>
                  </div>
                </div>

                <div class="form-grid mt16">
                  <div class="field">
                    <label for="ing-rules">{{ $t('ingest.rules') }}</label>
                    <select id="ing-rules" v-model="form.rules" class="select mono" data-testid="ingest-rules" :class="{ 'is-error': problems.includes('errRules') }">
                      <option v-if="!extractors.length" value="" disabled>{{ $t('ingest.noRules') }}</option>
                      <option v-for="x in extractors" :key="x.name" :value="x.name">{{ x.title ? `${x.name} — ${x.title}` : x.name }}</option>
                    </select>
                    <span v-if="selRule" class="hint">
                      {{ $t('ingest.rulesHint', { file: `knowledge/extractors/${selRule.name}.yaml`, family: selRule.family || '—' }) }}
                      <template v-if="selRule.patches"> {{ $t('ingest.rulesPatches') }}</template>
                    </span>
                  </div>
                  <div class="field">
                    <label for="ing-ver">{{ $t('ingest.version') }}</label>
                    <input id="ing-ver" v-model="form.version" class="input mono" :placeholder="$t('ingest.versionPh')" data-testid="ingest-version">
                    <span class="hint">{{ $t('ingest.versionHint') }}</span>
                  </div>
                </div>

                <div class="field mt16">
                  <span class="field-label">{{ $t('ingest.channel') }}</span>
                  <div class="radio-cards ch">
                    <label class="radio-card">
                      <input v-model="form.use_ai" type="radio" :value="false" name="ch" data-testid="ingest-ch-rules">
                      <div><div class="rc-t">{{ $t('ingest.chRules') }}</div><div class="rc-d">{{ $t('ingest.chRulesD') }}</div></div>
                    </label>
                    <label class="radio-card" :class="{ 'ai-off-card': !aiOn }">
                      <input v-model="form.use_ai" type="radio" :value="true" name="ch" :disabled="!aiOn" data-testid="ingest-ch-ai">
                      <div>
                        <div class="rc-t">{{ $t('ingest.chAi') }}</div>
                        <div class="rc-d">
                          <template v-if="aiOn">{{ $t('ingest.chAiOn', { m: ai?.models.extract || '—' }) }}</template>
                          <template v-else>
                            {{ $t('ingest.chAiOff') }}
                            <router-link :to="{ name: 'ai-settings' }" data-testid="ingest-goto-ai">{{ $t('ingest.chAiLink') }}</router-link>
                          </template>
                        </div>
                      </div>
                    </label>
                  </div>
                </div>

                <div class="field mt16">
                  <span class="field-label">{{ $t('ingest.scope') }}</span>
                  <div class="row wrap" style="gap: 14px" data-testid="ingest-domains">
                    <label v-for="d in DOMAINS" :key="d" class="check">
                      <input v-model="form.domains" type="checkbox" :value="d"><span class="mono">{{ d }}</span>
                    </label>
                  </div>
                </div>

                <div v-if="problems.length || startErr" class="notice err mt16" data-testid="ingest-form-error">
                  <Icon name="err" />
                  <div class="grow small">
                    <div v-for="p in problems" :key="p">{{ $t(`ingest.${p}`) }}</div>
                    <div v-if="startErr">{{ startErr }}</div>
                  </div>
                </div>
              </div>
              <div class="panel-f">
                <span class="small faint">{{ $t('ingest.startHint') }}</span>
                <button class="btn btn-primary ml-auto" :disabled="starting" data-testid="ingest-start" @click="start">
                  <Icon name="play" small /><span>{{ $t('ingest.start') }}</span>
                </button>
              </div>
            </div>

            <!-- 抽取中 -->
            <div v-else-if="phase === 'run'" class="panel" data-testid="ingest-running">
              <div class="panel-h">
                <h2>{{ $t('ingest.running') }}</h2>
                <span class="meta">{{ $t('ingest.elapsed', { t: fmtDuration(elapsed) }) }}</span>
              </div>
              <div class="panel-b">
                <div class="row">
                  <div class="progress striped" style="flex: 1"><i :style="{ width: `${current?.progress ?? 0}%` }" /></div>
                  <b class="small">{{ current?.progress ?? 0 }}%</b>
                </div>
                <div class="stages mt12">
                  <div v-for="(s, i) in STAGES" :key="s" class="stage" :class="stages[i]">
                    <span class="no"><Icon v-if="stages[i] === 'done'" name="check" small /><template v-else>{{ i + 1 }}</template></span>
                    <div>
                      <div class="t">{{ $t(`ingest.stage_${s}`) }}</div>
                      <div class="d">{{ $t(`ingest.stage_${s}_d`) }}</div>
                      <div v-if="stages[i] === 'cur' && current?.message" class="d mono">{{ current.message }}</div>
                    </div>
                    <span class="c" />
                  </div>
                </div>
              </div>
              <div class="panel-f">
                <span class="small faint">{{ $t('ingest.leaveHint') }}</span>
              </div>
            </div>

            <!-- 失败 -->
            <div v-else-if="phase === 'failed'" class="panel" data-testid="ingest-failed">
              <div class="panel-h"><h2>{{ $t('ingest.failed') }}</h2><span class="meta">{{ fmtTime(current?.created_at) }}</span></div>
              <div class="panel-b">
                <div class="notice err"><Icon name="err" /><div class="grow small mono">{{ current?.message || $t('c.error') }}</div></div>
              </div>
              <div class="panel-f">
                <button class="btn btn-primary ml-auto" data-testid="ingest-new" @click="newTask"><Icon name="plus" small />{{ $t('ingest.newTask') }}</button>
              </div>
            </div>

            <!-- 完成 -->
            <div v-else class="panel" data-testid="ingest-done">
              <div class="panel-h">
                <h2>{{ $t('ingest.done', { r: current?.result?.rules ?? '' }) }}</h2>
                <span class="meta">{{ $t('ingest.took', { t: fmtDuration(elapsed) }) }}</span>
              </div>
              <div class="panel-b">
                <div class="sum" data-testid="ingest-summary">
                  <div>
                    <div class="k">{{ $t('ingest.sumCards') }}</div>
                    <div class="v">{{ stats.cards.toLocaleString() }}</div>
                    <div class="s">{{ $t('ingest.sumCardsS', { c: stats.commands.toLocaleString(), f: stats.files.toLocaleString() }) }}</div>
                  </div>
                  <div>
                    <div class="k">{{ $t('ingest.sumSame') }}</div>
                    <div class="v">{{ stats.unchanged.toLocaleString() }}</div>
                    <div class="s">{{ $t('ingest.sumSameS') }}</div>
                  </div>
                  <div>
                    <div class="k">{{ $t('ingest.sumReview') }}</div>
                    <div class="v" style="color: var(--amber-ink)">{{ stats.review.toLocaleString() }}</div>
                    <div class="s">{{ $t('ingest.sumReviewS', { a: stats.added, u: stats.updated, c: stats.changed }) }}</div>
                  </div>
                  <div>
                    <div class="k">{{ $t('ingest.sumSkip') }}</div>
                    <div class="v" style="color: var(--red-ink)">{{ stats.skipped.toLocaleString() }} / {{ stats.errors.toLocaleString() }}</div>
                    <div class="s">{{ $t('ingest.sumSkipS') }}</div>
                  </div>
                </div>

                <div class="row wrap mt12" style="gap: 6px">
                  <span v-for="[d, c] in stats.perDomain" :key="d" class="tag mono">{{ d }} · {{ c.toLocaleString() }}</span>
                  <span v-if="stats.aiCards" class="tag t-violet">{{ $t('ingest.aiCards', { n: stats.aiCards }) }}</span>
                  <span v-if="stats.patched" class="tag">{{ $t('ingest.patched', { n: stats.patched }) }}</span>
                </div>

                <div class="notice info mt12"><Icon name="info" /><div class="grow small">{{ $t('ingest.draftNote') }}</div></div>

                <template v-if="stats.skippedBy.length">
                  <div class="section-t">{{ $t('ingest.skippedT') }}</div>
                  <table class="tbl compact" data-testid="ingest-skipped">
                    <thead><tr><th>{{ $t('ingest.reason') }}</th><th class="num">{{ $t('ingest.count') }}</th></tr></thead>
                    <tbody>
                      <tr v-for="[k, v] in stats.skippedBy" :key="k">
                        <td class="small">{{ $te(`ingest.skip_${k}`) ? $t(`ingest.skip_${k}`) : k }}</td>
                        <td class="num">{{ v.toLocaleString() }}</td>
                      </tr>
                    </tbody>
                  </table>
                </template>

                <template v-if="current?.result?.errors?.length">
                  <div class="section-t">{{ $t('ingest.errorsT', { n: stats.errors }) }}</div>
                  <div class="tbl-wrap errs">
                    <table class="tbl compact" data-testid="ingest-errors">
                      <tbody><tr v-for="(e, i) in current.result.errors" :key="i"><td class="mono small wrap">{{ e }}</td></tr></tbody>
                    </table>
                  </div>
                  <p v-if="stats.errors >= 50" class="small faint mt8">{{ $t('ingest.errorsCap') }}</p>
                </template>
              </div>
              <div class="panel-f">
                <button class="btn" data-testid="ingest-save-result" @click="saveResult"><Icon name="download" small />{{ $t('ingest.saveResult') }}</button>
                <button class="btn" data-testid="ingest-new" @click="newTask"><Icon name="plus" small />{{ $t('ingest.newTask') }}</button>
                <router-link class="btn btn-primary ml-auto" :to="{ name: 'review' }" data-testid="ingest-goto-review">
                  <Icon name="inbox" small /><span>{{ $t('ingest.openReview', { n: stats.review.toLocaleString() }) }}</span>
                </router-link>
              </div>
            </div>
          </div>

          <!-- 右栏 -->
          <div class="stack">
            <div class="panel" data-testid="ingest-tasks">
              <div class="panel-h">
                <h2>{{ $t('ingest.recent') }}</h2>
                <button class="btn btn-sm btn-icon" :title="$t('c.refresh')" :aria-label="$t('c.refresh')" data-testid="ingest-tasks-refresh" @click="loadTasks"><Icon name="refresh" small /></button>
              </div>
              <div v-if="tasksErr" class="empty small">
                <p>{{ tasksErr }}</p>
                <button class="btn btn-sm" @click="loadTasks">{{ $t('c.retry') }}</button>
              </div>
              <div v-else-if="!loading && !tasks.length" class="empty small">{{ $t('ingest.noTasks') }}</div>
              <div v-else>
                <button
                  v-for="x in tasks" :key="x.id" type="button" class="task" :class="{ 'is-sel': current?.id === x.id }"
                  :data-testid="`ingest-task-${x.id}`" @click="follow(x)"
                >
                  <span class="n mono">{{ x.result?.rules ?? x.id }}</span>
                  <span class="tag" :class="TASK_TAG[x.status]">{{ $t(`ingest.st_${x.status}`) }}</span>
                  <span class="m">{{ taskMeta(x) }}</span>
                </button>
              </div>
            </div>
            <div class="panel">
              <div class="panel-h"><h2>{{ $t('ingest.howto') }}</h2></div>
              <div class="panel-b small">
                <ol class="howto">
                  <li><router-link :to="{ name: 'profiles' }">{{ $t('ingest.how1') }}</router-link></li>
                  <li>{{ $t('ingest.how2') }}</li>
                  <li><router-link :to="{ name: 'review' }">{{ $t('ingest.how3') }}</router-link></li>
                  <li><router-link :to="{ name: 'releases' }">{{ $t('ingest.how4') }}</router-link></li>
                </ol>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- =================== 知识库包 =================== -->
      <section v-else>
        <div class="grid g2 pkg-grid">
          <div class="panel" data-testid="pkg-export">
            <div class="panel-h"><h2>{{ $t('ingest.exportT') }}</h2></div>
            <div class="panel-b">
              <p class="small muted">{{ $t('ingest.exportD') }}</p>
              <dl v-if="status.summary" class="kvs mt12">
                <dt>{{ $t('ingest.kbVersion') }}</dt><dd class="mono">{{ kbVersion || '—' }}</dd>
                <dt>{{ $t('ingest.exportContents') }}</dt>
                <dd>{{ $t('ingest.exportCounts', { n: status.summary.kb.nodes.toLocaleString(), p: status.summary.kb.profiles, c: status.summary.kb.cards.toLocaleString() }) }}</dd>
                <dt>{{ $t('ingest.exportDraft') }}</dt>
                <dd>{{ status.summary.kb.draft_changes ? $t('kb.draftChanges', { n: status.summary.kb.draft_changes }) : $t('kb.noDraft') }}</dd>
              </dl>
              <div v-if="exportErr" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ exportErr }}</div></div>
            </div>
            <div class="panel-f">
              <span class="mono small faint">{{ exportName }}</span>
              <button class="btn btn-primary ml-auto" :disabled="exporting" data-testid="pkg-export-btn" @click="doExport">
                <Icon name="download" small /><span>{{ $t('c.export') }}</span>
              </button>
            </div>
          </div>

          <div class="panel" data-testid="pkg-import">
            <div class="panel-h"><h2>{{ $t('ingest.importT') }}</h2></div>
            <div class="panel-b">
              <p class="small muted">{{ $t('ingest.importD') }}</p>
              <label class="srcbox mt12 pick">
                <Icon name="zip" />
                <div style="flex: 1; min-width: 0">
                  <div class="p">{{ pkgFile ? pkgFile.name : $t('ingest.pickFile') }}</div>
                  <div class="m">
                    <template v-if="pkgFile">{{ fmtBytes(pkgFile.size) }}<template v-if="plan?.kb_version"> · {{ $t('ingest.pkgVersion', { v: plan.kb_version }) }}</template></template>
                    <template v-else>{{ $t('ingest.pickHint') }}</template>
                  </div>
                </div>
                <span class="btn btn-sm">{{ pkgFile ? $t('ingest.change') : $t('ingest.choose') }}</span>
                <input ref="fileInput" type="file" accept=".zip,application/zip" class="sr-only" data-testid="pkg-file" @change="pickFile">
              </label>

              <div v-if="checking" class="empty small">{{ $t('ingest.checking') }}</div>
              <div v-if="planErr" class="notice err mt12" data-testid="pkg-error"><Icon name="err" /><div class="grow small">{{ planErr }}</div></div>

              <div v-if="imported" class="notice ok mt12" data-testid="pkg-imported">
                <Icon name="ok" />
                <div class="grow small">
                  {{ $t('ingest.importedMsg', { a: imported.added.length, c: imported.conflicts.length }) }}
                  <router-link v-if="imported.conflicts.length" :to="{ name: 'review' }">{{ $t('ingest.openReviewShort') }}</router-link>
                </div>
              </div>

              <template v-if="plan">
                <div class="section-t mt16">{{ $t('ingest.checkT') }}</div>
                <div class="chk" :class="errorIssues.length ? 'bad' : 'ok'" data-testid="pkg-check-valid">
                  <Icon :name="errorIssues.length ? 'err' : 'ok'" />
                  <div>
                    <div class="t">{{ $t('ingest.chkValid') }}</div>
                    <div class="d">{{ errorIssues.length ? $t('ingest.chkValidBad', { n: errorIssues.length }) : $t('ingest.chkValidOk') }}</div>
                    <div v-for="(i, k) in errorIssues.slice(0, 20)" :key="k" class="errline">
                      <template v-if="i.file">{{ i.file }}  </template>{{ i.message }} <span class="faint">[{{ i.code }}]</span>
                    </div>
                  </div>
                  <span class="c">{{ errorIssues.length }}</span>
                </div>
                <div class="chk ok">
                  <Icon name="plus" />
                  <div>
                    <div class="t">{{ $t('ingest.chkAdded') }}</div>
                    <div class="d">
                      <template v-if="plan.added.length">
                        <span v-for="[d, c] in groupByDir(plan.added)" :key="d" class="dirc"><span class="mono">{{ d }}</span> {{ c }}</span>
                      </template>
                      <template v-else>{{ $t('c.none') }}</template>
                    </div>
                  </div>
                  <span class="c">{{ plan.added.length }}</span>
                </div>
                <div class="chk ok">
                  <Icon name="check" />
                  <div><div class="t">{{ $t('ingest.chkSame') }}</div><div class="d">{{ $t('ingest.chkSameD') }}</div></div>
                  <span class="c">{{ plan.unchanged.length }}</span>
                </div>
                <div class="chk" :class="plan.conflicts.length ? 'warn' : 'ok'">
                  <Icon :name="plan.conflicts.length ? 'warn' : 'ok'" />
                  <div><div class="t">{{ $t('ingest.chkConflict') }}</div><div class="d">{{ $t('ingest.chkConflictD') }}</div></div>
                  <span class="c">{{ plan.conflicts.length }}</span>
                </div>
                <table v-if="plan.conflicts.length" class="tbl compact mt8" data-testid="pkg-conflicts">
                  <thead><tr><th>{{ $t('ingest.file') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="f in plan.conflicts.slice(0, 12)" :key="f"><td class="mono small">{{ f }}</td></tr>
                    <tr v-if="plan.conflicts.length > 12"><td class="small faint">{{ $t('ingest.more', { n: plan.conflicts.length - 12 }) }}</td></tr>
                  </tbody>
                </table>
              </template>
            </div>
            <div class="panel-f">
              <span v-if="plan && errorIssues.length" class="small" style="color: var(--red-ink)">{{ $t('ingest.fixFirst', { n: errorIssues.length }) }}</span>
              <span v-else-if="plan && !canApply(plan)" class="small faint">{{ $t('ingest.nothingToImport') }}</span>
              <button class="btn btn-primary ml-auto" :disabled="!canApply(plan) || importing" data-testid="pkg-import-btn" @click="doImport">
                <Icon name="upload" small /><span>{{ $t('c.import') }}</span>
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.fmt { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.fmt-card { padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); }
.fmt-card .rc-t { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; }
.fmt-card .rc-d { font-size: 12px; color: var(--ink-2); }
.srcbox { display: flex; gap: 10px; align-items: center; padding: 8px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); }
.srcbox .input { flex: 1; min-width: 0; background: var(--surface); }
.srcbox .p { font: 12px var(--font-mono); overflow-wrap: anywhere; }
.srcbox .m { font-size: 12px; color: var(--ink-3); }
.srcbox.pick { cursor: pointer; }
.srcbox.pick:hover { border-color: var(--line-strong); }
.sr-only { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.ch { grid-template-columns: 1fr 1fr; }
.ai-off-card { opacity: .62; cursor: not-allowed; }
.ai-off-card input { cursor: not-allowed; }
.ai-off-card a { pointer-events: auto; }
.stages { display: flex; flex-direction: column; }
.stage { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 10px 0; border-bottom: 1px solid var(--line); }
.stage:last-child { border-bottom: 0; }
.stage .no { width: 22px; height: 22px; border-radius: 50%; border: 1.5px solid var(--line-strong); display: inline-flex; align-items: center; justify-content: center; font-size: 11.5px; font-weight: 600; color: var(--ink-3); }
.stage.done .no { background: var(--teal); border-color: var(--teal); color: var(--surface); }
.stage.cur .no { border-color: var(--teal); color: var(--teal-ink); box-shadow: 0 0 0 3px var(--teal-soft); }
.stage .t { font-weight: 600; }
.stage.todo .t { color: var(--ink-3); font-weight: 500; }
.stage .d { font-size: 12px; color: var(--ink-2); overflow-wrap: anywhere; }
.sum { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 6px; }
.sum > div { padding: 10px 14px; border-left: 1px solid var(--line); }
.sum > div:first-child { border-left: 0; }
.sum .k { font-size: 12px; color: var(--ink-2); }
.sum .v { font: 600 20px/1.3 var(--font-display); }
.sum .s { font-size: 11.5px; color: var(--ink-3); }
.errs { max-height: 220px; border: 1px solid var(--line); border-radius: 6px; }
.errs td.wrap { white-space: normal; overflow-wrap: anywhere; }
.task { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px; padding: 10px 14px; border: 0; border-bottom: 1px solid var(--line); width: 100%; text-align: left; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.task:last-child { border-bottom: 0; }
.task:hover { background: var(--surface-2); }
.task.is-sel { background: var(--blue-soft); }
.task .n { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task .m { font-size: 12px; color: var(--ink-3); grid-column: 1 / -1; }
.howto { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; color: var(--ink-2); }
.chk { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--line); align-items: start; }
.chk:last-of-type { border-bottom: 0; }
.chk > .ico { margin-top: 2px; }
.chk.ok > .ico { color: var(--teal-ink); }
.chk.bad > .ico { color: var(--red-ink); }
.chk.warn > .ico { color: var(--amber-ink); }
.chk .t { font-weight: 600; }
.chk .d { font-size: 12px; color: var(--ink-2); }
.chk .c { font-size: 12px; color: var(--ink-3); white-space: nowrap; }
.dirc { margin-right: 10px; white-space: nowrap; }
.errline { margin-top: 6px; font: 11.5px/1.6 var(--font-mono); background: var(--red-soft); border: 1px solid var(--red-line); border-radius: 5px; padding: 6px 8px; color: var(--ink); overflow-wrap: anywhere; white-space: pre-wrap; }
.kvs { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; margin: 0; font-size: 12.5px; }
.kvs dt { color: var(--ink-2); }
.kvs dd { margin: 0; }
.pkg-grid { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); align-items: start; }
@media (max-width: 1100px) {
  .g-side.collapse, .pkg-grid { grid-template-columns: minmax(0, 1fr); }
  .fmt { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sum { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sum > div:nth-child(3) { border-left: 0; }
  .sum > div:nth-child(n + 3) { border-top: 1px solid var(--line); }
}
</style>
