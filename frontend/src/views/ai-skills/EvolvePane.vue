<script setup lang="ts">
/**
 * 进化：AI（skill-evolve）读失败案例与用户更正提出候选版本 → 回归集上新旧版本各跑一次、由代码校验打分 → 管理员批准或放弃。
 * 候选不会自动上线。未配置 AI、回归集为空、元 skill 自己时不能发起（说明原因）；已算好的候选仍可批准或放弃。
 */
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { ApiError, errorText, get, post, waitTask, type Task } from '@/api'
import { shortTime } from '@/views/account/account'
import Bits from './Bits.vue'
import DiffList from './DiffList.vue'
import { useSkillCtx, useT } from './ctx'
import { br, evolveBlock, evoSummary, f2, inputSummary, keptVars, stCls } from './logic'
import type { Definition, Evolution, EvolutionDetail } from './types'

const { detail, cases, loadCases, reload, flash, goTab } = useSkillCtx()
const { T, stLabel, vlabel } = useT()
const list = ref<Evolution[]>([])
const sel = ref<EvolutionDetail | null>(null)
const base = ref<Definition | null>(null)
const err = ref('')
const running = ref<Task | null>(null)
const startErr = ref('')
const onlyChanged = ref(false)
const confirm = ref<'approve' | 'reject' | null>(null)
const note = ref('')
const busy = ref(false)
const known = computed(() => (detail.value?.variables ?? []).map((v) => v.name))
const regN = computed(() => cases.value?.regression.length ?? 0)
const pending = computed(() => list.value.find((e) => e.status === 'pending') ?? null)

async function loadList(): Promise<void> {
  if (!detail.value) return
  err.value = ''
  try {
    const r = await get<{ evolutions: Evolution[] }>(`/ai/skills/${detail.value.id}/evolutions`)
    list.value = r.evolutions
    const pick = sel.value ? r.evolutions.find((e) => e.id === sel.value!.id) : (r.evolutions.find((e) => e.status === 'pending') ?? r.evolutions[0])
    if (pick) await open(pick.id)
    else sel.value = null
  } catch (e) { err.value = errorText(e) }
}
async function open(id: number): Promise<void> {
  if (!detail.value) return
  try {
    const d = await get<EvolutionDetail>(`/ai/skills/${detail.value.id}/evolutions/${id}`)
    sel.value = d
    onlyChanged.value = false
    base.value = null
    get<{ definition: Definition }>(`/ai/skills/${detail.value.id}/versions/${encodeURIComponent(d.base_version)}`).then((r) => { if (sel.value?.id === id) base.value = r.definition }).catch(() => {})
  } catch (e) { flash(errorText(e)) }
}
onMounted(() => { void loadList(); if (!cases.value) void loadCases() })

const why = computed(() => {
  const d = detail.value
  if (!d) return ''
  const k = evolveBlock({ configured: d.ai.configured, sid: d.id, enabled: d.enabled, regression: regN.value, pending: pending.value, running: !!running.value })
  return k ? T(k, { n: pending.value?.id ?? '' }) : ''
})
const step = computed(() => {
  if (running.value) return (running.value.progress ?? 0) < 10 ? 1 : 2
  if (!regN.value && !sel.value) return 0
  const s = sel.value?.status
  return s === 'pending' ? 3 : s === 'approved' || s === 'rejected' ? 4 : regN.value ? 1 : 0
})
const steps = computed(() => [
  [T('evo.step1'), regN.value ? T('evo.step1n', { n: regN.value }) : T('evo.step1none')],
  [T('evo.step2'), 'skill-evolve'],
  [T('evo.step3'), T('evo.step3s')],
  [T('evo.step4'), T('evo.step4s')],
])

