<script setup lang="ts">
/**
 * M3 页面共用的配置文本面板：行号 + 标记列 + 文本。每行可带样式类、分段（变量、生成值）与“默认”标签。
 * 行的 data-i 是行在数组中的下标，翻译页按它画两侧之间的连接带。
 */
import { ref } from 'vue'
import type { CodeLine } from '@/views/m3/code'

defineProps<{ lines: CodeLine[]; side?: string; testid?: string }>()
const emit = defineEmits<{ (e: 'pick', i: number): void; (e: 'var', v: string): void; (e: 'scroll'): void }>()
const box = ref<HTMLDivElement>()

/** 把第 i 行滚到可见区域（已可见时不动）。 */
function scrollToIndex(i: number): void {
  const el = box.value?.querySelector<HTMLElement>(`.l[data-i="${i}"]`)
  const pane = box.value
  if (!el || !pane) return
  const top = el.offsetTop
  if (top < pane.scrollTop + 20 || top > pane.scrollTop + pane.clientHeight - 60) pane.scrollTop = Math.max(0, top - pane.clientHeight / 3)
}

function onClick(ev: MouseEvent, i: number): void {
  const v = (ev.target as HTMLElement).closest<HTMLElement>('[data-v]')
  if (v?.dataset.v) emit('var', v.dataset.v)
  else emit('pick', i)
}

defineExpose({ box, scrollToIndex })
</script>

<template>
  <div ref="box" class="code" :data-testid="testid" @scroll="emit('scroll')">
    <div
      v-for="(l, i) in lines" :key="i"
      class="l" :class="[l.cls, { 'ghost-d': l.ghost }]" :data-i="i" :data-side="side" :data-ln="l.no ?? undefined"
      @click="onClick($event, i)"
    >
      <span class="n">{{ l.no ?? '·' }}</span><span class="g" /><span class="t"><template v-if="l.ghost">{{ l.text.match(/^\s*/)?.[0] }}<span class="gx">{{ l.text.trimStart() }}</span></template><template v-else-if="l.parts"><template v-for="(p, k) in l.parts" :key="k"><span v-if="p.v" :class="p.cls || 'vx'" :data-v="p.v" :title="p.title">{{ p.s }}</span><span v-else-if="p.cls" :class="p.cls">{{ p.s }}</span><template v-else>{{ p.s }}</template></template></template><template v-else>{{ l.text || ' ' }}</template><span v-if="l.tag" class="gtag">{{ l.tag }}</span></span>
    </div>
  </div>
</template>

<style scoped>
.code { position: relative; }
</style>
