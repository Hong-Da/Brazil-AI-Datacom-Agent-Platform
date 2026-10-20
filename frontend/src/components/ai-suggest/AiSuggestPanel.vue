<script setup lang="ts">
/**
 * AI 建议面板（M8-2，预览 DevelopDocs/ui-preview/M8/suggest.html）：未运行（发送内容、预计 token，超过提示线变黄）/
 * 运行中（本地脱敏 → 发送 → 生成 → 代码校验，可取消）/ 有建议（汇总条、全部采纳与按类别采纳只含校验通过的、筛选、卡片）/
 * 空结果 / 失败 / 已取消 / AI 不可用（REQ-040 的提示组件）；底部是采纳记录与撤销（30 天内）。
 * 会改配置、脚本或知识库的采纳先二次确认（附模拟结果，勾选“已查看”）。
 * 用法：<AiSuggestPanel ref="p" skill="device-summary" :params="{ device_id: 3 }" :scope="`device:3`" />，入口按钮调用 p.start()。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError, errorText, get, post, waitTask, type Task } from '@/api'
import Icon from '@/components/Icon.vue'
import AiOffHint from '@/components/ai-off-hint.vue'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import AiSuggestCard from './AiSuggestCard.vue'
import {
  REVERT_DAYS, STEPS, batchIds, bigRequest, canRevert, categoriesOf, counts, defaultOpen, filterItems, fmtTokens, jumpTarget,
  needsConfirm, pick, projectPath, query, stepOf,
  type Batch, type Category, type Check, type Estimate, type Filter, type ListResult, type RefInfo, type SkillList, type Suggestion,
} from './logic'
import './ai-suggest.css'

// canEstimate=false：参数还不完整（例如规范转规则还没有规范文字），不请求运行前估计（M8-5）
const props = withDefaults(defineProps<{ skill: string; params?: Record<string, unknown>; scope: string; flat?: boolean; canEstimate?: boolean }>(), {
  params: () => ({}),
  flat: false,
  canEstimate: true,
})
const emit = defineEmits<{ changed: []; jump: [ref: RefInfo]; state: [state: string] }>()
const { t, locale } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-suggest.${k}`, p ?? {})
const router = useRouter()
const auth = useAuth()
const project = useProject()
const canWrite = computed(() => project.canWrite)
const canKb = computed(() => auth.isKbEditor)

type St = 'loading' | 'off' | 'idle' | 'running' | 'done' | 'empty' | 'failed' | 'cancelled' | 'error'
const st = ref<St>('loading')
const info = ref<SkillList | null>(null)
const items = ref<Suggestion[]>([])
const log = ref<Suggestion[]>([])
const batch = ref<Batch | null>(null)
const est = ref<Estimate | null>(null)
const estErr = ref(false)
const err = ref('')
const notice = ref('')
const busy = ref(false)
const step = ref(0)
const filter = ref<Filter>('all')
const open = reactive<Record<number, boolean>>({})
const catMenu = ref(false)
const cards = ref<Record<number, InstanceType<typeof AiSuggestCard> | null>>({})

const P = (path: string) => projectPath(project.ref ?? '', path)
const skillInfo = computed(() => info.value?.skills.find((s) => s.id === props.skill) ?? null)
const skillName = computed(() => (skillInfo.value ? pick(skillInfo.value.title, String(locale.value)) : props.skill))
const offReason = computed(() => (info.value && !info.value.ai.configured ? info.value.ai.reason ?? 'no_connection' : null))
const c = computed(() => counts(items.value))
const shown = computed(() => filterItems(items.value, filter.value))
const passIds = computed(() => batchIds(items.value))
const warnPending = computed(() => items.value.filter((x) => x.status === 'pending' && x.check_status === 'warn').length)
const cats = computed(() => categoriesOf(items.value))
const threshold = computed(() => est.value?.threshold ?? info.value?.ai.warn_tokens ?? 0)
const big = computed(() => !!est.value && bigRequest(est.value.tokens, threshold.value))

function setSt(s: St): void { st.value = s; emit('state', s) }
function isOpen(it: Suggestion): boolean { return open[it.id] ?? defaultOpen(it) }

async function loadItems(): Promise<void> {
  const r = await get<ListResult>(P(`/ai/suggestions${query({ skill: props.skill, scope: props.scope, limit: 200 })}`))
  items.value = r.items
  const all = await get<{ items: Suggestion[] }>(P('/ai/suggestions/adoptions?limit=200'))
  log.value = all.items.filter((x) => x.skill === props.skill && x.scope_key === props.scope)
}

async function load(): Promise<void> {
  setSt('loading')
  err.value = ''
  try {
    info.value = await get<SkillList>(P('/ai/suggestions/skills'))
    await loadItems()
    if (items.value.length) {
      batch.value = await get<Batch>(P(`/ai/suggestions/batches/${items.value[0].batch_id}`))
      setSt('done')
    } else if (offReason.value) {
      setSt('off')
    } else {
      setSt('idle')
      void estimate()
    }
  } catch (e) {
    err.value = errorText(e)
    setSt('error')
  }
}

async function estimate(): Promise<void> {
  estErr.value = false
  est.value = null
  if (!canWrite.value || offReason.value || !props.canEstimate) return
  try {
    est.value = await post<Estimate>(P('/ai/suggestions/estimate'), { skill: props.skill, params: props.params })
  } catch {
    estErr.value = true
  }
}

/** 入口按钮调用：运行 skill（后台任务），轮询进度。 */
async function start(): Promise<void> {
  if (st.value === 'running' || !canWrite.value) return
  if (offReason.value) { setSt('off'); return }
  err.value = ''
  notice.value = ''
  step.value = 0
  try {
    const r = await post<{ task_id: string; batch_id: number }>(P('/ai/suggestions/run'), { skill: props.skill, params: props.params })
    batch.value = { id: r.batch_id, status: 'running' } as Batch
    setSt('running')
    void refreshBatch()
    const task = await waitTask<Batch>(r.task_id, (tk: Task<Batch>) => {
      step.value = stepOf(tk.message, tk.status)
      if (tk.message === 'send' || tk.message === 'generate') void refreshBatch()
    }, 600)
    await finish(task)
  } catch (e) {
    const d = e instanceof ApiError ? (e.data as { status?: string; reason?: string } | null) : null
    if (d?.status === 'not_configured' && info.value) {
      info.value = { ...info.value, ai: { ...info.value.ai, configured: false, reason: d.reason ?? null } }
      setSt('off')
      return
    }
    err.value = errorText(e)
    setSt('failed')
  }
}

