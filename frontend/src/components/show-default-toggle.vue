<script setup lang="ts">
/** “显示默认配置”开关（REQ-028）：各视图共用的样式与文案；选择由调用方用 rememberedFlag 记住。 */
const model = defineModel<boolean>({ required: true })
withDefaults(defineProps<{ count?: number | null; testid?: string }>(), { count: null, testid: 'toggle-default' })
</script>

<template>
  <label class="check small" :title="$t('hid.defaultTip')">
    <input v-model="model" type="checkbox" :data-testid="testid">
    <span>{{ $t('hid.showDefault') }}<span v-if="count !== null" class="faint cnt">{{ count }}</span></span>
  </label>
</template>

<style scoped>
/* 数字与文字之间的间隔用外边距：父元素是 flex 时开头的空格会被吞掉（REQ-055-29） */
.cnt { margin-left: 4px; }
</style>
