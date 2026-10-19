<script setup lang="ts">
/** AI 用量统计（REQ-040 追加）：时间范围（近 7 / 30 / 90 天或自定义）、合计、按天堆叠柱（输入 / 输出 token，悬停看明细，
 *  可切换为表格）、按用户 / 接口 / 功能 / 模型汇总、导出 CSV。管理员看全部；普通账号后端只统计本人的（mine 时不显示“按用户”）。
 *  connectionId：只看某个接口（接口设置页）。颜色：输入 = --chart-in、输出 = --chart-out（两种主题分别校验过色觉区分）。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { download, errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import { fmtTokens } from './logic'
import {
  BREAKDOWNS, PRESETS, csvName, dayBars, labelIdx, lastDays, shareOf, shortDay, total, usageQuery, validRange,
  type Bar, type Breakdown, type Group, type Usage, type UsageRow,
} from './usage'

const props = defineProps<{ mine?: boolean; connectionId?: number | null; title?: string; compact?: boolean }>()
const { t } = useI18n()
const U = (k: string, p?: Record<string, unknown>) => t(`ai-usage.${k}`, p ?? {})

const preset = ref<number | 'custom'>(30)
const init = lastDays(30)
const from = ref(init.from)
const to = ref(init.to)
const cFrom = ref(init.from)
const cTo = ref(init.to)
const rangeErr = ref(false)
const data = ref<Usage | null>(null)
const loading = ref(false)
const err = ref('')
const view = ref<'chart' | 'table'>('chart')
const groups = computed<Breakdown[]>(() => BREAKDOWNS.filter((g) => !(g === 'user' && props.mine) && !(g === 'connection' && props.connectionId != null)))
const group = ref<Breakdown>(props.mine ? 'feature' : 'user')
if (!groups.value.includes(group.value)) group.value = groups.value[0]

async function load(): Promise<void> {
  loading.value = true
  err.value = ''
  try {
    data.value = await get<Usage>(`/ai/usage?${usageQuery({ from: from.value, to: to.value, connectionId: props.connectionId })}`)
  } catch (e) {
    err.value = U('loadErr', { e: errorText(e) })
  } finally {
    loading.value = false
  }
}
defineExpose({ load })

function pick(n: number | 'custom'): void {
  preset.value = n
  if (n === 'custom') return
  const r = lastDays(n)
  from.value = r.from
  to.value = r.to
  void load()
}
function applyCustom(): void {
  rangeErr.value = !validRange(cFrom.value, cTo.value)
  if (rangeErr.value) return
  from.value = cFrom.value
  to.value = cTo.value
  void load()
}

// ---------- 图表 ----------
const W = 640
const H = 160
const geo = computed(() => dayBars(data.value?.by_day ?? [], W, H))
const labels = computed(() => labelIdx(geo.value.bars.length, props.compact ? 5 : 7))
const hover = ref<Bar | null>(null)
const tipX = ref(0)
function onHover(b: Bar | null): void {
  hover.value = b
  if (b) tipX.value = ((b.x + b.w / 2) / W) * 100
}
const rows = computed<UsageRow[]>(() => (data.value ? (data.value[`by_${group.value}`] ?? []) : []))
const shares = computed(() => shareOf(rows.value))
const hasData = computed(() => (data.value?.totals.calls ?? 0) > 0)
const keyLabel = (k: string) => (group.value === 'connection' && k === 'personal' ? U('personal') : k || '—')

async function exportCsv(g: Group): Promise<void> {
  try {
    await download(`/ai/usage/export?${usageQuery({ from: from.value, to: to.value, connectionId: props.connectionId, group: g })}`, csvName(g, from.value, to.value))
  } catch (e) {
    err.value = errorText(e)
  }
}

watch(() => props.connectionId, () => void load())
onMounted(load)
</script>

<template>
  <section class="panel usage-panel" :class="{ dim: loading && data }" :data-testid="mine ? 'my-ai-usage' : 'ai-usage-panel'">
    <div class="panel-h">
      <h2>{{ title ?? U('title') }}</h2>
      <span class="meta">{{ mine ? U('subMine') : U('sub') }}</span>
    </div>
    <div class="panel-b">
      <div class="filters" data-testid="usage-range">
        <div class="seg" role="group">
          <button v-for="n in PRESETS" :key="n" type="button" :aria-pressed="preset === n" :data-testid="`usage-days-${n}`" @click="pick(n)">{{ U('days', { n }) }}</button>
          <button type="button" :aria-pressed="preset === 'custom'" data-testid="usage-custom" @click="pick('custom')">{{ U('custom') }}</button>
        </div>
        <template v-if="preset === 'custom'">
          <label class="dt">{{ U('from') }} <input v-model="cFrom" type="date" class="input" data-testid="usage-from"></label>
          <label class="dt">{{ U('to') }} <input v-model="cTo" type="date" class="input" data-testid="usage-to"></label>
          <button type="button" class="btn btn-sm" data-testid="usage-apply" @click="applyCustom">{{ U('apply') }}</button>
          <span v-if="rangeErr" class="err small"><Icon name="err" small />{{ U('rangeErr') }}</span>
        </template>
        <span class="ml-auto mono small faint">{{ data?.from ?? from }} – {{ data?.to ?? to }}</span>
      </div>

      <div v-if="err" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ err }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <div v-else-if="!data && loading" class="empty small">{{ $t('c.loading') }}</div>
      <template v-else-if="data">
        <div class="tiles" data-testid="usage-totals">
          <div class="tile"><span class="k">{{ U('total') }}</span><b>{{ fmtTokens(total(data.totals)) }}</b></div>
          <div class="tile"><span class="k"><i class="sw in" />{{ U('tokensIn') }}</span><b>{{ fmtTokens(data.totals.tokens_in) }}</b></div>
          <div class="tile"><span class="k"><i class="sw out" />{{ U('tokensOut') }}</span><b>{{ fmtTokens(data.totals.tokens_out) }}</b></div>
          <div class="tile"><span class="k">{{ U('calls') }}</span><b>{{ data.totals.calls.toLocaleString('en-US') }}</b><span v-if="data.totals.errors" class="bad small">{{ U('errors') }} {{ data.totals.errors }}</span></div>
        </div>

        <div v-if="!hasData" class="empty small" data-testid="usage-empty">{{ U('empty') }}</div>
        <template v-else>
          <div class="chart-h">
            <h3>{{ U('chartT') }}</h3>
            <span class="legend"><span><i class="sw in" />{{ U('legendIn') }}</span><span><i class="sw out" />{{ U('legendOut') }}</span></span>
            <div class="seg small-seg ml-auto" role="group">
              <button type="button" :aria-pressed="view === 'chart'" data-testid="usage-view-chart" @click="view = 'chart'">{{ U('chartView') }}</button>
              <button type="button" :aria-pressed="view === 'table'" data-testid="usage-view-table" @click="view = 'table'">{{ U('tableView') }}</button>
            </div>
            <button type="button" class="btn btn-sm" data-testid="usage-export-day" @click="exportCsv('day')"><Icon name="download" small />{{ U('exportDay') }}</button>
          </div>
          <div v-if="view === 'chart'" class="chart" data-testid="usage-chart" @pointerleave="onHover(null)">
            <div class="yax"><span>{{ fmtTokens(geo.max) }}</span><span>{{ fmtTokens(geo.max / 2) }}</span><span>0</span></div>
            <div class="plot">
              <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="U('chartAria')">
                <line class="grid" x1="0" :x2="W" :y1="H / 2" :y2="H / 2" />
                <line class="base" x1="0" :x2="W" :y1="H - 0.5" :y2="H - 0.5" />
                <g v-for="b in geo.bars" :key="b.key">
                  <rect v-if="b.hIn > 0" class="m in" :class="{ on: hover?.key === b.key }" :x="b.x" :width="b.w" :y="H - b.hIn" :height="b.hIn" />
                  <rect v-if="b.hOut > 0" class="m out" :class="{ on: hover?.key === b.key }" :x="b.x" :width="b.w" :y="H - b.hIn - b.hOut - (b.hIn > 0 ? 2 : 0)" :height="b.hOut" />
                  <rect class="hit" :x="b.x - 1" :width="b.w + 2" y="0" :height="H" tabindex="0" @pointerenter="onHover(b)" @focus="onHover(b)" @blur="onHover(null)" />
                </g>
              </svg>
              <div v-if="hover" class="tip" :style="{ left: `${tipX}%` }" role="status" data-testid="usage-tip">
                <div class="tt">{{ hover.key }}</div>
                <div class="tr"><i class="ln in" /><b>{{ hover.row.tokens_in.toLocaleString('en-US') }}</b><span>{{ U('legendIn') }}</span></div>
                <div class="tr"><i class="ln out" /><b>{{ hover.row.tokens_out.toLocaleString('en-US') }}</b><span>{{ U('legendOut') }}</span></div>
                <div class="tf">{{ U('tipCalls', { n: hover.row.calls, e: hover.row.errors }) }}</div>
              </div>
              <div class="xax"><span v-for="i in labels" :key="i" :style="{ left: `${((geo.bars[i].x + geo.bars[i].w / 2) / W) * 100}%` }">{{ shortDay(geo.bars[i].key) }}</span></div>
            </div>
          </div>
          <div v-else class="tbl-wrap" style="max-height: 260px">
            <table class="tbl compact" data-testid="usage-day-table">
              <thead><tr><th>{{ U('day') }}</th><th class="num">{{ U('calls') }}</th><th class="num">{{ U('errors') }}</th><th class="num">{{ U('tokensIn') }}</th><th class="num">{{ U('tokensOut') }}</th></tr></thead>
              <tbody><tr v-for="r in data.by_day" :key="r.key"><td class="mono">{{ r.key }}</td><td class="num">{{ r.calls }}</td><td class="num">{{ r.errors }}</td><td class="num">{{ r.tokens_in.toLocaleString('en-US') }}</td><td class="num">{{ r.tokens_out.toLocaleString('en-US') }}</td></tr></tbody>
            </table>
          </div>

          <div class="tabs mt16" role="tablist" data-testid="usage-groups">
            <button v-for="g in groups" :key="g" type="button" role="tab" :aria-selected="group === g" :data-testid="`usage-by-${g}`" @click="group = g">{{ U(`by_${g}`) }}</button>
            <button type="button" class="btn btn-sm ml-auto exp" data-testid="usage-export" @click="exportCsv(group)"><Icon name="download" small />{{ U('export') }}</button>
          </div>
          <div class="tbl-wrap" style="max-height: 300px">
            <table class="tbl compact" :data-testid="`usage-table-${group}`">
              <thead><tr><th>{{ U(`key_${group}`) }}</th><th class="num">{{ U('calls') }}</th><th class="num">{{ U('errors') }}</th><th class="num">{{ U('tokensIn') }}</th><th class="num">{{ U('tokensOut') }}</th><th class="sharecol">{{ U('share') }}</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in rows" :key="r.key + (r.id ?? '')">
                  <td :class="{ mono: group === 'model' || group === 'feature' }">{{ keyLabel(r.key) }}</td>
                  <td class="num">{{ r.calls }}</td>
                  <td class="num" :class="{ bad: r.errors }">{{ r.errors }}</td>
                  <td class="num">{{ r.tokens_in.toLocaleString('en-US') }}</td>
                  <td class="num">{{ r.tokens_out.toLocaleString('en-US') }}</td>
                  <td><div class="meter"><div class="bar"><i :style="{ width: `${Math.round(shares[i] * 100)}%` }" /></div><span class="small faint">{{ fmtTokens(total(r)) }}</span></div></td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.usage-panel { --chart-in: #2A9D8F; --chart-out: #7A52C7; }
:root[data-theme="dark"] .usage-panel { --chart-in: #2FA394; --chart-out: #9A7CE6; }
.usage-panel.dim .chart, .usage-panel.dim .tiles { opacity: .55; transition: opacity .15s; }
.filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.dt { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; color: var(--ink-2); }
.dt .input { height: 28px; width: auto; font-size: 12px; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; border: 1px solid var(--line); border-radius: 8px; margin: 14px 0; }
.tile { padding: 10px 14px; display: flex; flex-direction: column; gap: 2px; border-left: 1px solid var(--line); min-width: 0; }
.tile:first-child { border-left: 0; }
.tile .k { font-size: 12px; color: var(--ink-3); display: inline-flex; gap: 6px; align-items: center; }
.tile b { font-size: 20px; font-variant-numeric: tabular-nums; color: var(--ink); }
.bad { color: var(--red-ink); }
.sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }
.sw.in { background: var(--chart-in); }
.sw.out { background: var(--chart-out); }
.chart-h { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.chart-h h3 { font-size: 13px; }
.legend { display: inline-flex; gap: 12px; font-size: 12px; color: var(--ink-2); }
.legend span { display: inline-flex; gap: 5px; align-items: center; }
.small-seg button { height: 26px; font-size: 12px; }
.chart { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; }
.yax { display: flex; flex-direction: column; justify-content: space-between; height: 160px; font-size: 11px; color: var(--ink-3); text-align: right; font-variant-numeric: tabular-nums; }
.plot { position: relative; }
.plot svg { display: block; width: 100%; height: 160px; overflow: visible; }
.grid { stroke: var(--line); stroke-width: 1; stroke-dasharray: 2 3; vector-effect: non-scaling-stroke; }
.base { stroke: var(--line-strong); stroke-width: 1; vector-effect: non-scaling-stroke; }
.m.in { fill: var(--chart-in); }
.m.out { fill: var(--chart-out); }
.m.on { opacity: .8; }
.hit { fill: transparent; cursor: default; outline: none; }
.hit:focus-visible { stroke: var(--focus); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.xax { position: relative; height: 18px; margin-top: 4px; font-size: 11px; color: var(--ink-3); }
.xax span { position: absolute; transform: translateX(-50%); white-space: nowrap; font-variant-numeric: tabular-nums; }
.tip { position: absolute; top: 4px; transform: translateX(-50%); background: var(--surface); border: 1px solid var(--line); border-radius: 6px; box-shadow: var(--shadow-pop); padding: 7px 10px; font-size: 12px; pointer-events: none; z-index: 5; min-width: 150px; }
.tip .tt { color: var(--ink-3); margin-bottom: 4px; font-variant-numeric: tabular-nums; }
.tip .tr { display: grid; grid-template-columns: 12px auto minmax(0, 1fr); gap: 6px; align-items: center; }
.tip .tr b { font-variant-numeric: tabular-nums; color: var(--ink); }
.tip .tr span { color: var(--ink-2); }
.tip .tf { margin-top: 4px; color: var(--ink-3); }
.ln { width: 12px; height: 2px; border-radius: 1px; display: inline-block; }
.ln.in { background: var(--chart-in); }
.ln.out { background: var(--chart-out); }
.tabs .exp { align-self: center; margin-bottom: 4px; }
.sharecol { width: 30%; }
.meter { display: flex; gap: 8px; align-items: center; min-width: 120px; }
@media (max-width: 760px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } .tile:nth-child(3) { border-left: 0; } .tile:nth-child(n+3) { border-top: 1px solid var(--line); } }
</style>
