<script setup lang="ts">
/**
 * 小徽标集合：kind = vs（校验状态）/ ver（版本）/ stack（堆叠条）/ legend（图例）/ rates（评价）/ rate（通过率条）/ src（版本来源）。
 * 颜色只用 req033.css 里的变量；状态总是配文字。
 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { pct, rateTone, ST_ORDER, stackSegs, stCls } from './logic'
import { useT } from './ctx'
import type { Counts } from './types'

const props = defineProps<{
  kind: 'vs' | 'ver' | 'stack' | 'legend' | 'rates' | 'rate' | 'src'
  s?: string
  v?: string | null
  cur?: boolean
  counts?: Partial<Counts>
  thin?: boolean
  r?: number | null
}>()
const { T, stLabel } = useT()
const segs = computed(() => stackSegs(props.counts ?? {}))
const SRC_ICON: Record<string, string> = { builtin: 'lock', edit: 'pencil', example: 'plus', evolution: 'dna' }
</script>

<template>
  <span v-if="kind === 'vs'" class="vs" :class="stCls(s)" :data-status="s">{{ stLabel(s ?? '') }}</span>
  <span v-else-if="kind === 'ver' && (!v || v === 'builtin')" class="ver builtin" :class="{ cur }" data-testid="ver-tag" data-ver="builtin"><Icon name="lock" small />{{ T('ver.builtin') }}</span>
  <span v-else-if="kind === 'ver' && (v === 'candidate' || v === 'draft')" class="ver mod" data-testid="ver-tag" :data-ver="v">{{ T(`ver.${v}`) }}</span>
  <span v-else-if="kind === 'ver'" class="ver mod" :class="{ cur }" data-testid="ver-tag" :data-ver="v"><b>v{{ v }}</b>{{ T('ver.modified') }}</span>
  <div v-else-if="kind === 'stack'" class="stackbar vsbar" :class="{ thin }">
    <i v-for="g in segs" :key="g.k" :class="`sw-${g.cls}`" :style="{ width: `${g.w.toFixed(2)}%` }" :title="`${stLabel(g.k)} ${g.n}`" />
  </div>
  <div v-else-if="kind === 'legend'" class="legend vs-legend">
    <span v-for="k in ST_ORDER" :key="k"><i :class="`sw-${stCls(k)}`" />{{ stLabel(k) }}</span>
  </div>
  <span v-else-if="kind === 'rates'" class="rates">
    <span class="r-up" :class="{ zero: !counts?.up }" :title="T('rate.up')"><Icon name="thumbUp" small />{{ counts?.up ?? 0 }}</span>
    <span class="r-down" :class="{ zero: !counts?.down }" :title="T('rate.down')"><Icon name="thumbDown" small />{{ counts?.down ?? 0 }}</span>
    <span class="r-corr" :class="{ zero: !counts?.corrections }" :title="T('rate.corr')"><Icon name="pencil" small />{{ counts?.corrections ?? 0 }}</span>
  </span>
  <div v-else-if="kind === 'rate'" class="meter rmeter">
    <div class="bar"><i :class="rateTone(r)" :style="{ width: `${((r ?? 0) * 100).toFixed(1)}%` }" /></div><span class="val">{{ pct(r) }}</span>
  </div>
  <span v-else-if="kind === 'src'" class="src" :class="`s-${s}`"><Icon :name="SRC_ICON[s ?? 'edit'] ?? 'pencil'" small />{{ T(`src.${s}`) }}</span>
</template>
