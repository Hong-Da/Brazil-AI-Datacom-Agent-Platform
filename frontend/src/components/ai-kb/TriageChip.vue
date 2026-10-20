<script setup lang="ts">
/** 未识别行表格“AI 归因”列的标记：归因（虚线紫色）、已送审（实线）、未通过（红色）、已忽略（灰）；没有建议时显示“—”。 */
import Icon from '@/components/Icon.vue'
import type { TriageMark } from './logic'

defineProps<{ mark: TriageMark | null | undefined }>()
</script>

<template>
  <span v-if="!mark" class="faint small">—</span>
  <span v-else-if="mark.state === 'fail'" class="vchip fail" data-testid="triage-chip" data-state="fail"><Icon name="err" small />{{ $t('kb-ai.ut.fail') }}</span>
  <span v-else class="cls" :class="mark.state" data-testid="triage-chip" :data-state="mark.state">
    {{ $t(`ai-suggest.kb.cause.${mark.cause}`) }}<template v-if="mark.state === 'sent'"> · {{ $t('kb-ai.ut.sent') }}</template><template v-else-if="mark.state === 'dismissed'"> · {{ $t('kb-ai.ut.dismissed') }}</template>
  </span>
</template>

<style scoped>
.cls { display: inline-flex; font-size: 11px; color: var(--violet); border: 1px dashed var(--ai-line); border-radius: 4px; padding: 0 5px; line-height: 17px; white-space: nowrap; }
.cls.sent { border-style: solid; background: var(--ai-soft); }
.cls.dismissed { color: var(--ink-3); border-color: var(--line-strong); }
</style>
