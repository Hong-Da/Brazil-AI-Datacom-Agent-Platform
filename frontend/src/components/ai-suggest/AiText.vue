<script setup lang="ts">
/** AI 文字段落（M8-2）：AI 写的文字用紫色虚线半透明底；代码填入的对象名、数字用实线小块（对象名可点击跳转）。
 *  segments 来自后端 check.segments；没有时显示 text。adopted 时整块变实线，左侧保留紫色细条。 */
import Icon from '@/components/Icon.vue'
import type { RefInfo, Segment } from './logic'

const props = defineProps<{ segments?: Segment[] | null; text?: string; refs?: RefInfo[]; adopted?: boolean; inline?: boolean }>()
const emit = defineEmits<{ jump: [ref: RefInfo] }>()

function refOf(s: Segment): RefInfo {
  const hit = (props.refs ?? []).find((r) => r.id === s.id)
  return hit ?? { id: s.id, label: s.v, found: !!s.found }
}
</script>

<template>
  <div class="ai-block" :class="{ 'is-ok': adopted, 'is-inline': inline }" data-testid="ai-text">
    <span v-if="!inline" class="ai-by"><Icon name="spark" small />{{ adopted ? $t('ai-suggest.aiAdopted') : $t('ai-suggest.aiBy') }}</span>
    <div>
      <template v-if="segments && segments.length">
        <template v-for="(s, i) in segments" :key="i">
          <span v-if="s.t === 'text'">{{ s.v }}</span>
          <button v-else-if="s.t === 'ref'" type="button" class="cv ref" :class="{ bad: !s.found }" data-testid="ai-text-ref" @click="emit('jump', refOf(s))">{{ s.v }}</button>
          <span v-else class="cv" :class="{ bad: !s.found }" data-testid="ai-text-num">{{ s.v }}</span>
        </template>
      </template>
      <span v-else>{{ text }}</span>
    </div>
  </div>
</template>

<style scoped>
.ai-block.is-inline { padding: 6px 9px; }
button.cv { cursor: pointer; font: inherit; }
button.cv.ref { font: 600 11.5px var(--font-mono); }
.cv.bad { text-decoration: line-through; color: var(--red-ink); border-color: var(--red-line); background: transparent; border-style: dashed; }
</style>
