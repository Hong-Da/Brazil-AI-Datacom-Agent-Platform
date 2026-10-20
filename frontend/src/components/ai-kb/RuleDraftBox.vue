<script setup lang="ts">
/**
 * 规范转规则（rule-draft，M8-5；预览 DevelopDocs/ui-preview/M8/compliance.html“检查规则”）：上传或粘贴规范 → 条款列表（状态由
 * 最近一次运行的建议算出）→ AI 面板（草稿 YAML 与样本试跑见 AiKbDetail）→ 采纳即送审核队列；下方“规则编写助手”用一句话运行同一个 skill。
 * 只给维护员与管理员（由所在页面 v-if auth.isKbEditor 控制）。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { errorText, get, post } from '@/api'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { projectPath, query, type Batch, type ListResult, type Suggestion } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { DOC_TYPES, MAX_STANDARD, MAX_UPLOAD, RULE_SCOPE, clauseStates, reviewRows, splitClauses, stepClasses } from './compliance'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`kb-ai.${k}`, p ?? {})
const project = useProject()
const P = (path: string) => projectPath(project.ref ?? '', path)

const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const fileInput = ref<HTMLInputElement | null>(null)

// ---------------------------------------------------------------- 规范文字
const doc = ref<{ name: string; text: string; chars: number; truncated: boolean } | null>(null)
const reading = ref(false)
const docErr = ref('')
const pasteOpen = ref(false)
const pasteText = ref('')
const sentence = ref('')
const mode = ref<'doc' | 'sentence'>('doc')
const notice = ref('')

async function onFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  docErr.value = ''
  if (!DOC_TYPES.test(f.name)) { docErr.value = T('rd.badType'); return }
  if (f.size > MAX_UPLOAD) { docErr.value = T('rd.tooBig'); return }
  reading.value = true
  try {
    const fd = new FormData()
    fd.append('file', f)
    doc.value = await post<{ name: string; text: string; chars: number; truncated: boolean }>(P('/ai/kb/extract-text'), fd)
    notice.value = ''
  } catch (err) {
    docErr.value = errorText(err)
  } finally {
    reading.value = false
  }
}

function usePaste(): void {
  const text = pasteText.value.trim()
  if (!text) return
  doc.value = { name: T('rd.pasted'), text: text.slice(0, MAX_STANDARD), chars: text.length, truncated: text.length > MAX_STANDARD }
  pasteOpen.value = false
  notice.value = ''
}

// ---------------------------------------------------------------- 最近一次运行（条款状态与已送审列表）
const items = ref<Suggestion[]>([])
const docBatch = ref<Batch | null>(null)
const reviewStatus = ref<Record<number, string>>({})
const reviewErr = ref('')

async function refresh(): Promise<void> {
  if (!project.ref) return
  try {
    items.value = (await get<ListResult>(P(`/ai/suggestions${query({ skill: 'rule-draft', scope: RULE_SCOPE, limit: 200 })}`))).items
    // 最近一次带规范全文运行的批次（一句话运行不改左边的条款列表）
    const ids = [...new Set(items.value.map((x) => x.batch_id))].sort((a, b) => b - a).slice(0, 6)
    docBatch.value = null
    for (const id of ids) {
      const b = await get<Batch>(P(`/ai/suggestions/batches/${id}`))
      if (typeof b.params?.text === 'string' && b.params.text) { docBatch.value = b; break }
    }
  } catch {
    /* 面板里会显示加载错误 */
  }
  if (!reviewRows(items.value, {}).length) return
  try {
    const r = await get<{ items: { id: number; status: string }[] }>('/review?status=all&kind=rule&limit=1000')
    reviewStatus.value = Object.fromEntries(r.items.map((x) => [x.id, x.status]))
    reviewErr.value = ''
  } catch (e) {
    reviewErr.value = T('rd.reviewFail', { e: errorText(e) })
  }
}

const batchText = computed(() => String(docBatch.value?.params?.text ?? ''))
const shownText = computed(() => doc.value?.text ?? batchText.value)
const shownName = computed(() => doc.value?.name ?? String(docBatch.value?.params?.doc_name ?? T('rd.lastRun')))
const clauses = computed(() => splitClauses(shownText.value))
/** 只有显示的规范就是那次运行的规范时，条款才标状态。 */
const states = computed(() => (shownText.value && shownText.value === batchText.value ? clauseStates(items.value, docBatch.value?.id ?? null) : {}))
const rows = computed(() => reviewRows(items.value, reviewStatus.value))
const running = computed(() => aiState.value === 'running')
const steps = computed(() => {
  const st = Object.values(states.value)
  const ran = st.length > 0 || (mode.value === 'doc' && !!batchText.value && shownText.value === batchText.value && (aiState.value === 'done' || aiState.value === 'empty'))
  const cls = stepClasses(!!shownText.value, running.value && mode.value === 'doc', ran, st.includes('sent'))
  return ['rd.step1', 'rd.step2', 'rd.step3', 'rd.step4'].map((k, i) => ({ k, cls: cls[i] }))
})

