<script setup lang="ts">
/**
 * 试运行：输入来自样例 / 回归集或候选案例 / 手填（JSON，与样例的 input 结构相同）；模式为真实 AI 或回放（不调用 AI）。
 * 可用编辑中的定义（草稿）试运行；结果显示实际发送的内容（脱敏后）、回复、代码校验与得分。试运行不计入统计。
 */
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { ApiError, errorText, post } from '@/api'
import Bits from './Bits.vue'
import { useSkillCtx, useT } from './ctx'
import { inputSummary, vname } from './logic'
import type { TestResult } from './types'

const { detail, draft, dirty, cases, goTab } = useSkillCtx()
const { T, L } = useT()
const configured = computed(() => !!detail.value?.ai.configured)
const samples = computed(() => detail.value?.samples ?? [])
const reg = computed(() => cases.value?.regression ?? [])
const cand = computed(() => cases.value?.candidates ?? [])

type Src = 'sample' | 'case' | 'manual'
const src = ref<Src>(samples.value.length ? 'sample' : reg.value.length + cand.value.length ? 'case' : 'manual')
const mode = ref<'ai' | 'replay'>(configured.value ? 'ai' : 'replay')
const sample = ref(0)
const caseId = ref<number | null>(reg.value[0]?.id ?? cand.value[0]?.id ?? null)
const manualInput = ref(JSON.stringify(samples.value[0]?.input ?? {}, null, 2))
const manualReply = ref(samples.value[0]?.reply ?? '')
const useDraft = ref(true)
const running = ref(false)
const result = ref<TestResult | null>(null)
const resDraft = ref(false)
const err = ref('')
watch(configured, (v) => { if (!v) mode.value = 'replay' })
watch(cases, () => { if (caseId.value === null) caseId.value = reg.value[0]?.id ?? cand.value[0]?.id ?? null })

const inputErr = computed(() => {
  if (src.value !== 'manual') return ''
  try {
    const v = JSON.parse(manualInput.value || '{}')
    return v && typeof v === 'object' && !Array.isArray(v) ? '' : T('test.inputObj')
  } catch { return T('test.inputJson') }
})
const canRun = computed(() => {
  if (running.value || inputErr.value) return false
  if (src.value === 'sample') return samples.value.length > 0
  if (src.value === 'case') return caseId.value !== null
  return mode.value === 'ai' || !!manualReply.value.trim()
})

async function run(): Promise<void> {
  if (!detail.value) return
  running.value = true
  err.value = ''
  const body: Record<string, unknown> = { mode: mode.value }
  if (src.value === 'sample') body.sample = samples.value[sample.value]?.index ?? sample.value
  else if (src.value === 'case') body.case_id = caseId.value
  else {
    body.input = JSON.parse(manualInput.value || '{}')
    if (mode.value === 'replay') body.reply = manualReply.value
  }
  const withDraft = useDraft.value && dirty.value
  if (withDraft && draft.value) body.definition = draft.value
  try {
    result.value = await post<TestResult>(`/ai/skills/${detail.value.id}/test`, body)
    resDraft.value = withDraft
  } catch (e) {
    err.value = e instanceof ApiError && (e.data as { status?: string } | null)?.status === 'not_configured' ? T('test.needAi') : errorText(e)
  } finally { running.value = false }
}
const modelName = computed(() => detail.value?.model || T('model.unset'))
</script>