async function start(): Promise<void> {
  if (!detail.value || why.value) return
  startErr.value = ''
  try {
    const r = await post<{ task_id: string }>(`/ai/skills/${detail.value.id}/evolve`, { limit: 20 })
    running.value = { id: r.task_id, kind: 'skill-evolve', status: 'queued', progress: 0, message: '', result: null, created_at: null, updated_at: null }
    flash(T('evo.started'))
    const t = await waitTask<EvolutionDetail>(r.task_id, (x) => { running.value = x })
    running.value = null
    if (t.status === 'failed') startErr.value = t.message || T('evo.taskFailed')
    sel.value = null
    await Promise.all([loadList(), reload(true)])
    if (t.result?.id) await open(t.result.id)
  } catch (e) {
    running.value = null
    const st = e instanceof ApiError ? (e.data as { status?: string } | null)?.status : undefined
    startErr.value = st === 'not_configured' ? T('evo.whyNoAi') : st === 'no_cases' ? T('evo.whyNoCases') : errorText(e)
  }
}
function progMsg(t: Task): string {
  const m = t.message || ''
  if (m === 'propose') return T('evo.progPropose')
  if (m.startsWith('case ')) return T('evo.progCase', { n: m.slice(5) })
  if (m === 'save') return T('evo.progSave')
  return m || T('evo.progQueued')
}

const rows = computed(() => sel.value?.scores?.cases ?? [])
const shownRows = computed(() => (onlyChanged.value ? rows.value.filter((r) => r.delta !== 'same') : rows.value))
const sum = computed(() => sel.value?.scores?.summary ?? (rows.value.length ? { ...evoSummary(rows.value), cases: rows.value.length } : null))
const caseText = (id: number) => {
  const c = [...(cases.value?.regression ?? []), ...(cases.value?.candidates ?? [])].find((x) => x.id === id)
  return c ? inputSummary(c.input) : T('evo.caseGone')
}
const vars = computed(() => (base.value && sel.value?.candidate ? keptVars(base.value, sel.value.candidate) : null))

function openConfirm(k: 'approve' | 'reject'): void {
  note.value = k === 'approve' && sel.value ? T('evo.approveNote', { n: sel.value.id, o: f2(sum.value?.old), x: f2(sum.value?.new) }) : ''
  confirm.value = k
}
async function decide(): Promise<void> {
  const k = confirm.value
  confirm.value = null
  if (!k || !detail.value || !sel.value) return
  busy.value = true
  try {
    const r = await post<{ published_version?: string }>(`/ai/skills/${detail.value.id}/evolutions/${sel.value.id}/${k}`, { note: note.value.trim() })
    await Promise.all([loadList(), reload(false)])
    flash(k === 'approve' ? T('evo.approved', { v: r.published_version ?? '' }) : T('evo.rejected', { n: sel.value?.id ?? '' }))
  } catch (e) { flash(errorText(e)) } finally { busy.value = false }
}
watch(() => detail.value?.id, () => { sel.value = null; void loadList() })
</script>

