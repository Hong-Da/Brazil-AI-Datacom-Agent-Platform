<script setup lang="ts">
/** 厂商标记 .vendor：色块（HW / CS / NK，letter 时单字母）+ 后面的文字（默认插槽）。of 可以是厂商、平台族或 Profile。 */
import { computed } from 'vue'
import { vendorMark } from '@/vendor'

const props = defineProps<{ of?: string | null; letter?: boolean }>()
const mark = computed(() => vendorMark(props.of))
</script>

<template>
  <span class="vendor" :data-vendor="mark.key || undefined"><i :class="mark.cls" :title="mark.name || undefined">{{ letter ? mark.letter : mark.abbr }}</i><slot /></span>
</template>
