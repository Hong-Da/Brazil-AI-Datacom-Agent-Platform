<script setup lang="ts">
/**
 * 报告摘要（report-summary，M8-5；预览 DevelopDocs/ui-preview/M8/report.html 的“导出”栏）：检查、基线、对比、变更报告共用。
 * 复选框“包含 AI 摘要”（v-model，默认勾选，导出时作为 include_ai_summary 传给接口）+ AI 入口 + 建议面板（中文、英文两条，采纳即放进报告）。
 * 范围由 reportScope 算出（与后端一致）；配置文本（没有导入的设备）没有范围，只显示一行说明。
 * 用法：<ReportAiSummary v-model="incAi" kind="check" :params="{ device_id: 3 }" />
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { reportScope, type ReportKind } from '@/components/ai-suggest/logic'

const props = defineProps<{ kind: ReportKind; params: Record<string, unknown> | null }>()
const include = defineModel<boolean>({ default: true })
const { t } = useI18n()
const T = (k: string) => t(`kb-ai.${k}`)

const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const open = ref(false)
const scope = computed(() => (props.params ? reportScope(props.kind, props.params as Parameters<typeof reportScope>[1]) : null))
const runParams = computed(() => ({ kind: props.kind, ...(props.params ?? {}) }))
/** 已有建议（运行过）时自动展开；空闲、未配置 AI 时收起，入口按钮上已有提示。 */
const hasContent = computed(() => !['loading', 'idle', 'off', 'error'].includes(aiState.value))
watch(scope, () => { open.value = false })
watch(aiState, (s, old) => { if (old === 'loading' && s === 'done') open.value = true })

async function run(): Promise<void> {
  open.value = true
  await nextTick()
  await panel.value?.start()
}
</script>

<template>
  <div class="ras" data-testid="report-ai" :data-scope="scope ?? ''">
    <div class="ras-h">
      <label class="check"><input v-model="include" type="checkbox" data-testid="report-ai-include" /><span>{{ T('ra.include') }}</span></label>
      <span class="ml-auto" />
      <template v-if="scope">
        <button v-if="hasContent || open" class="btn btn-xs btn-ghost" type="button" :aria-expanded="open" data-testid="report-ai-toggle" @click="open = !open">{{ open ? T('ra.hide') : T('ra.show') }}</button>
        <AiEntryButton :skills="['report-summary']" :busy="aiState === 'running'" small @run="run" />
      </template>
    </div>
    <p class="small faint">{{ T('ra.note') }}</p>
    <p v-if="!scope" class="small faint na" data-testid="report-ai-na"><Icon name="info" small />{{ T('ra.na') }}</p>
    <div v-if="scope" v-show="open" class="ras-p" data-testid="report-ai-panel">
      <p class="small faint">{{ T('ra.adoptHint') }}</p>
      <AiSuggestPanel ref="panel" skill="report-summary" :params="runParams" :scope="scope" flat @state="aiState = $event" />
    </div>
  </div>
</template>

<style scoped>
.ras { border: 1px dashed var(--ai-line, var(--line-strong)); border-radius: 7px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; background: var(--surface); }
.ras-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ras .check { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.ras p { margin: 0; }
.na { display: flex; align-items: center; gap: 6px; }
.ras-p { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
</style>