async function refreshBatch(): Promise<void> {
  if (!batch.value) return
  try { batch.value = await get<Batch>(P(`/ai/suggestions/batches/${batch.value.id}`)) } catch { /* 进度显示用，失败不影响 */ }
}

async function finish(task: Task<Batch>): Promise<void> {
  const b = task.result ?? null
  if (task.status === 'failed' || !b) { err.value = task.message; setSt('failed'); return }
  batch.value = b
  if (b.status === 'cancelled') { setSt('cancelled'); return }
  if (b.status === 'failed') {
    err.value = b.error?.key ? t(b.error.key) + (b.error.detail ? ` (${b.error.detail})` : '') : ''
    setSt('failed')
    return
  }
  await loadItems()
  for (const k of Object.keys(open)) delete open[Number(k)]
  filter.value = 'all'
  setSt(b.counts.total ? 'done' : 'empty')
  emit('changed')
}

async function cancel(): Promise<void> {
  if (!batch.value) return
  try {
    batch.value = await post<Batch>(P(`/ai/suggestions/batches/${batch.value.id}/cancel`))
    setSt('cancelled')
  } catch (e) {
    notice.value = errorText(e)
  }
}

// ---------------------------------------------------------------- 采纳、忽略、撤销
const confirm = ref<{ ids: number[]; category: Category; content?: Record<string, unknown>; checks: Check[]; seen: boolean } | null>(null)

function replace(s: Suggestion): void {
  items.value = items.value.map((x) => (x.id === s.id ? s : x))
}

