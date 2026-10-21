<script setup lang="ts">
/** 会话附件（REQ-053）：配置（临时设备）/ 文档（参考资料）/ 图片（不经脱敏）；本人可以删除。 */
import { useI18n } from 'vue-i18n'
import { attachDetail, type Attachment } from './ask-sessions'

defineProps<{ attachments: Attachment[]; canEdit: boolean; max: number }>()
const emit = defineEmits<{ (e: 'remove', id: number): void }>()
const { t } = useI18n()
const detail = (a: Attachment) => attachDetail(a, (k, p) => t(k, p ?? {}))
</script>

<template>
  <div v-if="attachments.length" class="atts" data-testid="ask-atts">
    <span class="small faint">{{ $t('ask.att.title') }} {{ attachments.length }}/{{ max }}</span>
    <span v-for="a in attachments" :key="a.id" class="att" :title="$t(`ask.att.hint.${a.kind}`)" :data-testid="`ask-att-${a.id}`">
      <span class="kind" :class="`k-${a.kind}`">{{ $t(`ask.att.kind.${a.kind}`) }}</span>
      <span class="nm">{{ a.name }}</span>
      <span class="small faint">{{ detail(a) }}</span>
      <button v-if="canEdit" class="x" type="button" :aria-label="$t('ask.att.remove')" :data-testid="`ask-att-del-${a.id}`" @click="emit('remove', a.id)">×</button>
    </span>
  </div>
</template>

<style scoped>
.atts { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 14px; border-bottom: 1px solid var(--line); background: var(--surface-2); align-items: center; font-size: 12.5px; }
.att { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: 6px; padding: 3px 6px 3px 8px; background: var(--surface); }
.att .nm { font-family: var(--font-mono); font-size: 12px; color: var(--ink); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kind { font: 600 10.5px var(--font-ui); border-radius: 4px; padding: 0 5px; border: 1px solid; }
.k-config { color: var(--teal-ink); background: var(--teal-soft); border-color: var(--teal-line); }
.k-doc { color: var(--blue-ink); background: var(--blue-soft); border-color: var(--blue-line); }
.k-image { color: var(--amber-ink); background: var(--amber-soft); border-color: var(--amber-line); }
.x { background: none; border: 0; color: var(--ink-3); cursor: pointer; padding: 0 2px; font-size: 14px; line-height: 1; }
.x:hover { color: var(--red-ink); }
</style>
