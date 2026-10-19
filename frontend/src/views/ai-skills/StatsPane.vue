<script setup lang="ts">
/** 统计与反馈：近 N 天合计、每日调用（按校验结论堆叠）、按版本的通过率、最近调用（查看详情、加入回归集）。 */
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, get, post } from '@/api'
import { shortTime } from '@/views/account/account'
import Bits from './Bits.vue'
import RunModal from './RunModal.vue'
import { useSkillCtx, useT } from './ctx'
import { dayCols, pct, pctOf } from './logic'
import type { StatsDetail } from './types'

const { detail, cases, loadCases, flash } = useSkillCtx()
const { T, usedBy, stLabel } = useT()
const days = ref(30)
const data = ref<StatsDetail | null>(null)
const err = ref('')
const loading = ref(false)
const runOpen = ref<number | null>(null)
const adding = ref<number | null>(null)

async function load(): Promise<void> {
  if (!detail.value) return
  loading.value = true
  err.value = ''
  try { data.value = await get<StatsDetail>(`/ai/skills/${detail.value.id}/stats?days=${days.value}`) } catch (e) { err.value = errorText(e) } finally { loading.value = false }
}
onMounted(load)
watch(days, load)

const tot = computed(() => data.value?.totals)
const chart = computed(() => dayCols(data.value?.daily ?? []))
const inCase = computed(() => new Set([...(cases.value?.regression ?? []), ...(cases.value?.candidates ?? [])].map((c) => c.run_id)))

function dayTip(c: { date: string; total: number; segs: { k: string; n: number }[] }): string {
  return [`${c.date}：${T('stats.nCalls', { n: c.total })}`, ...c.segs.map((s) => `${stLabel(s.k)} ${s.n}`)].join('\n')
}
async function addCase(runId: number): Promise<void> {
  if (!detail.value) return
  adding.value = runId
  try {
    const r = await post<{ existing?: boolean }>(`/ai/skills/${detail.value.id}/cases`, { run_id: runId, kind: 'regression' })
    await loadCases()
    flash(r.existing ? T('stats.caseExisting') : T('stats.caseAdded'))
  } catch (e) { flash(errorText(e)) } finally { adding.value = null }
}
</script>