function askAdopt(it: Suggestion, content?: Record<string, unknown>): void {
  if (needsConfirm(it.category)) {
    confirm.value = { ids: [it.id], category: it.category, content, checks: [it.check], seen: false }
    return
  }
  void adoptOne(it.id, content)
}

async function adoptOne(id: number, content?: Record<string, unknown>): Promise<void> {
  busy.value = true
  notice.value = ''
  try {
    replace(await post<Suggestion>(P(`/ai/suggestions/${id}/adopt`), content ? { content } : {}))
    open[id] = false
    cards.value[id]?.stopEdit()
    await loadItems()
    emit('changed')
  } catch (e) {
    const d = e instanceof ApiError ? (e.data as { check?: Check } | null) : null
    const msg = d?.check?.reasons?.length
      ? `${errorText(e)} ${d.check.reasons.map((r) => t(`ai-suggest.r.${r.code}`) + (r.ref ? `：${r.ref}` : '')).join('；')}`
      : errorText(e)
    if (content) cards.value[id]?.setEditError(msg)
    else notice.value = msg
  } finally {
    busy.value = false
  }
}

function askBatch(category?: Category): void {
  catMenu.value = false
  const ids = batchIds(items.value, category)
  if (!ids.length) return
  const catsHere = category ? [category] : categoriesOf(items.value.filter((x) => ids.includes(x.id)))
  if (catsHere.some(needsConfirm)) {
    confirm.value = { ids, category: category ?? '', checks: items.value.filter((x) => ids.includes(x.id)).map((x) => x.check), seen: false }
    return
  }
  void adoptBatch(ids)
}

