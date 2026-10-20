<script setup lang="ts">
/** 变更脚本、翻译结果下发前的提示（REQ-044）：来源设备使用近似 Profile（厂商默认、型号规则、手工选择）时请核对。 */
import Icon from '@/components/Icon.vue'
export interface ApproxNote { device: string; profile: string; source: string; rule_id: number | null }
defineProps<{ note: ApproxNote | null | undefined }>()
</script>

<template>
  <div v-if="note" class="notice warn approx-note" data-testid="approx-push-note">
    <Icon name="warn" />
    <div class="grow small">{{ $t('model.pushApprox', { d: note.device, p: note.profile, s: $t(`model.src.${note.source}`) + (note.rule_id ? ` #${note.rule_id}` : '') }) }}</div>
  </div>
</template>

<style scoped>
.approx-note { margin-bottom: 12px; align-items: center; }
</style>
