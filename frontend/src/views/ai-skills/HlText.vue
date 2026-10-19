<script setup lang="ts">
/** 带 {变量} 高亮的文本（未登记的变量标红，hot 为当前点选的变量）。 */
import { computed } from 'vue'
import { hlParts } from './logic'

const props = defineProps<{ text: string; known: string[]; hot?: string }>()
const parts = computed(() => hlParts(props.text ?? '', props.known))
</script>

<template><template v-for="(p, i) in parts" :key="i"><span v-if="p.t === 'var'" class="pv" :class="{ unk: !p.known, 'is-hot': hot && p.name === hot }" :data-var="p.name">{{ p.s }}</span><template v-else>{{ p.s }}</template></template></template>