<template>
  <div v-if="detail" data-testid="sk-stats">
    <div class="row wrap" style="gap: 8px; margin-bottom: 10px; align-items: center">
      <span class="small muted">{{ T('stats.range') }}</span>
      <div class="seg" role="group" data-testid="stats-days">
        <button v-for="d in [7, 30, 90]" :key="d" type="button" :aria-pressed="days === d" @click="days = d">{{ T('stats.days', { n: d }) }}</button>
      </div>
      <button class="btn btn-sm btn-ghost" type="button" :disabled="loading" @click="load"><Icon name="refresh" small />{{ $t('c.refresh') }}</button>
    </div>
    <div v-if="err" class="notice err"><Icon name="err" /><div class="grow">{{ err }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
    <div v-else-if="!data" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
    <template v-else-if="tot">
      <div class="strip st-strip" data-testid="stats-strip">
        <div><div class="k">{{ T('kpi.calls', { d: data.days }) }}</div><div class="v" data-testid="stats-calls">{{ tot.calls }}</div><div class="s"><Bits kind="stack" :counts="tot" thin /></div></div>
        <div><div class="k">{{ T('col.rate') }}</div><div class="v" style="color: var(--teal-ink)">{{ pct(tot.pass_rate) }}</div><div class="s">{{ T('stats.nPassed', { n: tot.passed }) }}</div></div>
        <div><div class="k">{{ T('col.blocked') }}</div><div class="v" style="color: var(--red-ink)">{{ pct(tot.reject_rate) }}</div><div class="s">{{ T('stats.nCalls', { n: tot.rejected }) }}</div></div>
        <div><div class="k">{{ T('stats.others') }}</div><div class="v">{{ tot.corrected }} / {{ tot.unverifiable }} / {{ tot.error }}</div></div>
        <div><div class="k">{{ T('stats.feedback') }}</div><div class="v" style="font-size: 15px; margin-top: 6px"><Bits kind="rates" :counts="tot" /></div></div>
      </div>

      <section class="panel">
        <div class="panel-h"><h2>{{ T('stats.daily') }}</h2><span class="meta">{{ T('stats.dailyMeta') }}</span><span class="ml-auto"><Bits kind="legend" /></span></div>
        <div class="panel-b">
          <div class="chartwrap">
            <div class="daychart" data-testid="stats-chart">
              <div class="gl" style="bottom: 50%"><span>{{ chart.top / 2 }}</span></div>
              <div class="gl" style="bottom: 100%"><span>{{ chart.top }}</span></div>
              <div v-for="c in chart.cols" :key="c.date" class="col" :title="dayTip(c)"><i v-for="g in c.segs" :key="g.k" :class="`sw-${g.cls}`" :style="{ height: `${g.h.toFixed(2)}%` }" /></div>
            </div>
            <div class="dayaxis"><span v-for="c in chart.cols" :key="c.date">{{ c.label }}</span></div>
          </div>
        </div>
      </section>

      <section class="panel mt12">
        <div class="panel-h"><h2>{{ T('stats.byVersion') }}</h2><span class="meta">{{ T('stats.byVersionMeta') }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl compact" data-testid="stats-by-version">
            <thead><tr><th>{{ T('col.version') }}</th><th class="num">{{ T('col.calls') }}</th><th>{{ T('col.rate') }}</th><th class="num">{{ T('col.blocked') }}</th><th>{{ T('stats.mix') }}</th></tr></thead>
            <tbody>
              <tr v-for="v in data.by_version" :key="v.version">
                <td><Bits kind="ver" :v="v.version" :cur="v.version === detail.active" /></td>
                <td class="num">{{ v.calls }}</td>
                <td><Bits kind="rate" :r="v.pass_rate" /></td>
                <td class="num">{{ pctOf(v.rejected, v.calls) }}</td>
                <td style="min-width: 140px"><Bits kind="stack" :counts="v" thin /></td>
              </tr>
              <tr v-if="!data.by_version.length"><td colspan="5" class="muted" style="text-align: center; padding: 16px">{{ T('stats.noCalls') }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel mt12">
        <div class="panel-h"><h2>{{ T('stats.recent') }}</h2><span class="meta">{{ T('stats.recentMeta') }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl runs-tbl" data-testid="stats-runs">
            <thead><tr><th>{{ T('col.time') }}</th><th>{{ T('col.source') }}</th><th>{{ T('col.version') }}</th><th>{{ T('col.status') }}</th><th>{{ T('col.rating') }}</th><th>{{ T('col.correction') }}</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in data.runs" :key="r.id" :data-run="r.id">
                <td class="nowrap small">{{ shortTime(r.created_at) }}<div class="faint">#{{ r.id }} · {{ r.actor || '—' }}</div></td>
                <td><span class="uchip">{{ usedBy(r.source) }}</span></td>
                <td><Bits kind="ver" :v="r.version" /></td>
                <td><Bits kind="vs" :s="r.status" /></td>
                <td>
                  <span v-if="r.rating === 'up'" class="ratecell up" :title="T('rate.up')"><Icon name="thumbUp" /></span>
                  <span v-else-if="r.rating === 'down'" class="ratecell down" :title="T('rate.down')"><Icon name="thumbDown" /></span>
                  <span v-else class="faint">—</span>
                </td>
                <td><div class="corr"><template v-if="r.correction">{{ r.correction }}</template><span v-else class="faint">—</span></div></td>
                <td class="right nowrap">
                  <button class="btn btn-sm btn-ghost" type="button" data-testid="run-view" @click="runOpen = r.id"><Icon name="eye" small />{{ T('runs.view') }}</button>
                  {{ ' ' }}
                  <span v-if="r.source === 'test' || r.source === 'regression'" class="small faint">{{ T('runs.testExcluded') }}</span>
                  <span v-else-if="inCase.has(r.id)" class="small faint">{{ T('runs.inCase') }}</span>
                  <button v-else class="btn btn-sm" type="button" :disabled="adding === r.id" data-testid="run-add-case" @click="addCase(r.id)"><Icon name="plus" small />{{ T('runs.addCase') }}</button>
                </td>
              </tr>
              <tr v-if="!data.runs.length"><td colspan="7" class="muted" style="text-align: center; padding: 20px">{{ T('stats.noRuns') }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
    <RunModal v-if="runOpen !== null" :sid="detail.id" :run-id="runOpen" @close="runOpen = null" />
  </div>
</template>
