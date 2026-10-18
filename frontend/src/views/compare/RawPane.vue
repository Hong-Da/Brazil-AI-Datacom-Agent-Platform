<script setup lang="ts">
/** 一侧的原文：带行号，高亮选中差异的相关行；没有原文时说明原因。 */
import { computed, nextTick, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'

const props = defineProps<{
  k: 'A' | 'B'
  label: string
  fname: string
  text: string | null
  loading: boolean
  /** 没有原文时的说明 */
  missing: string
  hl: number[]
  cls: string
  ghost: string
  unknown: number[]
}>()
const box = ref<HTMLDivElement>()
const lines = computed(() => (props.text ?? '').replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n'))
const hlSet = computed(() => new Set(props.hl))
const unkSet = computed(() => new Set(props.unknown))

function scrollTo(n: number, flash = false): void {
  const el = box.value?.querySelector<HTMLElement>(`[data-ln="${n}"]`)
  if (!el || !box.value) return
  box.value.scrollTop = Math.max(0, el.offsetTop - 60)
  if (flash) el.animate?.([{ outline: '2px solid var(--sel-ring)' }, { outline: '2px solid transparent' }], { duration: 900 })
}

watch(() => [props.hl, props.text], async () => {
  await nextTick()
  if (props.hl.length) scrollTo(Math.min(...props.hl))
  else if (box.value) box.value.scrollTop = 0
})

defineExpose({ scrollTo })
</script>

<template>
  <div class="rawcol" :data-testid="'raw-' + k">
    <div class="tbar">
      <span class="badge">{{ k }}</span><b class="trunc" :title="label">{{ label }}</b>
      <span class="fn" :title="fname">{{ fname }}</span>
      <span v-if="text !== null" class="ml-auto faint">{{ $t('compare.linesN', { n: lines.length }) }}</span>
    </div>
    <div v-if="ghost" class="ghostnote"><Icon name="info" small /><span>{{ ghost }}</span></div>
    <div v-if="loading" class="empty small">{{ $t('compare.raw.loading') }}</div>
    <div v-else-if="text === null" class="empty small missing"><Icon name="info" small /><span>{{ missing }}</span></div>
    <div v-else ref="box" class="code">
      <div
        v-for="(t, i) in lines" :key="i"
        class="l" :class="[hlSet.has(i + 1) ? cls : '', { unknown: unkSet.has(i + 1), 'c-cmt': /^\s*[!#]/.test(t) }]"
        :data-ln="i + 1"
      >
        <span class="n">{{ i + 1 }}</span><span class="g" /><span class="t">{{ t || ' ' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rawcol { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.tbar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--line); font-size: 12px; white-space: nowrap; overflow: hidden; }
.tbar .badge { width: 18px; height: 18px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); border: 1.5px solid var(--line-strong); flex: none; }
.tbar .fn { font: 11.5px var(--font-mono); color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; }
.code { flex: 1; min-height: 0; position: relative; }
.ghostnote { padding: 6px 12px; font-size: 12px; color: var(--ink-2); background: var(--surface-2); border-bottom: 1px dashed var(--line-strong); display: flex; gap: 6px; align-items: center; }
.missing { display: flex; gap: 6px; align-items: flex-start; text-align: left; color: var(--ink-2); }
</style>
