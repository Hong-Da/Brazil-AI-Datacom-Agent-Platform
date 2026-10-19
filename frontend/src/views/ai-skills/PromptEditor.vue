<script setup lang="ts">
/** 提示词编辑器：透明 textarea 叠在高亮层上，{变量} 着色、未登记的变量标红；下方显示行数、字符数与用到的变量。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import HlText from './HlText.vue'
import { br, varsIn } from './logic'
import { useT } from './ctx'

const props = defineProps<{ modelValue: string; known: string[]; hot?: string; label: string; testid?: string }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()
const { T } = useT()
const ta = ref<HTMLTextAreaElement | null>(null)
const hl = ref<HTMLElement | null>(null)
const used = computed(() => varsIn(props.modelValue))
const unk = computed(() => used.value.filter((n) => !props.known.includes(n)))

function fit(): void {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight + 2}px`
}
function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
  void nextTick(fit)
}
function onScroll(): void {
  if (hl.value && ta.value) hl.value.scrollTop = ta.value.scrollTop
}
watch(() => props.modelValue, () => void nextTick(fit))
onMounted(() => requestAnimationFrame(fit))
</script>

<template>
  <div class="pe" :data-testid="testid">
    <pre ref="hl" class="pe-hl" aria-hidden="true"><HlText :text="modelValue" :known="known" :hot="hot" />{{ '\n' }}</pre>
    <textarea ref="ta" :value="modelValue" spellcheck="false" :aria-label="label" @input="onInput" @scroll="onScroll" />
  </div>
  <div class="pe-foot">
    <span>{{ T('def.linesChars', { l: modelValue.split('\n').length, c: modelValue.length }) }}</span>
    <span class="used">{{ T('def.varsUsed') }}<template v-if="used.length"><template v-for="n in used" :key="n"><span class="pv" :class="{ unk: !known.includes(n) }">{{ br(n) }}</span>{{ ' ' }}</template></template><template v-else>{{ T('def.none') }}</template></span>
    <span v-if="unk.length" class="unkmsg" data-testid="unk-var"><Icon name="warn" small />{{ T('def.unknownVar', { v: unk.map(br).join(' ') }) }}</span>
  </div>
</template>