<template>
  <div v-if="detail" class="test-grid" data-testid="sk-test">
    <div>
      <section class="panel">
        <div class="panel-h"><h2>{{ T('test.input') }}</h2></div>
        <div class="panel-b">
          <div class="opt">
            <span class="lbl">{{ T('test.source') }}</span>
            <div class="seg" role="group" data-testid="test-src">
              <button v-for="s in (['sample', 'case', 'manual'] as const)" :key="s" type="button" :aria-pressed="src === s" :data-src="s" @click="src = s">{{ T(`test.src.${s}`) }}</button>
            </div>
            <template v-if="src === 'sample'">
              <template v-if="samples.length">
                <select v-model.number="sample" class="select" data-testid="test-sample">
                  <option v-for="(s, i) in samples" :key="s.index" :value="i">{{ L(s.title) }}</option>
                </select>
                <span class="hint">{{ T('test.sampleHint') }}</span>
              </template>
              <span v-else class="hint">{{ T('test.noSamples') }}</span>
            </template>
            <template v-else-if="src === 'case'">
              <template v-if="reg.length || cand.length">
                <select v-model.number="caseId" class="select" data-testid="test-case">
                  <optgroup v-if="reg.length" :label="T('cases.reg')"><option v-for="c in reg" :key="c.id" :value="c.id">#{{ c.id }} {{ inputSummary(c.input, 60) }}</option></optgroup>
                  <optgroup v-if="cand.length" :label="T('cases.cand')"><option v-for="c in cand" :key="c.id" :value="c.id">#{{ c.id }} {{ inputSummary(c.input, 60) }}</option></optgroup>
                </select>
                <span class="hint">{{ T('test.caseHint') }}</span>
              </template>
              <span v-else class="hint">{{ T('test.noCases') }} <a href="#" @click.prevent="goTab('cases')">{{ T('tab.cases') }}</a></span>
            </template>
            <template v-else>
              <textarea v-model="manualInput" class="textarea mono" rows="6" :class="{ 'is-error': inputErr }" :aria-label="T('test.manualInput')" data-testid="test-manual-input" />
              <span class="hint" :style="inputErr ? { color: 'var(--red-ink)' } : undefined">{{ inputErr || T('test.manualHint') }}</span>
            </template>
          </div>
          <div class="opt">
            <span class="lbl">{{ T('test.mode') }}</span>
            <div class="seg" role="group" data-testid="test-mode">
              <button type="button" :aria-pressed="mode === 'ai'" :disabled="!configured" data-mode="ai" data-testid="test-mode-ai" @click="mode = 'ai'">{{ T('test.modeAi') }}</button>
              <button type="button" :aria-pressed="mode === 'replay'" data-mode="replay" data-testid="test-mode-replay" @click="mode = 'replay'">{{ T('test.modeReplay') }}</button>
            </div>
            <span class="hint" data-testid="test-mode-hint">{{ !configured ? T('test.onlyReplay') : mode === 'ai' ? T('test.aiHint', { m: modelName }) : T('test.replayHint') }}</span>
            <textarea v-if="src === 'manual' && mode === 'replay'" v-model="manualReply" class="textarea mono" rows="3" :placeholder="T('test.replyPh')" data-testid="test-manual-reply" />
          </div>
          <div class="opt">
            <label class="check"><input v-model="useDraft" type="checkbox" data-testid="test-use-draft"><span>{{ T('test.useDraft') }}</span></label>
            <span class="hint">{{ dirty ? T('test.draftDirty') : T('test.draftClean', { v: vname(detail.active) ?? T('ver.builtinLower') }) }}</span>
          </div>
          <div class="opt">
            <button class="btn btn-primary" type="button" :disabled="!canRun" data-testid="test-run" @click="run"><Icon name="play" small />{{ running ? T('test.running') : T('test.run') }}</button>
            <span class="hint">{{ T('test.notCounted') }}</span>
          </div>
        </div>
      </section>
    </div>
    <div>
      <div v-if="err" class="notice err" data-testid="test-error"><Icon name="err" /><div class="grow">{{ err }}</div></div>
      <section v-else-if="!result" class="panel"><div class="test-empty"><Icon name="flask" /><p>{{ T('test.empty') }}</p></div></section>
      <template v-else>
        <section class="panel" data-testid="test-result">
          <div class="panel-b res-h">
            <Bits kind="vs" :s="result.check.status" />
            <span class="score">{{ T('test.score') }} <b data-testid="test-score">{{ result.check.score.toFixed(1) }}</b></span>
            <span v-if="result.mode === 'replay'" class="replay-flag" data-testid="test-replay-flag"><Icon name="refresh" small />{{ T('test.replayFlag') }}</span>
            <template v-else><span class="ailabel"><Icon name="spark" small />AI</span><span class="small faint">{{ result.ai.model }} · {{ result.ai.tokens_in + result.ai.tokens_out }} tokens · {{ (result.ai.ms / 1000).toFixed(1) }} s</span></template>
            <span v-if="resDraft" class="tag t-amber">{{ T('test.usedDraft') }}</span>
            <span class="small faint ml-auto">{{ T('test.scoreRule') }}</span>
          </div>
        </section>
        <section class="panel mt12">
          <div class="panel-h"><h2>{{ T('test.sent') }}</h2><span class="meta">{{ T('test.sentMeta') }}</span></div>
          <div class="panel-b">
            <div v-for="(s, i) in result.sent" :key="i">
              <div v-if="result.sent.length > 1" class="section-t">{{ s.step }}</div>
              <div class="sent"><div class="sh"><b>system</b><span class="faint">{{ T('test.chars', { n: s.system.length }) }}</span></div><pre>{{ s.system }}</pre></div>
              <div class="sent"><div class="sh"><b>prompt</b><span class="faint">{{ T('test.chars', { n: s.prompt.length }) }}</span></div><pre>{{ s.prompt }}</pre></div>
            </div>
          </div>
        </section>
        <section class="panel mt12">
          <div class="panel-h"><h2>{{ T('test.reply') }}</h2></div>
          <div class="panel-b reply">
            <template v-if="result.reply">
              <div v-if="result.mode === 'replay'"><div style="margin-bottom: 6px"><span class="replay-flag">{{ T('test.recorded') }}</span></div><pre data-testid="test-reply">{{ result.reply }}</pre></div>
              <div v-else class="aiblk"><div style="margin-bottom: 6px"><span class="ailabel"><Icon name="spark" small />AI</span></div><pre data-testid="test-reply">{{ result.reply }}</pre></div>
            </template>
            <p v-else class="small faint">{{ T('test.noReply') }}</p>
          </div>
        </section>
        <section class="panel mt12">
          <div class="panel-h"><h2>{{ T('test.checks') }}</h2></div>
          <div class="panel-b">
            <div class="checks" data-testid="test-checks">
              <div v-for="(c, i) in result.check.items" :key="i" class="ck" :class="c.ok ? 'res-ok' : 'res-bad'">
                <Icon :name="c.ok ? 'ok' : 'err'" small /><code>{{ c.reason || '—' }}</code><span>{{ c.ok ? T('test.ckOk') : T('test.ckBad') }}<template v-if="c.line"> · {{ T('test.line', { n: c.line }) }}</template></span>
                <span v-if="c.text" class="why">{{ c.text }}</span>
              </div>
              <p v-if="!result.check.items.length" class="small faint">{{ T('test.noItems') }}</p>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
