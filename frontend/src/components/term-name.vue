<script setup lang="ts">
/**
 * 节点名（REQ-026）：按当前显示风格写成命令路径，规范编号放在悬停提示里（canon 为 true 时另起一行小字显示）。
 * text 给出时直接用它（调用方已渲染），否则由 id 渲染。
 */
import { computed } from 'vue'
import { useTerms } from '@/stores/terms'

const props = defineProps<{ id: string; text?: string; canon?: boolean; tag?: string }>()
const terms = useTerms()
const shown = computed(() => props.text ?? terms.describe(props.id))
</script>

<template>
  <component :is="tag || 'span'" class="term-name" :title="`${$t('hid.canonical')}: ${id}`" :data-canon="id">
    <span class="term-cmd">{{ shown }}</span>
    <span v-if="canon && shown !== id" class="canon">{{ id }}</span>
  </component>
</template>

<style scoped>
.term-name { min-width: 0; }
.term-name .canon { display: block; }
</style>