async function adoptBatch(ids: number[]): Promise<void> {
  busy.value = true
  notice.value = ''
  try {
    const byCat = new Map<string, number[]>()
    for (const it of items.value.filter((x) => ids.includes(x.id))) byCat.set(it.category, [...(byCat.get(it.category) ?? []), it.id])
    for (const [category, list] of byCat) {
      await post(P('/ai/suggestions/adopt-batch'), { category, skill: props.skill, ids: list })
    }
    await loadItems()
    emit('changed')
  } catch (e) {
    notice.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function confirmOk(): Promise<void> {
  const cf = confirm.value
  confirm.value = null
  if (!cf) return
  if (cf.ids.length === 1 && cf.category) await adoptOne(cf.ids[0], cf.content)
  else await adoptBatch(cf.ids)
}

async function act(it: Suggestion, what: 'dismiss' | 'restore' | 'revert'): Promise<void> {
  busy.value = true
  notice.value = ''
  try {
    replace(await post<Suggestion>(P(`/ai/suggestions/${it.id}/${what}`), {}))
    await loadItems()
    emit('changed') // M8-5：忽略 / 恢复也通知页面（表格上的 AI 标记随之刷新）
  } catch (e) {
    notice.value = errorText(e)
  } finally {
    busy.value = false
  }
}

function jump(r: RefInfo): void {
  emit('jump', r)
  const tg = jumpTarget(r)
  if (tg) void router.push(tg)
}

function expandAll(v: boolean): void { for (const it of items.value) open[it.id] = v }

const stepRows = computed(() => STEPS.map((k, i) => ({
  k,
  cls: i < step.value ? 'done' : i === step.value ? 'cur' : '',
  sub: k === 'sanitize' ? T('step.sanitizeSub') : k === 'check' ? T('step.checkSub') : '',
  v: k === 'send' && batch.value?.connection ? `${batch.value.connection} · ${batch.value.model}` : '',
})))
const pct = computed(() => Math.min(100, Math.round(((step.value + 0.5) / STEPS.length) * 100)))
function fmtTime(s: string | null): string { return s ? new Date(s).toLocaleString(String(locale.value)) : '' }

watch(() => props.scope, () => void load())
onMounted(load)
defineExpose({ start, reload: load, state: st })
</script>

<template>
  <section class="aip" :class="{ flat }" :data-st="st" :data-testid="`ai-panel-${skill}`" aria-label="AI suggestions">
    <header class="aip-h">
      <span class="mark"><Icon name="spark" />{{ T('panel') }}</span>
      <span class="sk">{{ skillName }}</span>
      <span class="acts">
        <template v-if="st === 'done'">
          <button class="btn btn-xs btn-ghost" type="button" @click="expandAll(true)">{{ T('expandAll') }}</button>
          <button class="btn btn-xs btn-ghost" type="button" @click="expandAll(false)">{{ T('collapseAll') }}</button>
          <button v-if="canWrite" class="btn btn-xs" type="button" data-testid="ai-regen" @click="start"><Icon name="refresh" small />{{ T('regen') }}</button>
        </template>
      </span>
      <div v-if="batch && st !== 'off' && st !== 'idle' && st !== 'loading'" class="aip-meta" data-testid="ai-meta">
        <span v-if="batch.connection"><Icon name="plug" small />{{ T('iface') }} <b>{{ batch.connection }}</b></span>
        <span v-if="batch.model"><Icon name="cpu" small /><b>{{ batch.model }}</b></span>
        <span v-if="batch.skill"><Icon name="skill" small />skill <b>{{ batch.skill }}</b> {{ batch.skill_version === 'builtin' ? 'builtin' : `v${batch.skill_version}` }}</span>
        <span v-if="batch.mode === 'replay'" class="tag">{{ T('replay') }}</span>
        <span v-if="st === 'done' || st === 'empty'"><Icon name="bolt" small />{{ T('in') }} <b>{{ fmtTokens(batch.tokens_in) }}</b> · {{ T('out') }} <b>{{ fmtTokens(batch.tokens_out) }}</b> token</span>
      </div>
    </header>

    <div class="aip-b">
      <div v-if="notice" class="notice err" data-testid="ai-notice"><Icon name="err" /><div class="grow small">{{ notice }}</div><button class="btn btn-xs btn-ghost" type="button" @click="notice = ''"><Icon name="x" small /></button></div>

      <div v-if="st === 'loading'" class="small faint">{{ $t('c.loading') }}</div>

      <div v-else-if="st === 'error'" class="notice err"><Icon name="err" /><div class="grow"><b>{{ T('loadFail') }}</b><div class="small">{{ err }}</div></div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>

      <template v-else-if="st === 'off'">
        <AiOffHint :reason="offReason" />
        <p class="small faint">{{ T('offNote') }}</p>
      </template>

      <div v-else-if="st === 'idle'" class="idle" data-testid="ai-idle">
        <p class="what">{{ T(`what.${skill}`) }}</p>
        <dl class="sendlist"><dt>{{ T('sendLbl') }}</dt><dd>{{ T(`send.${skill}`) }}</dd></dl>
        <div v-if="est" class="tokest" :class="{ big }" data-testid="ai-estimate" :data-big="big">
          <Icon :name="big ? 'warn' : 'bolt'" />
          <span>{{ T('est') }} <b>{{ fmtTokens(est.tokens) }}</b> token</span>
          <span v-if="big">{{ T('estBig', { n: fmtTokens(threshold) }) }}</span>
          <router-link class="ml-auto small" :to="{ name: 'my-ai' }">{{ T('seeUsage') }}</router-link>
        </div>
        <div v-else-if="estErr" class="small faint">{{ T('estFail') }}</div>
        <div class="toolbar">
          <button v-if="canWrite" class="btn btn-ai" type="button" data-testid="ai-run" @click="start"><Icon name="spark" small />{{ big && est ? T('runAnyway', { n: fmtTokens(est.tokens) }) : T('run') }}</button>
          <span class="small faint">{{ canWrite ? T('idleNote') : T('readOnly') }}</span>
        </div>
      </div>

      <div v-else-if="st === 'running'" class="run" data-testid="ai-running">
        <div class="run-steps">
          <div v-for="(s, i) in stepRows" :key="s.k" class="st" :class="s.cls" :data-step="s.k">
            <span class="no"><Icon v-if="s.cls === 'done'" name="check" small /><template v-else>{{ i + 1 }}</template></span>
            <span>{{ T(`step.${s.k}`) }}<small v-if="s.sub">{{ s.sub }}</small></span>
            <span class="v">{{ s.v }}</span>
          </div>
        </div>
        <div class="progress"><i :style="{ width: `${pct}%` }" /></div>
        <div class="rf">
          <button class="btn btn-sm" type="button" data-testid="ai-cancel" @click="cancel"><Icon name="x" small />{{ T('cancel') }}</button>
          <span>{{ T('cancelNote') }}</span>
        </div>
      </div>

      <div v-else-if="st === 'cancelled'" class="notice" data-testid="ai-cancelled">
        <Icon name="info" />
        <div class="grow"><b>{{ T('cancelled') }}</b><div class="small">{{ T('cancelledD') }}</div>
          <div class="toolbar mt8"><button v-if="canWrite" class="btn btn-sm btn-ai" type="button" @click="start"><Icon name="spark" small />{{ T('restart') }}</button></div>
        </div>
      </div>

      <div v-else-if="st === 'failed'" class="notice err" data-testid="ai-failed">
        <Icon name="err" />
        <div class="grow"><b>{{ T('failed') }}</b><div class="small">{{ err }} {{ T('failedD') }}</div>
          <div class="toolbar mt8">
            <button v-if="canWrite" class="btn btn-sm" type="button" data-testid="ai-retry" @click="start"><Icon name="refresh" small />{{ T('retry') }}</button>
            <router-link class="btn btn-sm btn-ghost" :to="{ name: 'my-ai' }"><Icon name="plug" small />{{ T('otherIface') }}</router-link>
          </div>
        </div>
      </div>

      <div v-else-if="st === 'empty'" class="empty" style="padding: 24px 12px" data-testid="ai-empty">
        <Icon name="spark" /><h3>{{ T('empty') }}</h3><p>{{ T('emptyD') }}</p>
        <button v-if="canWrite" class="btn btn-sm" type="button" @click="start"><Icon name="refresh" small />{{ T('regen') }}</button>
      </div>

      <template v-else-if="st === 'done'">
        <div class="aisum" data-testid="ai-summary">
          <div class="bar">
            <i :style="{ background: 'var(--teal)', width: `${(c.pass / Math.max(1, items.length)) * 100}%` }" />
            <i :style="{ background: 'var(--amber)', width: `${(c.warn / Math.max(1, items.length)) * 100}%` }" />
            <i :style="{ background: 'var(--red)', width: `${(c.reject / Math.max(1, items.length)) * 100}%` }" />
          </div>
          <div class="cnt">
            <span>{{ T('items', { n: items.length }) }}</span>
            <span class="p"><i />{{ T('passed') }} {{ c.pass }}</span>
            <span class="w"><i />{{ T('warned') }} {{ c.warn }}</span>
            <span class="f"><i />{{ T('rejected') }} {{ c.reject }}</span>
          </div>
          <div v-if="canWrite" class="bulk">
            <span v-if="cats.length > 1" class="catmenu">
              <button class="btn btn-sm btn-aio" type="button" :aria-expanded="catMenu" data-testid="ai-catmenu" @click="catMenu = !catMenu">{{ T('byCat') }}<Icon name="chevD" small /></button>
              <div v-if="catMenu" class="pop" role="menu">
                <button v-for="k in cats" :key="k" type="button" :disabled="!batchIds(items, k).length" :data-testid="`ai-adopt-cat-${k}`" @click="askBatch(k)">{{ T(`cat.${k}`) }}<b>{{ batchIds(items, k).length }}</b></button>
              </div>
            </span>
            <button class="btn btn-sm btn-ai" type="button" :disabled="!passIds.length || busy" data-testid="ai-adopt-all" @click="askBatch()"><Icon name="check" small />{{ T('adoptAll', { n: passIds.length }) }}</button>
          </div>
        </div>
        <div v-if="warnPending" class="small faint" style="margin-top: -4px">{{ T('allNote', { n: warnPending }) }}</div>
        <div class="aifilter">
          <div class="seg" role="group">
            <button v-for="f in (['all', 'pending', 'adopted', 'dismissed'] as Filter[])" :key="f" type="button" :aria-pressed="filter === f" :data-testid="`ai-filter-${f}`" @click="filter = f">
              {{ T(`f.${f}`) }} {{ f === 'all' ? items.length : f === 'pending' ? c.pending + c.reverted : c[f] }}
            </button>
          </div>
        </div>
        <AiSuggestCard
          v-for="it in shown"
          :key="it.id"
          :ref="(el) => { cards[it.id] = el as InstanceType<typeof AiSuggestCard> | null }"
          :item="it"
          :open="isOpen(it)"
          :can-write="canWrite"
          :can-kb="canKb"
          :busy="busy"
          @toggle="open[it.id] = !isOpen(it)"
          @adopt="(content) => askAdopt(it, content)"
          @dismiss="act(it, 'dismiss')"
          @restore="act(it, 'restore')"
          @jump="jump"
        />
        <p v-if="!shown.length" class="small faint">{{ T('nothing') }}</p>
      </template>
    </div>

    <div v-if="log.length && (st === 'done' || st === 'idle' || st === 'off' || st === 'empty')" class="alog" data-testid="ai-log">
      <h3><Icon name="history" small />{{ T('log') }}<span class="meta">{{ T('logMeta') }}</span></h3>
      <ul class="loglist">
        <li v-for="r in log" :key="r.id" :class="{ 'is-undone': r.status === 'reverted' }" :data-testid="`ai-log-${r.id}`">
          <div class="lw">
            <span class="what">{{ r.check.title_display || r.title || `#${r.id}` }}</span>
            <div class="lm">
              <span>{{ fmtTime(r.decided_at) }}</span>
              <span><Icon name="user" small />{{ r.decided_by }}</span>
              <span>{{ r.edited ? T('logEdited') : T('logSingle') }}</span>
              <span class="mono">{{ r.skill }}</span>
              <span v-if="r.connection"><Icon name="plug" small />{{ r.connection }}</span>
              <span v-if="r.status === 'reverted'" class="ud">{{ T('undone') }} {{ fmtTime(r.reverted_at) }}</span>
            </div>
          </div>
          <template v-if="r.status === 'adopted' && canWrite && (!r.kb || canKb)">
            <button v-if="canRevert(r)" class="btn btn-xs" type="button" :disabled="busy" data-testid="ai-undo" @click="act(r, 'revert')"><Icon name="rollback" small />{{ T('undo') }}</button>
            <span v-else class="small faint" :title="String(REVERT_DAYS)">{{ T('useHistory') }}</span>
          </template>
        </li>
      </ul>
    </div>

    <div v-if="confirm" class="modal-back" data-testid="ai-confirm" @click.self="confirm = null" @keydown.esc="confirm = null">
      <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true">
        <div class="modal-h"><h2>{{ T('confirmT') }}</h2><button class="btn btn-ghost btn-sm" type="button" @click="confirm = null"><Icon name="x" small /></button></div>
        <div class="modal-b stack" style="gap: 10px">
          <p class="small">{{ T('confirmD') }}</p>
          <template v-for="(ck, i) in confirm.checks" :key="i">
            <div v-if="ck.result?.result" class="vf" :class="ck.status === 'warn' ? 'warn' : 'pass'">
              <Icon :name="ck.status === 'warn' ? 'warn' : 'ok'" />
              <div>{{ T('scriptRes', { a: ck.result.result.lines_added ?? 0, d: ck.result.result.lines_removed ?? 0, o: ck.result.result.lines_overridden ?? 0 }) }}</div>
            </div>
          </template>
          <label class="chk check"><input v-model="confirm.seen" type="checkbox" data-testid="ai-confirm-seen"><span>{{ T('confirmChk') }}</span></label>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="confirm = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-ai" type="button" :disabled="!confirm.seen" data-testid="ai-confirm-ok" @click="confirmOk">{{ T('adopt') }}</button>
        </div>
      </div>
    </div>
  </section>
</template>
