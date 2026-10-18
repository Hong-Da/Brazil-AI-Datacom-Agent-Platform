<script setup lang="ts">
/** 原始配置：带行号，标出原文行与未识别行，高亮选中节点的行；点行反选节点。 */
import { ref } from 'vue'

const props = defineProps<{
  lines: string[]
  rawLines: Set<number>
  unknownLines: Set<number>
  /** 进入了图的行（其余是分隔符、注释、空行） */
  owned: Map<number, string>
  hl: Set<number>
  selLine: number | null
}>()
const emit = defineEmits<{ (e: 'pick', line: number): void }>()
const box = ref<HTMLDivElement>()

function cls(n: number): string[] {
  const c = ['l', 'clickable']
  if (props.unknownLines.has(n)) c.push('unknown')
  else if (props.rawLines.has(n)) c.push('raw')
  else if (!props.owned.has(n)) c.push('c-cmt')
  if (props.hl.has(n) || props.selLine === n) c.push('is-hl')
  return c
}

/** 把行滚到可视区上方三分之一处（已可见时不动，force 时总是滚动）。 */
function scrollTo(n: number, force = false): void {
  const el = box.value?.querySelector<HTMLElement>(`[data-ln="${n}"]`)
  if (!el || !box.value) return
  const top = el.offsetTop
  const view = box.value
  if (!force && top >= view.scrollTop && top + el.offsetHeight <= view.scrollTop + view.clientHeight) return
  view.scrollTop = Math.max(0, top - view.clientHeight / 3)
}

function onClick(ev: MouseEvent): void {
  const el = (ev.target as HTMLElement).closest<HTMLElement>('[data-ln]')
  if (el) emit('pick', Number(el.dataset.ln))
}

defineExpose({ scrollTo })
</script>

<template>
  <div ref="box" class="code" data-testid="config-text" @click="onClick">
    <div v-for="(t, i) in lines" :key="i" :class="cls(i + 1)" :data-ln="i + 1">
      <span class="n">{{ i + 1 }}</span>
      <span class="g">
        <span v-if="unknownLines.has(i + 1)" class="gmark unk">?</span>
        <span v-else-if="rawLines.has(i + 1)" class="gmark raw">R</span>
      </span>
      <span class="t">{{ t }}</span>
    </div>
  </div>
</template>

<style scoped>
.code { flex: 1; min-height: 0; position: relative; }
</style>