<template>
  <div v-if="detail" data-testid="sk-evolve">
    <p class="small muted" style="margin-bottom: 10px">{{ T('evo.intro') }}</p>
    <div v-if="!detail.ai.configured" class="notice warn" style="margin-bottom: 14px" data-testid="evo-ai-off">
      <Icon name="info" /><div class="grow"><b>{{ T('evo.aiOffTitle') }}</b>{{ T('evo.aiOffText') }}</div>
      <router-link class="btn btn-sm" :to="{ name: 'ai-settings' }"><Icon name="plug" small />{{ T('aiOff.setup') }}</router-link>
    </div>
    <section class="panel">
      <div class="ev-top">
        <div>
          <div class="steps evsteps">
            <div v-for="(s, i) in steps" :key="i" class="st" :class="{ done: i < step, cur: i === step }"><span class="no">{{ i < step ? '✓' : i + 1 }}</span><span>{{ s[0] }}<small>{{ s[1] }}</small></span></div>
          </div>
          <div v-if="running" class="run-prog" data-testid="evo-running">
            <span class="estate running">{{ T('estate.running') }}</span>
            <div class="progress"><i :style="{ width: `${running.progress ?? 0}%` }" /></div>
            <span>{{ progMsg(running) }}</span>
          </div>
        </div>
        <div class="ev-start">
          <button class="btn btn-primary" type="button" :disabled="!!why" data-testid="evo-start" @click="start"><Icon name="dna" small />{{ T('evo.start') }}</button>
          <span class="why" data-testid="evo-why">{{ why || T('evo.cost', { n: Math.min(regN, 20) }) }}</span>
        </div>
      </div>
    </section>
    <div v-if="startErr" class="notice err mt12" data-testid="evo-error"><Icon name="err" /><div class="grow">{{ startErr }}</div></div>
    <div v-if="err" class="notice err mt12"><Icon name="err" /><div class="grow">{{ err }}</div><button class="btn btn-sm" type="button" @click="loadList">{{ $t('c.retry') }}</button></div>

    <section v-if="!regN && !list.length" class="panel mt12">
      <div class="empty" data-testid="evo-empty">
        <h3>{{ T('evo.emptyTitle') }}</h3><p>{{ T('evo.emptyText') }}</p>
        <button class="btn" type="button" @click="goTab('cases')"><Icon name="flask" small />{{ T('evo.openCases') }}</button>
      </div>
    </section>

    <template v-if="sel">
      <div v-if="sel.status === 'approved'" class="notice info mt12"><Icon name="ok" /><div class="grow"><b>{{ T('evo.isApproved', { n: sel.id, v: sel.published_version ?? '' }) }}</b> {{ T('evo.isApprovedText') }}</div><button class="btn btn-sm" type="button" @click="goTab('versions')"><Icon name="history" small />{{ T('tab.versions') }}</button></div>
      <div v-else-if="sel.status === 'rejected'" class="notice mt12"><Icon name="info" /><div class="grow"><b>{{ T('evo.isRejected', { n: sel.id }) }}</b> {{ T('evo.isRejectedText') }}</div></div>
      <div v-else-if="sel.status === 'failed'" class="notice err mt12" data-testid="evo-failed">
        <Icon name="err" />
        <div class="grow">
          <b>{{ T('evo.isFailed', { n: sel.id }) }}</b>
          <ul v-if="sel.error?.issues?.length" class="issues" style="margin: 4px 0 0; padding-left: 18px"><li v-for="(x, i) in sel.error.issues" :key="i">{{ x.field }} · {{ x.key }}{{ x.params ? ` ${JSON.stringify(x.params)}` : '' }}</li></ul>
          <pre v-if="sel.error?.reply" class="mono small" style="white-space: pre-wrap; margin: 6px 0 0; max-height: 160px; overflow: auto">{{ sel.error.reply }}</pre>
        </div>
      </div>

      <div v-if="sel.status !== 'failed' && sum" class="ev-grid" data-testid="evo-detail">
        <section class="panel scorep">
          <div class="panel-h"><h2>{{ T('evo.score') }}</h2><span class="meta">{{ T('evo.scoreMeta', { n: sum.cases }) }}</span></div>
          <div class="panel-b">
            <div class="scorebig">
              <div class="sc"><span class="k">{{ T('evo.current', { v: vlabel(sel.base_version) }) }}</span><span class="v" data-testid="evo-old">{{ f2(sum.old) }}</span></div>
              <span class="arrow"><Icon name="chevR" /></span>
              <div class="sc new"><span class="k">{{ T('evo.cand', { n: sel.id }) }}</span><span class="v" data-testid="evo-new">{{ f2(sum.new) }}</span></div>
              <span class="delta dl" :class="sum.new >= sum.old ? 'up' : 'down'">{{ sum.new >= sum.old ? '+' : '−' }}{{ f2(Math.abs(sum.new - sum.old)) }}</span>
            </div>
            <div class="cnt3b"><span class="up"><b>{{ sum.better }}</b>{{ T('evo.better') }}</span><span class="down"><b>{{ sum.worse }}</b>{{ T('evo.worse') }}</span><span class="same"><b>{{ sum.same }}</b>{{ T('evo.same') }}</span></div>
            <div class="dotsrow">
              <span>{{ vlabel(sel.base_version) }}</span><span class="dots"><i v-for="c in rows" :key="c.case_id" :class="`sw-${stCls(c.old.status)}`" :title="`#${c.case_id} ${stLabel(c.old.status)}`" /></span>
              <span>#{{ sel.id }}</span><span class="dots"><i v-for="c in rows" :key="c.case_id" :class="`sw-${stCls(c.new.status)}`" :title="`#${c.case_id} ${stLabel(c.new.status)}`" /></span>
            </div>
            <Bits kind="legend" />
            <div class="rule">{{ T('evo.rule') }}</div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('evo.notes') }}</h2><span class="ailabel"><Icon name="spark" small />AI</span></div>
          <div class="panel-b">
            <div class="aiblk ainotes"><p>{{ sel.rationale || '—' }}</p><div class="disc">{{ T('evo.disc') }}</div></div>
            <div class="section-t" style="margin-top: 14px">{{ T('test.checks') }}</div>
            <div v-if="vars" class="ck-line" :class="{ bad: vars[1].length }">
              <Icon :name="vars[1].length ? 'err' : 'ok'" />
              <div v-if="vars[1].length">{{ T('evo.varsLost', { v: vars[1].map(br).join(' ') }) }}</div>
              <div v-else>{{ T('evo.varsKept', { n: vars[0].length }) }} <template v-for="n in vars[0]" :key="n"><span class="pv">{{ br(n) }}</span>{{ ' ' }}</template></div>
            </div>
            <dl class="kv small" style="margin-top: 12px">
              <dt>{{ T('evo.base') }}</dt><dd>{{ vlabel(sel.base_version) }}</dd>
              <dt>{{ T('evo.by') }}</dt><dd>{{ sel.created_by || '—' }} · {{ shortTime(sel.created_at) }}</dd>
              <dt>{{ T('evo.input') }}</dt><dd>{{ T('evo.inputN', { n: sum.cases }) }}</dd>
              <template v-if="sel.decided_at"><dt>{{ T('evo.decided') }}</dt><dd>{{ sel.decided_by || '—' }} · {{ shortTime(sel.decided_at) }}</dd></template>
            </dl>
          </div>
        </section>
      </div>

      <section v-if="sel.status !== 'failed' && sel.diff?.length" class="panel mt12">
        <div class="panel-h"><h2>{{ T('evo.diff') }}</h2><span class="meta">{{ T('evo.diffMeta', { v: vlabel(sel.base_version) }) }}</span></div>
        <div class="panel-b"><DiffList :fields="sel.diff" :known="known" view="uni" /></div>
      </section>

      <section v-if="rows.length" class="panel mt12">
        <div class="panel-h"><h2>{{ T('evo.cases') }}</h2><label class="check" style="margin-left: auto"><input v-model="onlyChanged" type="checkbox"><span>{{ T('evo.onlyChanged') }}</span></label></div>
        <div class="tbl-wrap">
          <table class="tbl cmp-tbl" data-testid="evo-cases">
            <thead><tr><th>{{ T('evo.case') }}</th><th>{{ T('cases.input') }}</th><th>{{ T('evo.oldSt', { v: vlabel(sel.base_version) }) }}</th><th class="num">{{ T('evo.pts') }}</th><th>{{ T('evo.newSt') }}</th><th class="num">{{ T('evo.pts') }}</th><th>{{ T('evo.change') }}</th></tr></thead>
            <tbody>
              <tr v-for="c in shownRows" :key="c.case_id" class="cmp-row">
                <td class="mono">#{{ c.case_id }}</td>
                <td class="q">{{ caseText(c.case_id) }}</td>
                <td><Bits kind="vs" :s="c.old.status" /></td><td class="sc">{{ c.old.score }}</td>
                <td><Bits kind="vs" :s="c.new.status" /></td><td class="sc">{{ c.new.score }}</td>
                <td>
                  <span v-if="c.delta === 'better'" class="delta up"><Icon name="up" small />{{ T('evo.dBetter') }}</span>
                  <span v-else-if="c.delta === 'worse'" class="delta down"><Icon name="chevD" small />{{ T('evo.dWorse') }}</span>
                  <span v-else class="delta same">{{ T('evo.dSame') }}</span>
                </td>
              </tr>
            </tbody>
            <tfoot v-if="sum"><tr><td colspan="3">{{ T('evo.mean') }}</td><td class="sc">{{ f2(sum.old) }}</td><td /><td class="sc">{{ f2(sum.new) }}</td><td><span class="delta" :class="sum.new >= sum.old ? 'up' : 'down'">{{ sum.new >= sum.old ? '+' : '−' }}{{ f2(Math.abs(sum.new - sum.old)) }}</span></td></tr></tfoot>
          </table>
        </div>
      </section>

      <div v-if="sel.status === 'pending'" class="actbar" data-testid="evo-actbar">
        <div class="txt"><b>{{ T('evo.noAuto') }}</b> {{ T('evo.noAutoText') }}</div>
        <button class="btn" type="button" :disabled="busy" data-testid="evo-reject" @click="openConfirm('reject')"><Icon name="x" small />{{ T('evo.reject') }}</button>
        <button class="btn btn-primary" type="button" :disabled="busy" data-testid="evo-approve" @click="openConfirm('approve')"><Icon name="check" small />{{ T('evo.approve') }}</button>
      </div>
    </template>

    <section v-if="list.length" class="panel hist mt12">
      <div class="panel-h"><h2>{{ T('evo.hist') }}</h2><span class="meta">{{ T('evo.histMeta') }}</span></div>
      <div class="tbl-wrap">
        <table class="tbl compact" data-testid="evo-hist">
          <thead><tr><th>#</th><th>{{ T('col.time') }}</th><th>{{ T('evo.base') }}</th><th>{{ T('col.status') }}</th><th class="num">{{ T('evo.score') }}</th><th>{{ T('evo.result') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="e in list" :key="e.id" :class="{ 'is-sel': sel?.id === e.id }">
              <td class="n">#{{ e.id }}</td>
              <td class="small muted nowrap">{{ shortTime(e.created_at) }}</td>
              <td>{{ vlabel(e.base_version) }}</td>
              <td><span class="estate" :class="e.status">{{ T(`estate.${e.status}`) }}</span></td>
              <td class="num mono">{{ e.summary ? `${f2(e.summary.old)} → ${f2(e.summary.new)}` : '—' }}</td>
              <td class="small">{{ e.status === 'approved' ? T('evo.resApproved', { v: e.published_version ?? '' }) : e.status === 'rejected' ? T('evo.resRejected') : e.status === 'failed' ? T('evo.resFailed') : T('evo.resPending') }}</td>
              <td class="right"><button class="btn btn-xs" type="button" :disabled="sel?.id === e.id" @click="open(e.id)"><Icon name="eye" small />{{ T('ver.view') }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="confirm && sel" class="modal-back" @click.self="confirm = null">
      <div class="modal" role="dialog" aria-modal="true" style="width: min(560px, 100%)" data-testid="evo-confirm">
        <div class="modal-h"><h2>{{ confirm === 'approve' ? T('evo.approveTitle', { n: sel.id }) : T('evo.rejectTitle', { n: sel.id }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="confirm = null"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 10px">
          <p>{{ confirm === 'approve' ? T('evo.approveText', { id: detail.id, v: (detail.versions ?? 0) + 1 }) : T('evo.rejectText', { v: vlabel(detail.active) }) }}</p>
          <div v-if="confirm === 'approve' && sum" class="notice info"><Icon name="info" /><div class="grow small">{{ T('evo.approveInfo', { o: f2(sum.old), x: f2(sum.new) }) }}</div></div>
          <div class="field"><label for="evoNote">{{ T('evo.noteLabel') }}</label><input id="evoNote" v-model="note" class="input"></div>
        </div>
        <div class="modal-f"><button class="btn" type="button" @click="confirm = null">{{ $t('c.cancel') }}</button><button class="btn" :class="confirm === 'approve' ? 'btn-primary' : 'btn-danger'" type="button" data-testid="evo-confirm-ok" @click="decide">{{ confirm === 'approve' ? T('evo.approve') : T('evo.reject') }}</button></div>
      </div>
    </div>
  </div>
</template>
