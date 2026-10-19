<script setup lang="ts">
/**
 * 分析摘要（REQ-034）：六格（对象、检查发现、未识别 / 原文行、依赖默认值、安全基线、与上一版本），每格可点；
 * 下面是各功能域、TCP/IP 各层、检查发现、依赖默认值的关键配置、基线不符合项、版本变化，每一条都可跳到对应视图。
 * 数字全部来自后端（GET /devices/{id}/analysis?parts=summary）。
 */
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { get } from '@/api'
import { renderText } from '@/views/check/logic'
import type { Rule } from '@/views/check/types'
import { formatValue } from '@/views/device-graph/model'
import { BAND_ORDER, type Finding, type LayerInfo, type LayersData, type SummaryData } from './types'

const props = defineProps<{
  summary: SummaryData | null
  loading: boolean
  error: string
  layers: LayersData | null
  layerInfo: LayerInfo[]
  deviceId: number | null
  labelOf: (id: string) => string
  attrName: (schema: string) => string
  pick: (o: Record<string, string> | null | undefined) => string
}>()
const emit = defineEmits<{
  (e: 'jump', target: { node?: string; line?: number; view?: string; domain?: string; defaults?: boolean }): void
  (e: 'retry'): void
}>()
const { t, locale } = useI18n()

const rules = shallowRef(new Map<string, Rule>())
onMounted(async () => {
  try {
    rules.value = new Map((await get<{ rules: Rule[] }>('/kb/rules')).rules.map((r) => [r.id, r]))
  } catch { /* 取不到规则时只显示规则编号 */ }
})

const sec = ref<HTMLElement>()
const objects = computed(() => props.summary?.domains.reduce((s, d) => s + d.objects, 0) ?? 0)
const maxDomain = computed(() => Math.max(1, ...(props.summary?.domains.map((d) => d.objects + d.attrs + d.defaults) ?? [1])))
const maxLayer = computed(() => Math.max(1, ...(props.summary?.layers.map((l) => l.objects) ?? [1])))
const sev = computed(() => props.summary?.check?.summary.by_severity ?? { error: 0, warning: 0, info: 0 })
const checkTone = computed(() => (sev.value.error ? 'bad' : sev.value.warning ? 'warn' : 'ok'))
const bl = computed(() => props.summary?.baseline ?? null)
const blTone = computed(() => (bl.value?.score == null ? '' : bl.value.score < 60 ? 'bad' : bl.value.score < 85 ? 'warn' : 'ok'))
const hs = computed(() => props.summary?.history ?? null)
/** 与 TCP/IP 视图一致：应用层在上、物理层在下。 */
const layerRows = computed(() =>
  BAND_ORDER.map((id) => props.layerInfo.find((x) => x.id === id))
    .filter((x): x is LayerInfo => !!x)
    .map((x) => ({ id: x.id, name: props.pick(x.name), objects: props.summary?.layers.find((l) => l.id === x.id)?.objects ?? 0 })),
)

