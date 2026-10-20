<script setup lang="ts">
/**
 * 未识别行归因（M8-5，预览 DevelopDocs/ui-preview/M8/kb.html“未识别行归因”）：未识别行页右侧的 AI 面板。
 * skill unknown-triage，scope 固定 unknown-lines；勾选了写法时只发这些写法，否则后端取次数最多的 30 组。
 * 同时读取本 scope 的建议，按写法汇总归因（缺命令卡 / 版本差异 / 写法变体 / 未通过 / 已送审）交给表格显示。
 */
import { computed, onMounted, ref } from 'vue'
import { get } from '@/api'
import Icon from '@/components/Icon.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { projectPath, query, type ListResult } from '@/components/ai-suggest/logic'
import { useProject } from '@/stores/project'
import { triageMarks, UNKNOWN_SCOPE, type TriageMark } from './logic'

const props = withDefaults(defineProps<{ patterns?: string[] }>(), { patterns: () => [] })
const emit = defineEmits<{ marks: [marks: Record<string, TriageMark>]; state: [state: string]; close: [] }>()
const project = useProject()
const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const params = computed(() => (props.patterns.length ? { patterns: props.patterns } : {}))

async function loadMarks(): Promise<void> {
  if (!project.ref) return
  try {
    const r = await get<ListResult>(projectPath(project.ref, `/ai/suggestions${query({ skill: 'unknown-triage', scope: UNKNOWN_SCOPE, limit: 200 })}`))
    emit('marks', triageMarks(r.items))
  } catch { /* 归因列只是辅助显示，取不到时不影响本页 */ }
}
function onState(s: string): void {
  emit('state', s)
  if (s === 'done' || s === 'empty') void loadMarks()
}
onMounted(loadMarks)
defineExpose({ start: () => panel.value?.start(), reload: loadMarks })
</script>

<template>
  <aside class="ut-side" data-testid="unknown-ai-side">
    <div class="ut-h">
      <span class="small faint">{{ patterns.length ? $t('kb-ai.ut.picked', { n: patterns.length }) : $t('kb-ai.ut.top') }}</span>
      <button class="btn btn-xs btn-ghost ml-auto" type="button" data-testid="unknown-ai-close" @click="emit('close')"><Icon name="x" small />{{ $t('kb-ai.ut.close') }}</button>
    </div>
    <AiSuggestPanel ref="panel" skill="unknown-triage" :params="params" :scope="UNKNOWN_SCOPE" @state="onState" @changed="loadMarks" />
  </aside>
</template>

<style scoped>
.ut-side { display: flex; flex-direction: column; gap: 6px; min-height: 0; overflow: auto; }
.ut-h { display: flex; align-items: center; gap: 8px; }
</style>
