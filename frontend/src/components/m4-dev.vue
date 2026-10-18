<script setup lang="ts">
/** 设备标记：厂商色块（H 华为、C Cisco）+ 设备名（M4 预览的 .dev）。vendor 可以是厂商、平台族或 Profile。 */
import { computed } from 'vue'
import { vendorMark } from '@/views/m4/common'

const props = defineProps<{ name: string; vendor?: string | null }>()
const mark = computed(() => vendorMark(props.vendor))
</script>

<template>
  <span class="dev"><i v-if="mark" :class="mark">{{ mark === 'hw' ? 'H' : 'C' }}</i><i v-else class="unk">?</i>{{ name }}</span>
</template>

<style scoped>
.dev i.unk { background: var(--ink-3); }
</style>
