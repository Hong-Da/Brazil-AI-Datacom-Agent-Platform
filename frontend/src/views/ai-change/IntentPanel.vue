<script setup lang="ts">
/**
 * 增量变更页的“变更意图转脚本”（M8-4，预览 change.html 第一个页签）：一句话描述 → AI 给出目标图改动（右侧建议面板，
 * 校验与采纳；采纳需二次确认）→ 代码把已采纳的改动合并生成变更脚本（紫色行号来自 AI 改动）、回退脚本、影响分析与模拟执行。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { get, errorText } from '@/api'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { projectPath, query, type ListResult } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { flowSteps, scopes, type ChangePlan } from './logic'
import './ai-change.css'

const props = defineProps<{ deviceId: number | null; deviceName?: string }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-change.${k}`, p ?? {})
const project = useProject()

const intent = ref('')
const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const plan = ref<ChangePlan | null>(null)
const planErr = ref('')
const showRb = ref(false)
/** 这台设备运行过：有建议时面板一开始就显示；没有时等写了描述再显示（运行前估计需要描述） */
const hasRun = ref(false)
const scope = computed(() => (props.deviceId === null ? '' : scopes.intent(props.deviceId)))
const params = computed(() => ({ device_id: props.deviceId, intent: intent.value.trim() }))
const steps = computed(() => flowSteps(aiState.value, plan.value?.adopted.length ?? 0))
const rows = computed(() => (showRb.value ? (plan.value?.rollback ?? '').split('\n').map((text) => ({ text, k: 'frame', seq: null })) : plan.value?.rows ?? []))

/** 最近一次运行（面板显示的那一批）里已采纳的改动合并后的变更。 */
async function loadPlan(): Promise<void> {
  planErr.value = ''
  if (!scope.value || !project.ref) { plan.value = null; return }
  try {
    const r = await get<ListResult>(projectPath(project.ref, `/ai/suggestions${query({ skill: 'intent-script', scope: scope.value, limit: 1 })}`))
    const bid = r.items[0]?.batch_id
    hasRun.value = !!bid
    plan.value = bid ? await get<ChangePlan>(projectPath(project.ref, `/ai/change/plan?batch_id=${bid}`)) : null
  } catch (e) {
    planErr.value = errorText(e)
  }
}
function run(): void {
  if (!intent.value.trim()) return
  void panel.value?.start()
}
watch(scope, () => void loadPlan(), { immediate: true })
</script>

<template>
  <section class="aic-grid mt16" data-testid="ai-intent">
    <div class="aic-stack">
      <section class="panel">
        <div class="aic-intent">
          <label class="field-label" for="aic-intent-text">{{ T('intentLbl') }}</label>
          <textarea id="aic-intent-text" v-model="intent" class="textarea" :placeholder="T('intentPh')" maxlength="2000" :disabled="deviceId === null" data-testid="ai-intent-text" />
          <div class="toolbar">
            <AiEntryButton :skills="['intent-script']" :busy="aiState === 'running'" :label="T('intentBtn')" small @run="run" />
            <span class="small faint">{{ deviceId === null ? T('needDevice') : T('intentNote') }}</span>
          </div>
          <div class="flow" data-testid="ai-intent-flow">
            <span v-for="s in steps" :key="s.k" class="fs" :class="[s.kind, { cur: s.cur }]" :data-cur="s.cur"><Icon :name="s.icon" small />{{ T(`flow.${s.k}`) }}</span>
          </div>
        </div>
      </section>
      <section class="panel" data-testid="ai-intent-script">
        <div class="panel-h">
          <h2>{{ T('scriptT') }}</h2>
          <span class="meta">{{ T('scriptMeta') }}</span>
          <span v-if="plan?.rows" class="ml-auto seg" role="group">
            <button type="button" :aria-pressed="!showRb" @click="showRb = false">{{ T('scriptT') }}</button>
            <button type="button" :aria-pressed="showRb" data-testid="ai-intent-rb" @click="showRb = true">{{ T('rollback') }}</button>
          </span>
        </div>
        <div v-if="planErr" class="notice err" style="margin: 10px"><Icon name="err" /><div class="grow small">{{ planErr }}</div></div>
        <div v-else-if="!plan?.rows" class="aic-empty">{{ T('scriptEmpty') }}</div>
        <template v-else>
          <div class="aic-code" data-testid="ai-intent-code">
            <div v-for="(r, i) in rows" :key="i" class="l" :class="r.k" :data-k="r.k"><span class="n">{{ i + 1 }}</span><span class="t">{{ r.text }}</span></div>
          </div>
          <div class="aic-impact">
            <div><b>{{ plan.summary?.ops ?? 0 }}</b>{{ T('ops') }}</div>
            <div><b>{{ plan.impact?.objects ?? 0 }}</b>{{ T('impObjects') }}</div>
            <div><b>{{ plan.impact?.business ?? 0 }}</b>{{ T('impBiz') }}</div>
            <div>
              <span class="vchip" :class="plan.verify && plan.rollback_verify ? 'pass' : 'fail'" data-testid="ai-intent-sim"><Icon :name="plan.verify && plan.rollback_verify ? 'ok' : 'err'" small />{{ plan.verify && plan.rollback_verify ? T('simOk') : T('simFail') }}</span>
              <router-link v-if="plan.script_info" class="small" style="display: block; margin-top: 4px" :to="{ name: 'scripts' }" data-testid="ai-intent-open">{{ T('openScript') }}</router-link>
            </div>
          </div>
        </template>
      </section>
    </div>
    <div class="aic-side">
      <div v-if="deviceId !== null && !hasRun && !intent.trim()" class="panel aic-empty" data-testid="ai-intent-wait">{{ T('intentWait') }}</div>
      <AiSuggestPanel v-else-if="deviceId !== null" ref="panel" skill="intent-script" :params="params" :scope="scope" @state="aiState = $event" @changed="loadPlan" />
    </div>
  </section>
</template>
