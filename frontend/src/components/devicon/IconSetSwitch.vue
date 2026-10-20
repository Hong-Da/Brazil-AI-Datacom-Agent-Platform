<script setup lang="ts">
/** 设备图标风格切换（REQ-042，个人偏好）：A 圆柱 / B 几何徽章（默认）/ C 线框。 */
import { usePrefs } from '@/stores/prefs'
import { ICON_SET_IDS } from './sets'
import { svg } from './lmi'
import './devicon.css'

withDefaults(defineProps<{ small?: boolean }>(), { small: false })
const prefs = usePrefs()
const sample = (s: string) => svg(s, 'core', { size: 16 })
</script>

<template>
  <div class="seg iconseg" role="group" :aria-label="$t('devicon.iconSet')" :title="$t('devicon.iconSetTip')" data-testid="icon-set-switch">
    <button v-for="s in ICON_SET_IDS" :key="s" type="button" :class="{ 'btn-xs': small }" :aria-pressed="prefs.iconSet === s" :data-testid="`icon-set-${s}`" @click="prefs.iconSet = s">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <span style="display: contents" v-html="sample(s)" /><span>{{ $t(`devicon.set.${s}`) }}</span>
    </button>
  </div>
</template>
