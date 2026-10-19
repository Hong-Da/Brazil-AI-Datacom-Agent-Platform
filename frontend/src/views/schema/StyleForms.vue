<script setup lang="ts">
/** Schema 节点卡片：各显示风格的写法（当前风格在前并高亮）。 */
import { computed } from 'vue'
import { useTerms } from '@/stores/terms'
import { styleRows } from './styles'

const props = defineProps<{ id: string; type: string }>()
const terms = useTerms()
const rows = computed(() => styleRows(terms, props.id, props.type, terms.style, terms.styles))
</script>

<template>
  <div v-if="rows.length" class="sf" data-testid="style-forms">
    <div v-for="r in rows" :key="r.style" :class="['sf-row', { cur: r.current }]" :data-style="r.style">
      <span class="sf-k">{{ $t(`style.${r.style}`) }}</span>
      <span class="sf-v">
        <span class="mono">{{ r.form }}</span>
        <span v-if="r.name" class="small muted">{{ r.name }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.sf { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; }
.sf-row { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; align-items: baseline; padding: 5px 8px; border-radius: 5px; border: 1px solid var(--line); background: var(--surface-2); }
.sf-row.cur { border-color: var(--blue-line); background: var(--blue-soft); }
.sf-k { font-size: 11.5px; color: var(--ink-3); }
.sf-row.cur .sf-k { color: var(--blue-ink); font-weight: 600; }
.sf-v { display: flex; flex-direction: column; min-width: 0; overflow-wrap: anywhere; }
.sf-v .mono { font-size: 12.5px; }
</style>
