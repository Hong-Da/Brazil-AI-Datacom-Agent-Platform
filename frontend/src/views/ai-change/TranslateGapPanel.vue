<script setup lang="ts">
/**
 * 配置翻译页的“翻译未支持项”（M8-4，预览 change.html 第三个页签）：列出翻译时不支持或原文保留的行，右侧面板给出目标平台的
 * 等价写法（每条用目标命令卡解析验证，逐条确认）；采纳后重新翻译，译文里来自 AI 的行由后端写入并标出（ai_lines）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { gapRows, scopes, type Unsupported } from './logic'
import './ai-change.css'

const props = defineProps<{
  deviceId: number
  to: string
  ruleSet?: string | null
  interfaceMap?: Record<string, string> | null
  unsupported: Unsupported[]
  aiLines?: number[]
  outText: string
  srcText: string
}>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-change.${k}`, p ?? {})

const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiState = ref('loading')
const scope = computed(() => scopes.translate(props.deviceId, props.to))
const params = computed(() => {
  const p: Record<string, unknown> = { device_id: props.deviceId, to: props.to }
  if (props.ruleSet) p.rule_set = props.ruleSet
  if (props.interfaceMap && Object.keys(props.interfaceMap).length) p.interface_map = props.interfaceMap
  return p
})
const src = computed(() => props.srcText.split('\n'))
const rows = computed(() => gapRows(props.unsupported).map((r) => ({ ...r, src: src.value[r.line - 1] ?? r.text })))
const outLines = computed(() => props.outText.split('\n'))
const aiOut = computed(() => (props.aiLines ?? []).map((n) => ({ n, text: outLines.value[n - 1] ?? '' })))
</script>

<template>
  <section class="aic-grid mt16" data-testid="ai-gap">
    <section class="panel">
      <div class="panel-h">
        <h2>{{ T('gapT') }}</h2>
        <span class="meta">{{ T('gapMeta') }}</span>
        <span class="ml-auto"><AiEntryButton :skills="['translate-gap']" :busy="aiState === 'running'" small @run="panel?.start()" /></span>
      </div>
      <div v-if="aiOut.length" class="aic-row small" data-testid="ai-gap-lines"><Icon name="spark" small />{{ T('aiLines', { n: aiOut.length }) }}</div>
      <div class="tbl-wrap">
        <table class="tbl aic-gap" data-testid="ai-gap-table">
          <tbody>
            <tr v-for="r in rows" :key="r.line" :data-line="r.line">
              <td class="mono small">L{{ r.line }}</td>
              <td><div class="src">{{ r.src }}</div><div v-if="r.schema" class="small faint mono">{{ r.schema }}</div></td>
              <td>
                <div v-if="r.ai && r.ai.kind === 'none'" class="dst">{{ T('gapNone') }}</div>
                <div v-else-if="r.ai" class="dst" :title="T('gapAi')">{{ r.ai.config }}</div>
                <span v-else class="none">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <div class="aic-side">
      <AiSuggestPanel ref="panel" skill="translate-gap" :params="params" :scope="scope" @state="aiState = $event" @changed="emit('changed')" />
    </div>
  </section>
</template>
