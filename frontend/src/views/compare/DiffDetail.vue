<script setup lang="ts">
/** 差异详情：两侧有效值与来源、判定依据（由结果字段推出）、关联引用、原文行跳转、在配置图中打开。 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useTerms } from '@/stores/terms'
import { describe, explain, sideOf, type Row } from './logic'

const props = defineProps<{
  row: Row | null
  rows: Row[]
  aLabel: string
  bLabel: string
  aProfile: string
  bProfile: string
  /** 能在配置图中打开时给出设备 id（该侧是设备的最新版本） */
  aGraph: number | null
  bGraph: number | null
}>()
const emit = defineEmits<{ (e: 'select', id: string): void; (e: 'jump', side: 'a' | 'b', line: number): void }>()

const terms = useTerms()
const what = computed(() => (props.row ? describe(props.row.node, props.row.dflt ? 'attr' : props.row.diff?.node_kind ?? 'attr', terms.describeParts) : null))
const why = computed(() => (props.row ? explain(props.row) : null))
const sides = computed(() => {
  const r = props.row
  if (!r) return []
  return (['a', 'b'] as const).map((s) => ({
    s,
    k: s.toUpperCase(),
    label: s === 'a' ? props.aLabel : props.bLabel,
    profile: s === 'a' ? props.aProfile : props.bProfile,
    v: sideOf(r, s),
    node: r.diff?.[s]?.node ?? '',
    graph: s === 'a' ? props.aGraph : props.bGraph,
  }))
})
const related = computed(() => {
  const r = props.row
  if (!r?.diff?.related.length) return []
  return r.diff.related.map((n) => ({ node: n, text: terms.describe(n), row: props.rows.find((x) => x.node === n && x.id !== r.id) ?? null }))
})
</script>

<template>
  <div class="panel-h">
    <h3>{{ $t('compare.detail.title') }}</h3>
    <span class="meta"><span v-if="row" class="dk" :class="row.type">{{ $t('compare.type.' + row.type) }}</span></span>
  </div>
  <div class="d-scroll" data-testid="diff-detail">
    <div v-if="!row || !what || !why" class="empty" style="padding: 30px 10px"><p>{{ $t('compare.detail.empty') }}</p></div>
    <template v-else>
      <div class="d-obj">{{ what.o }}</div>
      <div v-if="what.a" class="muted small">{{ what.a }}</div>
      <div class="d-path" :title="$t('hid.canonical')" data-testid="diff-canon"><span class="faint">{{ $t('hid.canonical') }}</span> {{ row.node }}</div>
      <div v-if="row.diff?.schema || row.dflt?.schema" class="small faint mt4">Schema <span class="mono">{{ row.diff?.schema ?? row.dflt?.schema }}</span></div>

      <div class="vcards">
        <div v-for="x in sides" :key="x.s" class="vcard" :class="[x.v.origin === 'absent' ? 'absent' : x.v.origin === 'explicit' ? '' : 'dashed', x.v.origin === 'default' ? 'hid-default' : x.v.origin === 'derived' ? 'hid-derived' : '']">
          <div class="h">
            <b>{{ x.k }}</b><span class="trunc" :title="x.label">{{ x.label }}</span>
            <span v-if="x.v.origin !== 'absent'" class="tag" :class="x.v.origin">{{ $t('src.' + x.v.origin) }}</span>
          </div>
          <div class="v">{{ x.v.origin === 'absent' ? $t('compare.notPresent') : x.v.text }}</div>
          <div v-if="x.v.origin === 'default'" class="small faint mt4">{{ $t('compare.detail.fromProfile', { p: x.profile }) }}</div>
          <div v-else-if="x.v.origin === 'derived'" class="small faint mt4">{{ $t('compare.detail.derived') }}</div>
        </div>
      </div>

      <div class="section-t">{{ $t('compare.detail.why') }}</div>
      <div class="whybox" :class="'t-' + row.type" data-testid="diff-why">{{ $t('compare.' + why.key, why.params) }}</div>

      <template v-if="related.length">
        <div class="section-t">{{ $t('compare.detail.related') }}</div>
        <ul class="rel">
          <li v-for="x in related" :key="x.node">
            <button v-if="x.row" class="link-btn mono" :title="x.node" @click="emit('select', x.row.id)">{{ x.text }}</button>
            <span v-else class="mono" :title="x.node">{{ x.text }}</span>
            <div class="canon">{{ x.node }}</div>
          </li>
        </ul>
      </template>

      <div class="section-t">{{ $t('compare.detail.lines') }}</div>
      <div>
        <template v-for="x in sides" :key="x.s">
          <template v-if="x.v.lines.length">
            <button v-for="n in x.v.lines" :key="x.s + n" class="lnchip" data-testid="line-chip" @click="emit('jump', x.s, n)">{{ x.k }}:{{ n }}</button>
          </template>
          <span v-else class="small faint nolines">{{ $t(x.s === 'a' ? 'compare.detail.noLineA' : 'compare.detail.noLineB') }}</span>
        </template>
      </div>

      <div v-if="sides.some((x) => x.graph !== null && x.node)" class="row wrap mt12">
        <template v-for="x in sides" :key="x.s">
          <router-link v-if="x.graph !== null && x.node" class="btn btn-sm" :to="{ name: 'device-graph', params: { id: x.graph }, query: { node: x.node } }">
            <Icon name="graph" small />{{ $t(x.s === 'a' ? 'compare.detail.openA' : 'compare.detail.openB') }}
          </router-link>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.d-scroll { flex: 1; overflow: auto; padding: 14px; min-height: 0; }
.d-obj { font: 600 13.5px var(--font-mono); overflow-wrap: anywhere; }
.d-path { font: 12px var(--font-mono); color: var(--ink-2); overflow-wrap: anywhere; margin-top: 8px; }
.mt4 { margin-top: 4px; }
.mt12 { margin-top: 12px; }
.wrap { flex-wrap: wrap; }
.vcards { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; margin: 12px 0; }
.vcard { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; background: var(--surface-2); min-width: 0; }
.vcard.dashed { border-style: dashed; background: transparent; }
.vcard.hid-default, .vcard.hid-derived { border-color: transparent; outline-offset: 0; }
.vcard.absent { background: transparent; border-style: dotted; }
.vcard .h { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-3); min-width: 0; }
.vcard .h b { color: var(--ink); }
.vcard .h .tag { margin-left: auto; flex: none; }
.vcard .v { font: 600 13px var(--font-mono); margin-top: 4px; overflow-wrap: anywhere; }
.vcard.absent .v { font: italic 12px var(--font-ui); color: var(--ink-3); }
.whybox { border-left: 3px solid var(--line-strong); padding: 6px 10px; background: var(--surface-2); border-radius: 0 5px 5px 0; color: var(--ink); font-size: 12.5px; }
.whybox.t-renamed { border-left-color: var(--d-ren); }
.whybox.t-modified { border-left-color: var(--d-mod); }
.whybox.t-added { border-left-color: var(--d-add); }
.whybox.t-removed { border-left-color: var(--d-del); }
.rel { margin: 0; padding-left: 18px; font-size: 12px; overflow-wrap: anywhere; }
.lnchip { font: 11.5px var(--font-mono); border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink-2); border-radius: 4px; padding: 0 5px; cursor: pointer; margin: 0 4px 4px 0; display: inline-block; }
.lnchip:hover { border-color: var(--blue); color: var(--blue-ink); }
.nolines { margin-right: 10px; }
</style>