const params = computed<Record<string, unknown>>(() =>
  mode.value === 'sentence'
    ? { sentence: sentence.value.trim() }
    : { text: shownText.value, doc_name: shownName.value },
)

async function run(m: 'doc' | 'sentence'): Promise<void> {
  if (running.value) return
  if (m === 'doc' && !shownText.value) m = 'sentence'
  if (m === 'sentence' && !sentence.value.trim()) { notice.value = T('rd.needInput'); return }
  notice.value = ''
  mode.value = m
  await nextTick()
  await panel.value?.start()
}

function clearDoc(): void {
  doc.value = null
  docBatch.value = null
}

onMounted(refresh)
</script>

<template>
  <div class="rdx" data-testid="rule-draft">
    <div class="rdx-grid">
      <div class="rdx-main">
        <section class="panel">
          <div class="hostbar">
            <h3>{{ T('rd.title') }}</h3>
            <span class="ml-auto" />
            <AiEntryButton :skills="['rule-draft']" :busy="running" small @run="run('doc')" />
          </div>
          <div class="panel-b rdx-steps">
            <div class="steps" data-testid="rule-steps">
              <div v-for="(s, i) in steps" :key="s.k" class="st" :class="s.cls"><span class="no"><Icon v-if="s.cls === 'done'" name="check" small /><template v-else>{{ i + 1 }}</template></span><span>{{ T(s.k) }}</span></div>
            </div>
            <p class="small faint">{{ T('rd.sub') }}</p>
          </div>
          <div class="hostbar docbar">
            <input ref="fileInput" type="file" accept=".txt,.md,.markdown,.text,.docx" hidden data-testid="rule-doc-file" @change="onFile" />
            <button class="btn btn-sm" type="button" :disabled="reading" data-testid="rule-doc-upload" @click="fileInput?.click()"><Icon name="upload" small />{{ reading ? T('rd.uploading') : T('rd.upload') }}</button>
            <button class="btn btn-sm btn-ghost" type="button" :aria-expanded="pasteOpen" data-testid="rule-doc-paste" @click="pasteOpen = !pasteOpen">{{ pasteOpen ? T('rd.pasteHide') : T('rd.paste') }}</button>
            <template v-if="shownText">
              <Icon name="file" small /><span class="mono small docname" data-testid="rule-doc-name">{{ shownName }}</span>
              <span class="small faint">{{ T('rd.docInfo', { n: doc?.chars ?? shownText.length, c: clauses.length }) }}</span>
              <button class="btn btn-xs btn-ghost" type="button" data-testid="rule-doc-clear" @click="clearDoc"><Icon name="x" small />{{ T('rd.clear') }}</button>
            </template>
          </div>
          <div v-if="pasteOpen" class="pastebox">
            <textarea v-model="pasteText" class="input" rows="6" :placeholder="T('rd.pastePh')" data-testid="rule-doc-text" />
            <div class="toolbar"><button class="btn btn-sm btn-primary" type="button" :disabled="!pasteText.trim()" data-testid="rule-doc-use" @click="usePaste">{{ T('rd.usePaste') }}</button></div>
          </div>
          <div v-if="docErr" class="notice err mx12"><Icon name="err" /><div class="grow small">{{ docErr }}</div></div>
          <div v-if="doc?.truncated" class="notice warn mx12"><Icon name="warn" /><div class="grow small">{{ T('rd.truncated', { n: MAX_STANDARD }) }}</div></div>
          <div class="stdtext" data-testid="rule-clauses">
            <p v-if="!clauses.length" class="small faint">{{ T('rd.noDoc') }}</p>
            <div v-for="c in clauses" :key="c.id" class="cl" :class="{ ok: states[c.id] === 'sent', has: states[c.id] === 'draft' || states[c.id] === 'failed' }" :data-clause="c.id" :data-state="states[c.id] || 'none'">
              <span class="no">{{ c.no }}</span><span>{{ c.text }}</span>
              <span class="rtag" :class="{ bad: states[c.id] === 'failed' }">{{ states[c.id] ? T(`rd.st.${states[c.id]}`) : '' }}</span>
            </div>
          </div>
          <div v-if="notice" class="notice warn mx12" data-testid="rule-notice"><Icon name="info" /><div class="grow small">{{ notice }}</div></div>
          <div class="assist">
            <Icon name="wand" small class="wand" /><span class="small b">{{ T('rd.assist') }}</span>
            <input v-model="sentence" class="input" maxlength="2000" :placeholder="T('rd.sentencePh')" data-testid="rule-sentence" @keydown.enter="run('sentence')" />
            <button class="btn btn-sm btn-ai" type="button" :disabled="running || !sentence.trim()" data-testid="rule-sentence-run" @click="run('sentence')"><Icon name="spark" small />{{ T('rd.sentenceRun') }}</button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-h">
            <h2>{{ T('rd.review') }}</h2><span class="meta">{{ T('rd.reviewMeta') }}</span>
            <router-link class="btn btn-xs ml-auto" :to="{ name: 'review', query: { kind: 'rule' } }" data-testid="rule-review-open"><Icon name="inbox" small />{{ T('rd.reviewOpen') }}</router-link>
          </div>
          <div class="rqlist" data-testid="rule-review-list">
            <p v-if="reviewErr" class="small faint">{{ reviewErr }}</p>
            <p v-if="!rows.length" class="small faint">{{ T('rd.reviewEmpty') }}</p>
            <router-link v-for="r in rows" :key="r.sid" class="rq" :to="{ name: 'review', query: { kind: 'rule' } }" :data-testid="`rule-review-${r.reviewId}`">
              <Icon name="rules" small /><span class="grow">{{ r.title }}</span>
              <span class="tag t-violet">{{ T('rd.fromAi') }}</span>
              <span class="tag" :class="r.status === 'approved' ? 'approved' : r.status === 'rejected' ? 'rejected' : 'pending'">{{ T(`rv.${r.status === 'approved' || r.status === 'rejected' ? r.status : 'pending'}`) }}</span>
            </router-link>
          </div>
        </section>
      </div>
      <div class="rdx-side">
        <AiSuggestPanel ref="panel" skill="rule-draft" :params="params" :can-estimate="!!(params.text || params.sentence)" :scope="RULE_SCOPE" @state="aiState = $event" @changed="refresh" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.rdx { margin-bottom: 14px; }
