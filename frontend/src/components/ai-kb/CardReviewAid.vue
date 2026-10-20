<script setup lang="ts">
/**
 * 命令卡审核助手（M8-5，预览 DevelopDocs/ui-preview/M8/kb.html“命令卡审核助手”）：审核队列里命令卡条目的详情下方。
 * 可选粘贴文档原文（2 万字以内），skill card-review 对照它标出参数类型、默认值、取消写法可疑的地方。
 * 只标注不改卡：采纳只是记录“已确认这条标注”，要改卡请用“修改后通过”。
 */
import { computed, nextTick, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { cardScope, MAX_DOC } from './logic'

const props = defineProps<{ cardId: string }>()
const panel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const state = ref('loading')
const open = ref(false)
const doc = ref('')
const shown = computed(() => open.value || ['done', 'running', 'empty', 'failed', 'cancelled'].includes(state.value))
const params = computed(() => (doc.value.trim() ? { card_id: props.cardId, doc_text: doc.value } : { card_id: props.cardId }))

async function run(): Promise<void> {
  open.value = true
  await nextTick()
  await panel.value?.start()
}
watch(() => props.cardId, () => { open.value = false; doc.value = '' })
</script>

<template>
  <div class="cra" data-testid="card-review-aid">
    <div class="cra-h">
      <b class="small"><Icon name="spark" small /> {{ $t('kb-ai.cr.title') }}</b>
      <span class="small faint">{{ $t('kb-ai.cr.sub') }}</span>
      <span class="ml-auto row" style="gap: 6px">
        <button v-if="!shown" class="btn btn-xs btn-ghost" type="button" data-testid="card-review-open" @click="open = true">{{ $t('kb-ai.cr.open') }}</button>
        <AiEntryButton :skills="['card-review']" :busy="state === 'running'" :label="$t('kb-ai.cr.btn')" small @run="run" />
      </span>
    </div>
    <div v-show="shown" class="cra-b">
      <label class="field">
        <span class="small">{{ $t('kb-ai.cr.doc') }} <span class="faint">{{ $t('kb-ai.cr.docHint', { n: doc.length.toLocaleString(), m: MAX_DOC.toLocaleString() }) }}</span></span>
        <textarea v-model="doc" class="textarea mono small" rows="5" :maxlength="MAX_DOC" spellcheck="false" :placeholder="$t('kb-ai.cr.docPh')" data-testid="kb-doc-text" />
      </label>
      <div class="notice info"><Icon name="info" small /><div class="grow small">{{ $t('kb-ai.cr.note') }}</div></div>
      <AiSuggestPanel ref="panel" skill="card-review" :params="params" :scope="cardScope(cardId)" flat @state="state = $event" />
    </div>
  </div>
</template>

<style scoped>
.cra { margin-top: 18px; border-top: 1px dashed var(--ai-line); padding-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.cra-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cra-b { display: flex; flex-direction: column; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.textarea { width: 100%; resize: vertical; min-height: 90px; }
</style>
