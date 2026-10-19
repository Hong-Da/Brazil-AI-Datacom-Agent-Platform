<script setup lang="ts">
/**
 * 视图全屏容器（REQ-043）：包住一个视图区域（工具栏、图例、选中对象面板都放在里面），
 * 全屏时整块带上，内容不重建，缩放、选中、滚动位置保持。
 * 按钮：float 时右上角浮动；否则在区域内的工具栏里放 <FullscreenButton />。
 * 全屏时容器是纵向 flex，要撑满的子元素在页面样式里用 `.fsv.is-fs .xxx { flex: 1; min-height: 0 }`。
 */
import { onBeforeUnmount, provide, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'
import FullscreenButton from './FullscreenButton.vue'
import { createFsPane, FS_KEY, type FsMode } from './fullscreen'

const props = withDefaults(defineProps<{ title?: string; float?: boolean; shortcut?: boolean }>(), { title: '', float: false, shortcut: true })
const emit = defineEmits<{ change: [mode: FsMode] }>()
const { t } = useI18n()

const root = ref<HTMLElement | null>(null)
const hint = ref(false)
let hintTimer: ReturnType<typeof setTimeout> | undefined

const pane = createFsPane(() => root.value, {
  shortcut: () => props.shortcut,
  onChange(m) {
    clearTimeout(hintTimer)
    hint.value = !!m
    if (m) hintTimer = setTimeout(() => { hint.value = false }, 2600)
    emit('change', m)
  },
})
provide(FS_KEY, pane)
defineExpose({ enter: pane.enter, exit: pane.exit, toggle: pane.toggle, mode: pane.mode })
onBeforeUnmount(() => { clearTimeout(hintTimer); pane.dispose() })
</script>

<template>
  <div ref="root" class="fsv" :class="{ 'is-fs': !!pane.mode.value, 'is-max': pane.mode.value === 'max', 'fsv-float': float }" :data-fs="pane.mode.value || 'off'">
    <div v-if="pane.mode.value && title" class="fs-title"><b>{{ title }}</b></div>
    <FullscreenButton v-if="float" class="fs-float" />
    <slot :mode="pane.mode.value" />
    <div class="fs-hint" :class="{ on: hint }" role="status" data-testid="fs-hint">
      <template v-if="pane.mode.value"><Icon :name="pane.mode.value === 'max' ? 'expand' : 'monitor'" small /><span>{{ pane.mode.value === 'max' ? t('fullscreen.hintMax') : t('fullscreen.hintNative') }}</span></template>
    </div>
  </div>
</template>

<style>
/* 全局样式：容器的子元素由各页面放进来，用 :where 降低优先级，页面样式可以覆盖。 */
.fsv { position: relative; min-width: 0; }
:where(.fsv.is-fs) { background: var(--bg); padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 8px; width: 100vw; height: 100vh; overflow: hidden; box-sizing: border-box; margin: 0; max-width: none; }
/* 盒子尺寸与外边距必须覆盖页面样式（例如 .hw 的 margin-top 会把固定定位的区域往下推）。 */
.fsv.is-fs { margin: 0 !important; width: 100vw !important; height: 100vh !important; max-width: none !important; max-height: none !important; border-radius: 0 !important; }
.fsv.is-max { position: fixed; inset: 0; z-index: 70; }
.fsv:fullscreen::backdrop { background: var(--bg); }
.fsv.is-fs > * { flex-shrink: 0; }
.fs-title { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink-2); padding: 0 2px; padding-right: 150px; }
.fs-title b { color: var(--ink); font-size: 14px; }
.fs-float { position: absolute; top: 8px; right: 8px; z-index: 6; }
.fsv.is-fs > .fs-float { top: 8px; right: 12px; }
.fs-btn { white-space: nowrap; }
/* 放在页签条（.tabs）里时，恢复按钮外观（.tabs button 会去掉边框和背景）。 */
.tabs > .fs-btn.btn { border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); padding: 0 9px; font-size: 12px; }
.tabs > .fs-btn.btn-xs { padding: 0 7px; font-size: 11.5px; }
.fs-btn kbd { font: 600 10.5px var(--font-ui); border: 1px solid var(--line-strong); border-bottom-width: 2px; border-radius: 3px; padding: 0 4px; color: var(--ink-3); background: var(--surface-2); line-height: 15px; }
.fs-btn[aria-pressed="true"] { border-color: var(--blue); color: var(--blue-ink); background: var(--blue-soft); }
.fs-hint { position: absolute; top: 14px; left: 50%; transform: translateX(-50%); z-index: 20; display: flex; align-items: center; gap: 8px; padding: 7px 12px; border-radius: 999px; background: var(--ink); color: var(--surface); font-size: 12.5px; box-shadow: var(--shadow-pop); pointer-events: none; opacity: 0; transition: opacity .25s; white-space: nowrap; }
.fs-hint.on { opacity: .94; }
.fs-hint .ico { width: 14px; height: 14px; }
.fsv.is-fs .toast { position: absolute; }
body.has-fs-max { overflow: hidden; }
@media (prefers-reduced-motion: reduce) { .fs-hint { transition: none; } }
</style>
