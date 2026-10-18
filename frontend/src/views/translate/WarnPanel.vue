<script setup lang="ts">
/** 告警面板：按类别分组的告警；选中一条时显示说明、两侧行号、原文与“标记为已处理”。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import TermName from '@/components/term-name.vue'
import { groupCounts, warnText } from './logic'
import { GROUPS, type Group, type Warn } from './types'

const props = defineProps<{
  warns: Warn[]
  filter: Group | ''
  sel: string | null
  handled: Record<string, boolean>
  dstOf: (w: Warn) => number[]
  srcText: (lines: number[]) => string
}>()
const emit = defineEmits<{
  (e: 'filter', g: Group | ''): void
  (e: 'select', id: string | null): void
  (e: 'go', side: 's' | 'd', idx: number): void
  (e: 'handle', id: string, v: boolean): void
  (e: 'copy', text: string): void
}>()
const { t, locale } = useI18n()
const counts = computed(() => groupCounts(props.warns))
const shown = computed(() => GROUPS.filter((g) => !props.filter || props.filter === g).map((g) => ({ g, ws: props.warns.filter((w) => w.group === g) })).filter((x) => x.ws.length))
const done = computed(() => props.warns.filter((w) => props.handled[w.id]).length)
const sevName = (l: string) => t(`translate.sev.${l}`)
</script>

<template>
  <section class="panel warns" aria-label="Warnings" data-testid="tr-warns">
    <div class="tabs" role="tablist">
      <span class="tabs-k">{{ $t('translate.warns') }}</span>
      <button type="button" role="tab" :aria-selected="filter === ''" @click="emit('filter', '')">{{ $t('translate.all') }} <span class="count">{{ warns.length }}</span></button>
      <button v-for="g in GROUPS" :key="g" type="button" role="tab" :aria-selected="filter === g" :title="$t(`translate.group.${g}`)" :aria-label="`${$t(`translate.group.${g}`)} ${counts[g]}`" :data-testid="`tr-tab-${g}`" @click="emit('filter', g)">
        <span class="wk" :class="g">{{ counts[g] }}</span>
      </button>
    </div>
    <div class="wlist">
      <div v-if="!warns.length" class="empty small">{{ $t('translate.noWarns') }}</div>
      <template v-for="grp in shown" :key="grp.g">
        <div class="wgrp-h"><span class="wk" :class="grp.g">{{ $t(`translate.group.${grp.g}`) }}</span><span class="cnt">{{ grp.ws.length }}</span></div>
        <div
          v-for="w in grp.ws" :key="w.id" class="wi" :class="[`k-${w.group}`, { 'is-sel': sel === w.id, done: handled[w.id] }]"
          tabindex="0" :data-w="w.id" data-testid="tr-warn" @click="emit('select', sel === w.id ? null : w.id)" @keydown.enter.prevent="emit('select', sel === w.id ? null : w.id)"
        >
          <div class="wh">
            <span class="wid">{{ w.id }}</span>
            <span class="sev" :class="w.level"><span class="sevdot" :class="w.level" />{{ sevName(w.level) }}</span>
            <span v-if="handled[w.id]" class="tag pass" style="height: 18px"><Icon name="check" small />{{ $t('translate.handled') }}</span>
            <span class="wo"><TermName v-if="w.item.node && !w.item.node.startsWith('raw[') && !w.item.node.includes('ext[')" :id="w.item.node" /><span v-else class="mono">{{ w.item.kind }}</span></span>
          </div>
          <div class="wt">{{ warnText(w, String(locale)) }}</div>
          <template v-if="sel === w.id">
            <div class="wlines" @click.stop>
              <span>{{ $t('translate.src') }}</span>
              <template v-if="w.item.lines.length"><button v-for="l in w.item.lines.slice(0, 12)" :key="l" type="button" class="lnchip" @click="emit('go', 's', l - 1)">L{{ l }}</button><span v-if="w.item.lines.length > 12" class="faint">…</span></template>
              <span v-else class="faint">{{ $t('translate.noSrcLine') }}</span>
              <span style="margin-left: 6px">{{ $t('translate.out') }}</span>
              <template v-if="dstOf(w).length"><button v-for="i in dstOf(w).slice(0, 12)" :key="i" type="button" class="lnchip" @click="emit('go', 'd', i)">L{{ i + 1 }}</button></template>
              <span v-else class="faint">{{ $t('translate.notInOut') }}</span>
            </div>
            <pre v-if="w.group === 'raw' && w.item.lines.length" class="block">{{ srcText(w.item.lines) }}</pre>
            <div class="wact" @click.stop>
              <label class="check"><input type="checkbox" :checked="!!handled[w.id]" :data-testid="`tr-handle-${w.id}`" @change="emit('handle', w.id, ($event.target as HTMLInputElement).checked)"><span>{{ $t('translate.markHandled') }}</span></label>
              <button v-if="w.group === 'raw' && w.item.lines.length" class="btn btn-xs" type="button" @click="emit('copy', srcText(w.item.lines))"><Icon name="copy" small />{{ $t('translate.copyLines') }}</button>
            </div>
          </template>
        </div>
      </template>
    </div>
    <div class="wfoot"><span>{{ $t('translate.handledN', { n: done, m: warns.length }) }}</span><div class="progress"><i :style="{ width: warns.length ? `${(done / warns.length) * 100}%` : '0' }" /></div></div>
  </section>
</template>

<style scoped>
.warns { display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.warns .tabs { margin: 0; padding: 0 8px; align-items: center; flex-wrap: wrap; }
.warns .tabs button { font-size: 12.5px; white-space: nowrap; }
.warns .tabs .tabs-k { padding-right: 6px; font-size: 12px; font-weight: 600; color: var(--ink-2); margin: 0 6px 0 4px; }
.wlist { flex: 1; overflow: auto; min-height: 0; }
.wgrp-h { display: flex; align-items: center; gap: 8px; padding: 7px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 1; font-size: 12px; color: var(--ink-2); }
.wgrp-h .cnt { margin-left: auto; font-size: 11.5px; color: var(--ink-3); }
.wi { padding: 10px 12px 10px 14px; border-bottom: 1px solid var(--line); cursor: pointer; position: relative; }
.wi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bar, transparent); }
.wi.k-default { --bar: #D9962B; }
.wi.k-unsup { --bar: var(--red); }
.wi.k-raw { --bar: var(--raw); }
.wi.k-infer { --bar: var(--blue); }
.wi:hover { background: var(--surface-2); }
.wi.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.wi.done .wt { color: var(--ink-3); }
.wh { display: flex; align-items: center; gap: 8px; min-width: 0; }
.wid { font: 600 11px var(--font-mono); color: var(--ink-3); }
.wo { font-size: 11.5px; color: var(--ink-3); margin-left: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 55%; }
.wt { margin-top: 5px; font-size: 12.5px; line-height: 1.45; overflow-wrap: anywhere; }
.wlines { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; font-size: 11.5px; color: var(--ink-3); }
.lnchip { font: 11.5px var(--font-mono); border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink-2); border-radius: 4px; padding: 0 5px; cursor: pointer; }
.lnchip:hover { border-color: var(--blue); color: var(--blue-ink); }
.wact { margin-top: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
pre.block { margin-top: 8px; font-size: 11.5px; max-height: 160px; overflow: auto; }
.wfoot { padding: 8px 12px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-2); display: flex; gap: 8px; align-items: center; }
.wfoot .progress { flex: 1; }
</style>
