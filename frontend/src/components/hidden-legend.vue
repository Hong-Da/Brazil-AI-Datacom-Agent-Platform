<script setup lang="ts">
/** 隐藏配置的图例（REQ-028）：默认值（灰色虚线）与派生值（紫色点线），全站统一。 */
withDefaults(defineProps<{ derived?: boolean }>(), { derived: true })
</script>

<template>
  <span class="hid-legend" data-testid="hidden-legend">
    <span class="hk" :title="$t('hid.defaultTip')"><svg viewBox="0 0 22 10"><rect class="hk-def" x="1" y="1" width="20" height="8" rx="2" /></svg><span class="tag default">{{ $t('hid.default') }}</span></span>
    <span v-if="derived !== false" class="hk" :title="$t('hid.derivedTip')"><svg viewBox="0 0 22 10"><rect class="hk-der" x="1" y="1" width="20" height="8" rx="2" /></svg><span class="tag derived">{{ $t('hid.derived') }}</span></span>
  </span>
</template>