.rdx-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(340px, 460px); gap: 12px; align-items: start; }
@media (max-width: 1180px) { .rdx-grid { grid-template-columns: minmax(0, 1fr); } }
.rdx-main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.rdx-side { min-width: 0; position: sticky; top: 12px; }
.hostbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 9px 12px; border-bottom: 1px solid var(--line); }
.hostbar h3 { font-size: 13.5px; margin-right: 6px; }
.rdx-steps { display: flex; flex-direction: column; gap: 8px; padding-bottom: 8px; }
.docbar { border-top: 1px solid var(--line); }
.docname { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pastebox { padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--line); }
.pastebox textarea { width: 100%; font-size: 12.5px; resize: vertical; min-height: 110px; }
.mx12 { margin: 10px 12px 0; }
.stdtext { padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; line-height: 1.65; max-height: 420px; overflow: auto; }
.stdtext .cl { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 8px; padding: 5px 8px; border-radius: 5px; align-items: start; }
.stdtext .cl .no { font: 600 12px var(--font-mono); color: var(--ink-3); overflow-wrap: anywhere; }
.stdtext .cl.has { background: var(--ai-wash); box-shadow: inset 2px 0 0 var(--ai-line); }
.stdtext .cl.ok { background: var(--surface-2); box-shadow: inset 2px 0 0 var(--ai); }
.stdtext .cl .rtag { font-size: 11px; color: var(--ai); white-space: nowrap; }
.stdtext .cl .rtag.bad { color: var(--red-ink); }
.assist { display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-top: 1px solid var(--line); flex-wrap: wrap; }
.assist .input { flex: 1; min-width: 240px; }
.assist .wand { color: var(--violet); }
.assist .b { font-weight: 600; }
.rqlist { display: flex; flex-direction: column; gap: 6px; padding: 12px; }
.rq { display: flex; gap: 8px; align-items: center; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); text-decoration: none; box-shadow: inset 3px 0 0 var(--violet); background: var(--surface); }
.rq:hover { background: var(--surface-2); }
</style>
