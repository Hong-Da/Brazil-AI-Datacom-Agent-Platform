<script setup lang="ts">
/** 设备图标（REQ-042）：按个人偏好的图标风格画角色或平台外形，叠加厂商标识与状态角标；ghost 为待采纳的 AI 建议（紫色虚线半透明）。
 *  SVG 由 lmi.ts 拼出（名称已转义），只放自己生成的字符串。 */
import { computed } from 'vue'
import { usePrefs } from '@/stores/prefs'
import { svg, type Badge, type VendorCode } from './lmi'
import './devicon.css'

const props = withDefaults(defineProps<{ kind: string; size?: number; vendor?: VendorCode | '' | null; badges?: Badge[]; ghost?: boolean; title?: string; set?: string }>(), {
  size: 24, vendor: null, badges: () => [], ghost: false, title: '', set: '',
})
const prefs = usePrefs()
const html = computed(() => svg(props.set || prefs.iconSet, props.kind, { size: props.size, vendor: props.vendor, badges: props.badges, ghost: props.ghost, title: props.title || undefined }))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <span class="devicon" :class="{ ghost }" data-testid="devicon" :data-kind="kind" :data-set="set || prefs.iconSet" :style="{ width: `${size}px`, height: `${size}px` }" v-html="html" />
</template>
