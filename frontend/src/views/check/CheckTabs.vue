<script setup lang="ts">
/** 配置检查的三个标签：发现 / 规则 / 冗余清理（清理独立成页，标签在两个页面顶部保持一致）。 */
import Icon from '@/components/Icon.vue'

defineProps<{
  active: 'findings' | 'rules' | 'cleanup'
  findings?: number | null
  rules?: string | null
  orphans?: number | null
}>()
</script>

<template>
  <div class="tabs" role="tablist" data-testid="check-tabs">
    <router-link :to="{ name: 'check', hash: '#findings' }" role="tab" :aria-selected="active === 'findings'" data-testid="tab-findings">
      <Icon name="shield" small /><span>{{ $t('check.tabFindings') }}</span><span v-if="findings != null" class="count">{{ findings }}</span>
    </router-link>
    <router-link :to="{ name: 'check', hash: '#rules' }" role="tab" :aria-selected="active === 'rules'" data-testid="tab-rules">
      <Icon name="sliders" small /><span>{{ $t('check.tabRules') }}</span><span v-if="rules" class="count">{{ rules }}</span>
    </router-link>
    <router-link :to="{ name: 'cleanup' }" role="tab" :aria-selected="active === 'cleanup'" data-testid="tab-cleanup">
      <Icon name="broom" small /><span>{{ $t('nav.cleanup') }}</span><span v-if="orphans != null" class="count">{{ orphans }}</span>
    </router-link>
  </div>
</template>

<style scoped>
.tabs { margin-bottom: 10px; }
.tabs a { display: inline-flex; align-items: center; gap: 6px; }
</style>
