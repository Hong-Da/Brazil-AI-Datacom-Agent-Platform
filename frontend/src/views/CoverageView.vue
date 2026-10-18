<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import { pickLang } from '@/i18n'
import { saveText } from './profiles/csv'
import {
  buildCoverage, coverageCsv, coverageSummary, domainStats, filterCoverage, groupByDomain,
  type CovCell, type CovFilter, type CovRow,
} from './profiles/coverage'
import { pct, shortId, vendorBadge } from './profiles/format'
import type { CoverageResult, ProfileDetail, ProfileList, ProfileRow } from './profiles/types'
import { useTerms } from '@/stores/terms'
import { styleForm } from './schema/styles'

const { t, te, locale } = useI18n()
const terms = useTerms()
/** 当前显示风格的命令写法（REQ-026） */
const formOf = (r: CovRow) => styleForm(terms, r.node, r.type, terms.style)
function nodeTitle(r: CovRow): string {
  const f = formOf(r)
  return [pickLang(r.semantic, String(locale.value)), f ? `${t(`style.${terms.style}`)}: ${f}` : ''].filter(Boolean).join(' · ')
}

const rows = ref<CovRow[]>([])
const pids = ref<string[]>([])
const profiles = ref<Record<string, ProfileRow>>({})
const partial = ref(false)
const loading = ref(true)
const err = ref('')
const closed = reactive<Record<string, boolean>>({})
const filter = reactive<CovFilter>({ q: '', domain: '', cred: '', gapsOnly: false, diffOnly: false, showDeprecated: false })

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [cov, list] = await Promise.all([get<CoverageResult>('/kb/coverage'), get<ProfileList>('/kb/profiles')])
    // 可信度与是否继承来自各 Profile 的详情；个别取不到时矩阵照常显示状态
    const settled = await Promise.allSettled(cov.profiles.map((p) => get<ProfileDetail>(`/kb/profiles/${encodeURIComponent(p)}`)))
    const details: Record<string, ProfileDetail | undefined> = {}
    cov.profiles.forEach((p, i) => { const s = settled[i]; details[p] = s.status === 'fulfilled' ? s.value : undefined })
    partial.value = settled.some((s) => s.status === 'rejected')
    profiles.value = Object.fromEntries(list.profiles.map((p) => [p.id, p]))
    const vendors = Object.fromEntries(list.profiles.map((p) => [p.id, p.vendor]))
    pids.value = cov.profiles
    rows.value = buildCoverage(cov, details, vendors)
  } catch (e) {
    err.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

const domains = computed(() => [...new Set(rows.value.map((r) => r.domain))].sort())
const filtered = computed(() => filterCoverage(rows.value, filter, formOf))
const groups = computed(() => groupByDomain(filtered.value))
const sum = computed(() => coverageSummary(rows.value))
const filtering = computed(() => !!(filter.q || filter.domain || filter.cred || filter.gapsOnly || filter.diffOnly))

function domLabel(d: string): string {
  const k = `coverage.dom_${d.replace(/-/g, '_')}`
  return te(k) ? t(k) : d
}
function profCov(pid: string): number {
  const p = profiles.value[pid]
  return p ? pct(p.coverage) : 0
}
function cellTitle(c: CovCell): string {
  return c.inherited ? t('coverage.inhFrom', { p: c.origin ?? '' }) : ''
}
function clearFilters() {
  Object.assign(filter, { q: '', domain: '', cred: '', gapsOnly: false, diffOnly: false })
}
function exportCsv() {
  saveText(`coverage_${new Date().toISOString().slice(0, 10)}.csv`, coverageCsv(filtered.value, pids.value))
}
</script>

<template>
  <main class="main">
    <div class="page fill">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('coverage.title') }}</h1>
          <p class="ph-sub">{{ $t('coverage.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" :disabled="loading" data-testid="coverage-refresh" @click="load"><Icon name="refresh" small />{{ $t('c.refresh') }}</button>
          <button class="btn" :disabled="!filtered.length" data-testid="coverage-export" @click="exportCsv"><Icon name="download" small />{{ $t('coverage.exportCsv') }}</button>
        </div>
      </div>

      <div v-if="err" class="notice err" data-testid="coverage-error">
        <Icon name="err" /><div class="grow small">{{ err }}</div>
        <button class="btn btn-xs" @click="load">{{ $t('c.retry') }}</button>
      </div>
      <div v-else-if="loading && !rows.length" class="panel"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>
      <div v-else-if="!pids.length" class="panel">
        <div class="empty">
          <h3>{{ $t('coverage.noProfiles') }}</h3>
          <router-link class="btn btn-sm btn-primary" :to="{ name: 'profiles' }">{{ $t('nav.profiles') }}</router-link>
        </div>
      </div>

      <template v-else>
        <div class="sumrow" data-testid="coverage-summary">
          <div><div class="k">{{ $t('coverage.sNodes') }}</div><div class="v">{{ sum.nodes }}<small>{{ $t('coverage.sNodesSub', { n: sum.domains }) }}</small></div></div>
          <div><div class="k">{{ $t('coverage.sGaps') }}</div><div class="v" style="color:var(--amber-ink)">{{ sum.gaps }}<small>{{ $t('coverage.sGapsSub') }}</small></div></div>
          <div><div class="k">{{ $t('coverage.sDiffs') }}</div><div class="v">{{ sum.diffs }}<small>{{ $t('coverage.sDiffsSub') }}</small></div></div>
          <div><div class="k">{{ $t('coverage.sDraft') }}</div><div class="v">{{ sum.draft }}<small>{{ $t('coverage.sDraftSub') }}</small></div></div>
        </div>

        <div v-if="partial" class="notice warn" style="margin-bottom:10px"><Icon name="warn" /><div class="grow small">{{ $t('coverage.partial') }}</div></div>

        <div class="toolbar" style="margin-bottom:10px">
          <label class="input-wrap"><Icon name="search" small /><input v-model="filter.q" class="input" type="search" :placeholder="$t('coverage.searchPh')" data-testid="coverage-q"></label>
          <select v-model="filter.domain" class="select" :aria-label="$t('coverage.domain')" data-testid="coverage-domain">
            <option value="">{{ $t('coverage.allDomains') }}</option>
            <option v-for="d in domains" :key="d" :value="d">{{ d }}</option>
          </select>
          <select v-model="filter.cred" class="select" :aria-label="$t('coverage.cred')" data-testid="coverage-cred">
            <option value="">{{ $t('coverage.anyCred') }}</option>
            <option value="draft">{{ $t('coverage.hasDraft') }}</option>
            <option value="reviewed">{{ $t('coverage.hasReviewed') }}</option>
            <option value="verified">{{ $t('coverage.allVerified') }}</option>
          </select>
          <label class="check"><span class="switch"><input v-model="filter.gapsOnly" type="checkbox" data-testid="coverage-gaps"><span></span></span><span>{{ $t('coverage.gapsOnly') }}</span></label>
          <label class="check"><span class="switch"><input v-model="filter.diffOnly" type="checkbox" data-testid="coverage-diff"><span></span></span><span>{{ $t('coverage.diffOnly') }}</span></label>
          <label class="check"><input v-model="filter.showDeprecated" type="checkbox" data-testid="coverage-deprecated"><span>{{ $t('coverage.showDeprecated') }}</span></label>
          <span class="grow"></span>
          <span class="legend">
            <span><span class="cell sup">verified</span></span>
            <span><span class="cell sup reviewed">reviewed</span></span>
            <span><span class="cell sup draft">draft</span></span>
            <span><span class="cell sup inh">{{ $t('src.inherited') }}</span></span>
            <span><span class="cell uns">{{ $t('st.unsupported') }}</span></span>
            <span><span class="cell unf">{{ $t('st.unfilled') }}</span></span>
          </span>
        </div>

        <div class="panel cov-wrap">
          <table v-if="groups.length" class="cov" data-testid="coverage-table">
            <thead><tr>
              <th class="c-node">{{ $t('coverage.node') }}</th>
              <th>{{ $t('coverage.type') }}</th>
              <th v-for="pid in pids" :key="pid" class="c-p">
                <router-link class="ph-prof" :to="{ name: 'profiles', query: { profile: pid } }">
                  <span class="vendor">
                    <i :class="vendorBadge(profiles[pid]?.vendor ?? '').cls">{{ vendorBadge(profiles[pid]?.vendor ?? '').text }}</i>
                    <span class="pid">{{ shortId(pid) }}</span>
                  </span>
                  <span class="inh">{{ profiles[pid]?.inherits ? $t('coverage.inherits', { p: shortId(profiles[pid].inherits!) }) : profiles[pid]?.software }}</span>
                  <div class="meter"><div class="bar"><i :style="{ width: profCov(pid) + '%' }"></i></div><span class="val">{{ profCov(pid) }}%</span></div>
                </router-link>
              </th>
              <th>{{ $t('coverage.notes') }}</th>
            </tr></thead>
            <tbody v-for="g in groups" :key="g.domain">
              <tr :class="['grp', { closed: closed[g.domain] }]" :data-testid="`coverage-group-${g.domain}`" @click="closed[g.domain] = !closed[g.domain]">
                <td class="c-node">
                  <span class="chev"><Icon name="chevD" small /></span> {{ g.domain }}
                  <span class="faint" style="font-weight:400">{{ domLabel(g.domain) !== g.domain ? domLabel(g.domain) + ', ' : '' }}{{ g.rows.length }}</span>
                </td>
                <td></td>
                <td v-for="pid in pids" :key="pid" class="c-p">
                  <span class="grp-meter">
                    <span class="bar"><i :style="{ width: domainStats(rows, g.domain, pid).pct + '%' }"></i></span>{{ domainStats(rows, g.domain, pid).pct }}%
                    <span v-if="domainStats(rows, g.domain, pid).gaps" class="tag warn gap-tag">{{ $t('coverage.gapN', { n: domainStats(rows, g.domain, pid).gaps }) }}</span>
                  </span>
                </td>
                <td></td>
              </tr>
              <template v-if="!closed[g.domain]">
                <tr v-for="r in g.rows" :key="r.node" :class="{ gap: r.gap, dep: r.deprecated }">
                  <td class="c-node" :title="nodeTitle(r)">
                    <div><span class="pre">{{ r.node.includes('.') ? r.node.slice(0, r.node.lastIndexOf('.') + 1) : '' }}</span>{{ r.node.slice(r.node.lastIndexOf('.') + 1) }}</div>
                    <div v-if="formOf(r)" class="cform" data-testid="coverage-form">{{ formOf(r) }}</div>
                  </td>
                  <td class="c-type" :title="r.type">{{ r.type }}</td>
                  <td v-for="pid in pids" :key="pid" class="c-p">
                    <router-link :to="{ name: 'profiles', query: { profile: pid, node: r.node } }" class="cell-link">
                      <span v-if="r.cells[pid].state === 'unsupported'" class="cell uns">{{ $t('st.unsupported') }}</span>
                      <span v-else-if="r.cells[pid].state === 'unfilled'" class="cell unf"><Icon name="warn" />{{ $t('st.unfilled') }}</span>
                      <span v-else :class="['cell', 'sup', r.cells[pid].cred, { inh: r.cells[pid].inherited }]" :title="cellTitle(r.cells[pid])">
                        <Icon name="check" />{{ r.cells[pid].cred || $t('st.supported') }}<span v-if="r.cells[pid].inherited" class="inhk">{{ $t('coverage.inhShort') }}</span>
                      </span>
                    </router-link>
                  </td>
                  <td class="note">
                    <template v-if="r.deprecated"><span class="tag deprecated" style="text-decoration:none">deprecated</span></template>
                    <template v-else>
                      <span v-if="r.supportDiff" class="tag t-amber">{{ $t('coverage.transWarn') }}</span>
                      <template v-if="r.defaultDiff">
                        <span class="tag t-violet">{{ $t('coverage.defaultsDiffer') }}</span>
                        <div class="mono small">{{ r.defaultDiff.map((d) => `${d.vendor}: ${d.value}`).join(' / ') }}</div>
                      </template>
                    </template>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          <div v-else class="empty" data-testid="coverage-empty">
            <h3>{{ $t('coverage.noMatch') }}</h3>
            <p>{{ $t('coverage.noMatchHint') }}</p>
            <button v-if="filtering" class="btn btn-sm" @click="clearFilters">{{ $t('coverage.clear') }}</button>
          </div>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.cov-wrap { flex: 1; min-height: 0; overflow: auto; }
.cov { border-collapse: separate; border-spacing: 0; width: 100%; min-width: 900px; }
.cov th, .cov td { border-bottom: 1px solid var(--line); padding: 3px 10px; text-align: left; vertical-align: middle; background: var(--surface); }
.cov thead th { position: sticky; top: 0; z-index: 3; background: var(--surface-2); font-weight: 600; font-size: 12px; color: var(--ink-2); vertical-align: bottom; padding: 8px 10px; }
.cov .c-node { position: sticky; left: 0; z-index: 2; min-width: 250px; max-width: 320px; border-right: 1px solid var(--line); }
.cov thead .c-node { z-index: 4; }
.cov td.c-node { font: 12px var(--font-mono); white-space: nowrap; }
.cov td.c-node .pre { color: var(--ink-3); }
.cov td.c-node .cform { font-size: 10.5px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; max-width: 300px; }
.cov tr.dep td.c-node .cform { text-decoration: none; }
.cov td.c-type { font: 11.5px var(--font-mono); color: var(--ink-3); white-space: nowrap; max-width: 116px; overflow: hidden; text-overflow: ellipsis; }
.cov .c-p { min-width: 128px; width: 136px; }
.cov tbody tr:hover td { background: var(--surface-2); }
.cov tr.gap td.c-node { box-shadow: inset 3px 0 0 var(--amber); }
.cov tr.dep td { color: var(--ink-3); }
.cov tr.dep td.c-node { text-decoration: line-through; }
.cov tr.grp td { background: var(--surface-3); font-weight: 600; cursor: pointer; padding-top: 6px; padding-bottom: 6px; }
.cov tr.grp td.c-node { font: 600 12.5px var(--font-ui); }
.cov tr.grp:hover td { background: var(--surface-3); }
.ph-prof { display: flex; flex-direction: column; gap: 4px; color: inherit; text-decoration: none; }
.ph-prof:hover .pid { color: var(--teal-ink); }
.ph-prof .pid { font: 600 11.5px var(--font-mono); color: var(--ink); white-space: nowrap; }
.ph-prof .inh { font-weight: 400; font-size: 11px; color: var(--ink-3); white-space: nowrap; }
.ph-prof .meter { min-width: 0; }
.cell-link { text-decoration: none; }
.cell { display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 7px; border-radius: 4px; font-size: 11.5px; white-space: nowrap; border: 1px solid transparent; }
.cell.sup { color: var(--teal-ink); background: var(--teal-soft); border-color: var(--teal-line); }
.cell.sup.draft { color: var(--amber-ink); background: var(--amber-soft); border-color: var(--amber-line); }
.cell.sup.reviewed { color: var(--blue-ink); background: var(--blue-soft); border-color: var(--blue-line); }
.cell.sup.inh { background: transparent; border-style: dashed; border-color: var(--line-strong); color: var(--ink-2); }
.cell.uns { color: var(--ink-3); background: var(--surface-3); }
.cell.unf { color: var(--amber-ink); border: 1.5px dashed var(--amber); background: transparent; font-weight: 600; }
.cell :deep(.ico) { width: 12px; height: 12px; }
.cell .inhk { font-size: 10.5px; opacity: .8; }
.note { font-size: 11.5px; color: var(--ink-2); min-width: 130px; line-height: 1.9; }
.note .tag { height: 18px; font-size: 11px; }
.grp-meter { white-space: nowrap; display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 11.5px; color: var(--ink-2); }
.grp-meter .bar { width: 44px; flex: none; height: 5px; background: var(--surface); border-radius: 3px; overflow: hidden; }
.grp-meter .bar i { display: block; height: 100%; background: var(--teal); }
.gap-tag { height: 16px; font-size: 10.5px; padding: 0 5px; }
.sumrow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; border: 1px solid var(--line); border-radius: var(--r-panel); background: var(--surface); margin-bottom: 12px; }
.sumrow > div { padding: 10px 14px; border-left: 1px solid var(--line); min-width: 0; }
.sumrow > div:first-child { border-left: 0; }
.sumrow .k { font-size: 12px; color: var(--ink-2); }
.sumrow .v { font: 600 18px/1.3 var(--font-display); }
.sumrow .v small { font: 400 12px var(--font-ui); color: var(--ink-3); margin-left: 4px; }
.chev { transition: transform .15s; display: inline-block; }
tr.grp.closed .chev { transform: rotate(-90deg); }
@media (max-width: 1100px) { .sumrow { grid-template-columns: repeat(2, minmax(0, 1fr)); } .sumrow > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--line); } .sumrow > div:nth-child(4) { border-top: 1px solid var(--line); } }
</style>
