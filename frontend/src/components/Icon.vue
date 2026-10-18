<script setup lang="ts">
import { computed } from 'vue'
import { ICONS } from './icons'

const props = defineProps<{ name: string; small?: boolean }>()
const path = computed(() => ICONS[props.name] ?? ICONS.info)
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <svg :class="['ico', { 'ico-sm': small }]" viewBox="0 0 24 24" aria-hidden="true" v-html="path" />
</template>
