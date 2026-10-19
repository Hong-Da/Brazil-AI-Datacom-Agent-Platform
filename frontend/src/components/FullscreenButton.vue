<script setup lang="ts">
/** 全屏按钮（REQ-043）：放在 <FullscreenPane> 里面的任意位置，控制所在的全屏区域。 */
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'
import { FS_KEY } from './fullscreen'

withDefaults(defineProps<{ size?: 'sm' | 'xs'; iconOnly?: boolean }>(), { size: 'sm', iconOnly: false })
const { t } = useI18n()
const pane = inject(FS_KEY, null)
</script>

<template>
  <button
    v-if="pane"
    type="button"
    class="btn fs-btn"
    :class="size === 'xs' ? 'btn-xs' : 'btn-sm'"
    :aria-pressed="pane.mode.value ? 'true' : 'false'"
    :aria-label="pane.mode.value ? t('fullscreen.exit') : t('fullscreen.enter')"
    :title="pane.mode.value ? t('fullscreen.exitTip') : t('fullscreen.enterTip')"
    data-testid="fs-btn"
    @click="pane.toggle()"
  >
    <Icon :name="pane.mode.value ? 'collapse' : 'expand'" small />
    <span v-if="!iconOnly">{{ pane.mode.value ? t('fullscreen.exit') : t('fullscreen.enter') }}</span>
    <kbd>{{ pane.mode.value ? 'Esc' : 'F' }}</kbd>
  </button>
</template>
