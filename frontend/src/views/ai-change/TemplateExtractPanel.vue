<script setup lang="ts">
/**
 * 模板页“从设备提取”的 AI 模板提取（M8-4）：对已选的 1～10 台同类设备，AI 在代码的模板草稿基础上整理变量；
 * 代码用每台设备自己的取值渲染，结果必须与原配置等价（卡片里列出每台设备的核对结果与覆盖率）；采纳后存为我的模板。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { scopes, templateReady } from './logic'
import './ai-change.css'

const props = defineProps<{ ids: number[]; families: string[] }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-change.${k}`, p ?? {})

const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const ready = computed(() => templateReady(props.ids, props.families))
const scope = computed(() => scopes.template(props.ids))
const params = computed(() => ({ device_ids: [...props.ids] }))
</script>

<template>
  <section class="panel mt16" data-testid="ai-template">
    <div class="panel-h">
      <h2>{{ T('tplT') }}</h2>
      <span class="meta">{{ T('tplMeta') }}</span>
      <span class="ml-auto"><AiEntryButton :skills="['template-extract']" :busy="aiState === 'running'" small @run="ready && panel?.start()" /></span>
    </div>
    <div v-if="!ready" class="notice info" style="margin: 10px"><Icon name="info" /><div class="grow">{{ T('tplNeed') }}</div></div>
    <div v-else style="padding: 0 12px 12px">
      <AiSuggestPanel ref="panel" :key="scope" skill="template-extract" :params="params" :scope="scope" flat @state="aiState = $event" @changed="emit('changed')" />
    </div>
  </section>
</template>
