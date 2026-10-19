<script setup lang="ts">
/** 逐字段对比（后端 diff 的 fields）：有差异的字段展开，相同的折叠；统一 / 并排两种视图。 */
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import HlText from './HlText.vue'
import { diffCounts, sbsRows } from './logic'
import { useT } from './ctx'
import type { DiffField } from './types'

const props = defineProps<{ fields: DiffField[]; known: string[]; view?: 'uni' | 'sbs' }>()
const { T } = useT()
const open = ref<Record<string, boolean>>({})
watch(() => props.fields, (fs) => { open.value = Object.fromEntries(fs.map((f) => [f.field, f.changed])) }, { immediate: true })

function label(f: string): string {
  if (f.startsWith('templates.')) return T('field.template', { n: f.slice(10) })
  return ['system', 'prompt', 'examples', 'tools', 'output'].includes(f) ? T(`field.${f}`) : f
}
</script>

<template>
  <div>
    <div v-for="f in fields" :key="f.field" class="fcmp" :class="{ 'is-open': open[f.field] && f.changed }" :data-field="f.field" data-testid="diff-field">
      <button type="button" class="fh" :disabled="!f.changed" @click="open[f.field] = !open[f.field]">
        <Icon name="chevR" small class="chev" /><span>{{ label(f.field) }}</span><code>{{ f.field }}</code>
        <span v-if="!f.changed" class="same">{{ T('diff.same') }}</span>
        <span v-else class="cnt"><span class="a">+{{ diffCounts(f.lines).add }}</span><span class="d">−{{ diffCounts(f.lines).del }}</span></span>
      </button>
      <template v-if="f.changed && open[f.field]">
        <div v-if="view === 'sbs'" class="code pdiff sbs">
          <template v-for="(r, i) in sbsRows(f.lines ?? [])" :key="i">
            <div v-if="r.left" class="l" :class="{ 'd-del': r.left.op === 'del' }"><span class="n">{{ r.left.n }}</span><span class="g">{{ r.left.op === 'del' ? '−' : '' }}</span><span class="t"><HlText :text="r.left.text" :known="known" />{{ r.left.text ? '' : ' ' }}</span></div>
            <div v-else class="l blank"><span class="n" /><span class="g" /><span class="t" /></div>
            <div v-if="r.right" class="l" :class="{ 'd-add': r.right.op === 'add' }"><span class="n">{{ r.right.n }}</span><span class="g">{{ r.right.op === 'add' ? '+' : '' }}</span><span class="t"><HlText :text="r.right.text" :known="known" />{{ r.right.text ? '' : ' ' }}</span></div>
            <div v-else class="l blank"><span class="n" /><span class="g" /><span class="t" /></div>
          </template>
        </div>
        <div v-else class="code pdiff">
          <div v-for="(l, i) in f.lines ?? []" :key="i" class="l" :class="{ 'd-del': l.op === 'del', 'd-add': l.op === 'add' }">
            <span class="n">{{ l.op === 'del' ? l.a : l.b }}</span><span class="g">{{ l.op === 'del' ? '−' : l.op === 'add' ? '+' : '' }}</span><span class="t"><HlText :text="l.text" :known="known" />{{ l.text ? '' : ' ' }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