function msg(f: Finding, which: 'message' | 'suggestion', texts: Record<string, Record<string, string>>): string {
  return renderText(f[which], String(locale.value), texts, rules.value)
}
function ruleTitle(f: Finding): string {
  const r = rules.value.get(f.rule)
  return r ? props.pick(r.title) || f.rule : f.rule
}
function scrollTo(id: string): void {
  sec.value?.querySelector(`#an-sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function tileLines(): void {
  const s = props.summary
  if (!s) return
  if (s.unknown_lines.length) emit('jump', { line: s.unknown_lines[0], view: 'script' })
  else emit('jump', { view: 'script' })
}
const kindText = (k: string) => t(`device-analysis.change.${k}`)
const sevTag = (s: string) => (s === 'error' ? 'fail' : s === 'warning' ? 't-amber' : '')
</script>

<template>
  <div ref="sec" class="sumv" data-testid="analysis-summary">
    <div v-if="error" class="notice err"><Icon name="err" /><div class="grow">{{ error }}</div><button class="btn btn-sm" @click="emit('retry')">{{ $t('c.retry') }}</button></div>
    <div v-else-if="loading || !summary" class="faint small pad">{{ $t('device-analysis.summaryLoading') }}</div>
    <template v-else>
      <div class="tiles">
        <button type="button" class="tile" data-testid="tile-objects" @click="scrollTo('domains')">
          <span class="k"><Icon name="layers" small />{{ $t('device-analysis.tile.objects') }}</span>
          <span class="v">{{ objects }}</span>
          <span class="s">{{ $t('device-analysis.tile.domainsN', { n: summary.domains.length }) }}</span>
          <span class="go">{{ $t('device-analysis.view') }} →</span>
        </button>
        <button type="button" class="tile" data-testid="tile-check" @click="scrollTo('check')">
          <span class="k"><Icon name="shield" small />{{ $t('device-analysis.tile.check') }}</span>
          <span class="v" :class="checkTone">{{ summary.check ? summary.check.summary.total - summary.check.summary.ignored : '—' }}</span>
          <span class="s">error {{ sev.error }} · warning {{ sev.warning }} · info {{ sev.info }}</span>
          <span class="go">{{ $t('device-analysis.view') }} →</span>
        </button>
        <button type="button" class="tile" data-testid="tile-lines" @click="tileLines">
          <span class="k"><Icon name="unknown" small />{{ $t('device-analysis.tile.lines') }}</span>
          <span class="v" :class="{ bad: summary.lines.unknown }">{{ summary.lines.unknown }} / {{ summary.lines.raw }}</span>
          <span class="s">{{ $t('device-analysis.tile.linesSub', { n: summary.lines.total, c: (summary.lines.coverage * 100).toFixed(1) }) }}</span>
          <span class="go">{{ $t('device-analysis.view') }} →</span>
        </button>
        <button type="button" class="tile" data-testid="tile-defaults" @click="scrollTo('defaults')">
          <span class="k"><Icon name="info" small />{{ $t('device-analysis.tile.defaults') }}</span>
          <span class="v" :class="{ warn: summary.defaults.key }">{{ summary.defaults.key }} / {{ summary.defaults.total }}</span>
          <span class="s">{{ $t('device-analysis.tile.defaultsSub') }}</span>
          <span class="go">{{ $t('device-analysis.view') }} →</span>
        </button>
        <button type="button" class="tile" data-testid="tile-baseline" @click="scrollTo('baseline')">
          <span class="k"><Icon name="shield" small />{{ $t('device-analysis.tile.baseline') }}</span>
          <span class="v" :class="blTone">{{ bl?.score ?? '—' }}</span>
          <span class="s">{{ bl ? $t('device-analysis.tile.baselineSub', { b: bl.baseline, n: bl.failure_count }) : $t('device-analysis.unavailable') }}</span>
          <span class="go">{{ $t('device-analysis.view') }} →</span>
        </button>
        <button type="button" class="tile" data-testid="tile-history" @click="scrollTo('history')">
          <span class="k"><Icon name="history" small />{{ $t('device-analysis.tile.history') }}</span>
          <span class="v">{{ hs?.summary ? `~${hs.summary.modified} +${hs.summary.added} −${hs.summary.removed}` : '—' }}</span>
          <span class="s">{{ hs?.previous ? `#${hs.previous.seq} → #${hs.current.seq}` : hs ? $t('device-analysis.firstVersion') : $t('device-analysis.noHistory') }}</span>
          <span class="go">{{ $t('device-analysis.view') }} →</span>
        </button>
      </div>

      <div class="sgrid">
        <section id="an-sec-domains" class="panel">
          <div class="panel-h">
            <h3>{{ $t('device-analysis.byDomain') }}</h3>
            <span class="meta keys"><i class="k-o" />{{ $t('device-analysis.objectsW') }}<i class="k-a" />{{ $t('device-analysis.attrsW') }}<span class="tag default">{{ $t('hid.default') }}</span></span>
          </div>
          <div class="panel-b">
            <button v-for="d in summary.domains" :key="d.domain" type="button" class="dbar" :title="$t('device-analysis.domainFilterTip')" @click="emit('jump', { view: 'script', domain: d.domain })">
              <span>{{ d.domain }}</span>
              <span class="bar" :style="{ width: `${((d.objects + d.attrs + d.defaults) / maxDomain) * 100}%` }">
                <i class="o" :style="{ flex: d.objects }" /><i class="a" :style="{ flex: d.attrs }" /><i class="df" :style="{ flex: d.defaults }" />
              </span>
              <span class="num">{{ d.objects }}</span>
            </button>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h3>{{ $t('device-analysis.byLayer') }}</h3><span class="meta">{{ $t('device-analysis.crossN', { n: summary.cross_layer }) }}</span></div>
          <div class="panel-b">
            <button v-for="r in layerRows" :key="r.id" type="button" class="lyrow" :class="{ mpls: r.id === 'mpls' }" :data-ly="r.id" @click="emit('jump', { view: 'tcpip' })">
              <span>{{ r.name }}</span><span class="bar"><i :style="{ width: `${(r.objects / maxLayer) * 100}%` }" /></span><span class="num">{{ r.objects }}</span>
            </button>
            <div v-if="layers" class="xmatrix">
              <span v-for="x in layers.cross_by_layers" :key="`${x.a}${x.b}`" class="xm">{{ pick(layerInfo.find((l) => l.id === x.a)?.name) || x.a }} ↔ {{ pick(layerInfo.find((l) => l.id === x.b)?.name) || x.b }} <b>{{ x.count }}</b></span>
            </div>
          </div>
        </section>
      </div>

      <div class="sgrid">
        <section id="an-sec-check" class="panel">
          <div class="panel-h">
            <h3>{{ $t('device-analysis.checkTitle') }}</h3>
            <router-link class="meta" :to="{ name: 'check', query: deviceId ? { device: deviceId } : {} }">{{ $t('device-analysis.checkAll') }} →</router-link>
          </div>
          <div class="panel-b">
            <div v-if="!summary.check?.top.length" class="small faint">{{ $t('device-analysis.none') }}</div>
            <button v-for="(f, i) in summary.check?.top ?? []" :key="i" type="button" class="sli" data-testid="finding" @click="emit('jump', { node: f.node, line: f.lines[0], view: 'script' })">
              <span class="tag" :class="sevTag(f.severity)">{{ f.severity }}</span>
              <span class="txt"><b>{{ ruleTitle(f) }}</b> <code>{{ labelOf(f.node) }}</code><br><span class="m">{{ msg(f, 'message', summary.check!.texts) }}</span></span>
              <span class="ln">{{ f.lines.length ? $t('device-analysis.lineN', { n: f.lines[0] }) : '' }}</span>
            </button>
          </div>
        </section>
        <section id="an-sec-defaults" class="panel">
          <div class="panel-h"><h3>{{ $t('device-analysis.keyDefaults') }}</h3><span class="meta">{{ $t('device-analysis.keyDefaultsTip') }}</span></div>
          <div class="panel-b">
            <div v-if="!summary.defaults.items.length" class="small faint">{{ $t('device-analysis.none') }}</div>
            <button v-for="it in summary.defaults.items" :key="it.node" type="button" class="sli" data-testid="key-default" @click="emit('jump', { node: it.node, view: 'script', defaults: true })">
              <span class="tag default">{{ $t('hid.default') }}</span>
              <span class="txt"><code>{{ it.owner ? labelOf(it.owner) : '' }} › {{ attrName(it.schema) }} = {{ formatValue(it.value) }}</code><br><span class="m">{{ it.others.map((o) => `${o.profile} = ${formatValue(o.value)}`).join('；') }}</span></span>
              <span class="ln">{{ it.domain }}</span>
            </button>
            <div v-if="summary.defaults.truncated" class="small faint">{{ $t('device-analysis.truncated', { n: summary.defaults.key }) }}</div>
          </div>
        </section>
      </div>

      <div class="sgrid">
        <section id="an-sec-baseline" class="panel">
          <div class="panel-h"><h3>{{ $t('device-analysis.baselineTitle') }}</h3><router-link class="meta" :to="{ name: 'baseline' }">{{ $t('nav.baseline') }} →</router-link></div>
          <div class="panel-b">
            <div v-if="!bl" class="small faint">{{ $t('device-analysis.unavailable') }}</div>
            <div v-else-if="!bl.failures.length" class="small faint">{{ $t('device-analysis.none') }}</div>
            <button v-for="(f, i) in bl?.failures ?? []" :key="i" type="button" class="sli" @click="emit('jump', { node: f.node, line: f.lines[0], view: 'script' })">
              <span class="tag" :class="sevTag(f.severity)">{{ f.severity }}</span>
              <span class="txt"><code>{{ f.rule }}</code><br><span class="m">{{ msg(f, 'message', bl!.texts) }}</span></span>
              <span class="ln">{{ f.lines.length ? $t('device-analysis.lineN', { n: f.lines[0] }) : '' }}</span>
            </button>
          </div>
        </section>
        <section id="an-sec-history" class="panel">
          <div class="panel-h"><h3>{{ $t('device-analysis.historyTitle') }}</h3><router-link v-if="deviceId" class="meta" :to="{ name: 'history', params: { id: deviceId } }">{{ $t('nav.history') }} →</router-link></div>
          <div class="panel-b">
            <div v-if="!hs" class="small faint">{{ $t('device-analysis.noHistory') }}</div>
            <div v-else-if="!hs.previous" class="small faint">{{ $t('device-analysis.firstVersion') }}</div>
            <div v-else-if="!hs.items.length" class="small faint">{{ $t('device-analysis.noChange') }}</div>
            <button v-for="it in hs?.items ?? []" :key="it.object" type="button" class="sli" @click="emit('jump', { node: it.object, view: 'script' })">
              <span class="tag t-amber">{{ kindText(it.kind) }}</span>
              <span class="txt"><code>{{ labelOf(it.object) }}</code></span>
              <span class="ln">{{ it.domain }}</span>
            </button>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sumv { flex: 1; min-height: 0; overflow: auto; padding: 12px; display: flex; flex-direction: column; gap: 12px; }
.sumv > * { flex: none; }
.pad { padding: 30px; text-align: center; }
.tiles { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--r-panel); overflow: hidden; background: var(--surface); }
.tile { all: unset; box-sizing: border-box; padding: 10px 12px; border-left: 1px solid var(--line); cursor: pointer; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.tile:first-child { border-left: 0; }
.tile:hover { background: var(--surface-2); }
.tile:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.tile .k { font-size: 11.5px; color: var(--ink-2); display: flex; align-items: center; gap: 5px; }
.tile .v { font: 600 22px var(--font-display); color: var(--ink); line-height: 1.15; white-space: nowrap; }
.tile .s { font-size: 11px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tile .v.warn { color: var(--amber-ink); }
.tile .v.bad { color: var(--red-ink); }
.tile .v.ok { color: var(--teal-ink); }
.tile .go { font-size: 11px; color: var(--blue-ink); margin-top: 2px; }
@media (max-width: 1250px) {
  .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .tile:nth-child(4) { border-left: 0; }
  .tile:nth-child(n+4) { border-top: 1px solid var(--line); }
}
.sgrid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
@media (max-width: 1000px) { .sgrid { grid-template-columns: 1fr; } }
.sgrid .panel-h { flex-wrap: wrap; row-gap: 2px; }
.sgrid .panel-h h3 { white-space: nowrap; flex: none; }
.sgrid .panel-h .meta { min-width: 0; }
.keys { display: inline-flex; align-items: center; gap: 5px; }
.keys i { width: 10px; height: 8px; border-radius: 2px; display: inline-block; }
.keys .k-o { background: var(--teal); }
.keys .k-a { background: var(--teal-line); margin-left: 6px; }
.keys .tag { margin-left: 6px; }
.dbar, .lyrow { all: unset; box-sizing: border-box; display: grid; grid-template-columns: 110px minmax(0, 1fr) 44px; gap: 8px; align-items: center; font-size: 12px; padding: 3px 4px; cursor: pointer; border-radius: 4px; width: 100%; }
.dbar:hover, .lyrow:hover { background: var(--surface-2); }
.dbar:focus-visible, .lyrow:focus-visible, .sli:focus-visible { outline: 2px solid var(--focus); }
.dbar .bar { height: 8px; border-radius: 4px; overflow: hidden; display: flex; min-width: 4px; }
.dbar .bar i { display: block; height: 100%; }
.dbar .bar i.o { background: var(--teal); }
.dbar .bar i.a { background: var(--teal-line); }
.dbar .bar i.df { background: repeating-linear-gradient(90deg, var(--ink-3) 0 2px, transparent 2px 4px); opacity: .6; }
.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-2); }
.lyrow { grid-template-columns: 130px minmax(0, 1fr) 44px; }
.lyrow .bar { height: 12px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
.lyrow .bar i { display: block; height: 100%; background: var(--c); }
.lyrow.mpls .bar i { background: repeating-linear-gradient(135deg, var(--c) 0 3px, color-mix(in srgb, var(--c) 55%, transparent) 3px 6px); }
.xmatrix { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.xm { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; padding: 1px 7px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); color: var(--ink-2); }
.xm b { color: var(--ink); }
.sli { all: unset; box-sizing: border-box; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: baseline; padding: 6px 4px; border-top: 1px solid var(--line); font-size: 12.5px; cursor: pointer; width: 100%; }
.sli:first-of-type { border-top: 0; }
.sli:hover { background: var(--surface-2); }
.sli .txt { min-width: 0; overflow-wrap: anywhere; }
.sli .m { color: var(--ink-2); font-size: 12px; }
.sli code { font: 11.5px var(--font-mono); }
.sli .ln { font: 11px var(--font-mono); color: var(--blue-ink); white-space: nowrap; }
</style>
