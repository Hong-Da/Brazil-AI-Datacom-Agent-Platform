<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get, post, waitTask } from '@/api'
import { useStatus } from '@/stores/status'
import { fmtTime, type Device } from './devices/logic'
import {
  diffLines, filterRt, pct, profileView, rtState, sampleName,
  type ProfileRow, type Regression, type RtResult,
} from './dashboard/logic'

const status = useStatus()
const { t, te } = useI18n()
const summary = computed(() => status.summary)
const loading = ref(true)
const loadError = ref('')
const profiles = ref<ProfileRow[]>([])

const regression = computed(() => (summary.value?.regression ?? null) as Regression | null)
const recent = computed(() => ((summary.value?.devices.recent ?? []) as Device[]).slice(0, 5))
const firstUse = computed(() => !!summary.value && summary.value.devices.count === 0 && !regression.value)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    await status.refresh()
    if (!status.summary) await get('/summary') // 外壳的 refresh 会吞掉错误；取不到时再请求一次以拿到错误文字
    profiles.value = (await get<{ profiles: ProfileRow[] }>('/kb/profiles')).profiles
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ---- 往返测试
const rtFilter = ref<'' | 'fail'>('')
const open = ref<Set<string>>(new Set())
const rtRows = computed(() => filterRt(regression.value?.results ?? [], rtFilter.value))
const rtStale = computed(() => !!regression.value && !!summary.value && regression.value.kb_version !== summary.value.kb.version)
const rtPassed = computed(() => (regression.value ? regression.value.results.filter((r) => rtState(r) === 'pass').length : 0))
const rtBad = computed(() => (regression.value ? regression.value.results.length - rtPassed.value : 0))
function toggle(file: string): void {
  const s = new Set(open.value)
  if (s.has(file)) s.delete(file)
  else s.add(file)
  open.value = s
}

const running = ref(false)
const runProgress = ref(0)
const runError = ref('')
async function runAll(): Promise<void> {
  running.value = true
  runProgress.value = 0
  runError.value = ''
  try {
    const { task_id } = await post<{ task_id: string }>('/roundtrip', { samples: true })
    const t = await waitTask<Regression>(task_id, (x) => { runProgress.value = x.progress })
    if (t.status === 'failed') runError.value = t.message
    await status.refresh()
    open.value = new Set((regression.value?.results ?? []).filter((r) => rtState(r) === 'diff').map((r) => r.file))
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
  }
}

function resultClass(r: RtResult): string {
  const s = rtState(r)
  return s === 'pass' ? 'pass' : s === 'unknown' ? 'warn' : 'fail'
}

// ---- 概况数字
const reviewKinds = computed(() => Object.entries(summary.value?.review.by_kind ?? {}).filter(([, n]) => n > 0))
function kindLabel(k: string): string {
  return te(`dashboard.kind.${k}`) ? t(`dashboard.kind.${k}`) : k
}
const profileList = computed(() => profiles.value.map(profileView))
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('dashboard.title') }}</h1>
          <p class="ph-sub">{{ $t('dashboard.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" :disabled="running" data-testid="run-roundtrips" @click="runAll">
            <Icon name="play" small /><span>{{ running ? $t('c.running') : $t('dashboard.runAll') }}</span>
          </button>
          <router-link class="btn btn-primary" :to="{ name: 'devices', query: { import: '1' } }" data-testid="import-configs">
            <Icon name="upload" small /><span>{{ $t('dashboard.import') }}</span>
          </router-link>
        </div>
      </div>

      <div v-if="loading && !summary" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>

      <div v-else-if="loadError && !summary" class="notice err" data-testid="load-error">
        <Icon name="err" /><div class="grow">{{ loadError }}</div>
        <button class="btn btn-sm" @click="load">{{ $t('c.retry') }}</button>
      </div>

      <section v-else-if="firstUse && summary" class="panel" data-testid="first-use">
        <div class="empty" style="padding: 56px 24px">
          <svg class="art" viewBox="0 0 120 84" aria-hidden="true">
            <path d="M20 62 60 76 100 62 60 48z" fill="none" stroke="var(--blue)" stroke-width="2" />
            <path d="M20 46 60 60 100 46 60 32z" fill="none" stroke="var(--teal)" stroke-width="2" stroke-dasharray="4 3" />
            <path d="M20 30 60 44 100 30 60 16z" fill="none" stroke="var(--amber)" stroke-width="2" stroke-dasharray="4 3" />
          </svg>
          <h3>{{ $t('dashboard.emptyTitle') }}</h3>
          <p>{{ $t('dashboard.emptyText') }}</p>
          <div class="row mt8">
            <router-link class="btn btn-primary" :to="{ name: 'devices', query: { import: '1' } }"><Icon name="upload" small /><span>{{ $t('dashboard.import') }}</span></router-link>
            <router-link class="btn" :to="{ name: 'ingest' }">{{ $t('dashboard.ingestFirst') }}</router-link>
          </div>
          <p class="small faint mt8">{{ $t('dashboard.bundled', { v: summary.kb.version, n: summary.kb.profiles }) }}</p>
        </div>
      </section>

      <template v-else-if="summary">
        <div v-if="runError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ runError }}</div></div>

        <div class="strip" data-testid="summary-strip">
          <div>
            <div class="k">{{ $t('dashboard.kbVersion') }}</div>
            <div class="v mono">{{ summary.kb.version }}</div>
            <div class="s">
              <router-link v-if="summary.kb.draft_changes" :to="{ name: 'releases' }">{{ $t('kb.draftChanges', { n: summary.kb.draft_changes }) }}</router-link>
              <span v-else>{{ $t('kb.noDraft') }}</span>
            </div>
          </div>
          <div>
            <router-link class="k" :to="{ name: 'profiles' }">Profiles</router-link>
            <div class="v">{{ summary.kb.profiles }} <small>{{ $t('dashboard.avgCoverage', { n: pct(summary.kb.avg_coverage) }) }}</small></div>
            <div class="s">{{ summary.kb.unfilled_profiles ? $t('dashboard.unfilledProfiles', { n: summary.kb.unfilled_profiles }) : $t('dashboard.kbSize', { c: summary.kb.cards, n: summary.kb.nodes }) }}</div>
          </div>
          <div>
            <router-link class="k" :to="{ name: 'review' }">{{ $t('dashboard.reviewQueue') }}</router-link>
            <div class="v" :class="{ amber: summary.review.pending }">{{ summary.review.pending.toLocaleString() }} <small>{{ $t('dashboard.pending') }}</small></div>
            <div class="s">
              <template v-if="reviewKinds.length">
                <span v-for="([k, n], i) in reviewKinds" :key="k">{{ i ? $t('dashboard.sep') : '' }}{{ kindLabel(k) }} {{ n.toLocaleString() }}</span>
              </template>
              <span v-else>{{ $t('dashboard.reviewEmpty') }}</span>
            </div>
          </div>
          <div>
            <router-link class="k" :to="{ name: 'unknown-lines' }">{{ $t('dashboard.unknownLines') }}</router-link>
            <div class="v">{{ summary.unknown.patterns }} <small>{{ $t('dashboard.unknownHits', { n: summary.unknown.total.toLocaleString() }) }}</small></div>
            <div class="s">{{ summary.unknown.patterns ? $t('dashboard.unknownHint') : $t('dashboard.unknownNone') }}</div>
          </div>
          <div>
            <div class="k">{{ $t('dashboard.roundtrip') }}</div>
            <template v-if="regression">
              <div class="v" :class="{ red: rtBad }">{{ rtPassed }} / {{ regression.results.length }} <small>{{ $t('dashboard.identical') }}</small></div>
              <div class="s">
                <span v-if="rtBad">{{ $t('dashboard.rtBad', { n: rtBad }) }}</span>
                <span v-else-if="rtStale">{{ $t('dashboard.rtStale', { v: regression.kb_version }) }}</span>
                <span v-else>{{ $t('dashboard.rtAt', { t: fmtTime(regression.at) }) }}</span>
              </div>
            </template>
            <template v-else>
              <div class="v faint">—</div>
              <div class="s">{{ $t('dashboard.rtNever') }}</div>
            </template>
          </div>
        </div>

        <div class="dash">
          <section class="panel" data-testid="roundtrip-panel">
            <div class="panel-h">
              <h2>{{ $t('dashboard.samples') }}</h2>
              <span class="meta">{{ $t('dashboard.samplesMeta') }}</span>
              <select v-model="rtFilter" class="select" style="width: auto; height: 28px" data-testid="rt-filter">
                <option value="">{{ $t('dashboard.filterAll', { n: regression?.results.length ?? 0 }) }}</option>
                <option value="fail">{{ $t('dashboard.filterFail') }}</option>
              </select>
            </div>
            <div v-if="running" class="panel-b">
              <div class="progress striped"><i :style="{ width: (runProgress || 100) + '%' }" /></div>
            </div>
            <div v-if="!regression" class="empty" data-testid="rt-never">
              <p>{{ $t('dashboard.rtNeverLong') }}</p>
              <button class="btn btn-sm" :disabled="running" @click="runAll"><Icon name="play" small />{{ $t('dashboard.runAll') }}</button>
            </div>
            <div v-else class="rt-wrap">
              <table class="tbl" data-testid="rt-table">
                <thead>
                  <tr>
                    <th style="width: 28px" />
                    <th>{{ $t('dashboard.colSample') }}</th>
                    <th>Profile</th>
                    <th class="num">{{ $t('dashboard.colLines') }}</th>
                    <th class="num">{{ $t('dashboard.colUnknown') }}</th>
                    <th>{{ $t('dashboard.colResult') }}</th>
                    <th>{{ $t('dashboard.colKb') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!rtRows.length"><td colspan="7"><div class="empty"><p>{{ $t('dashboard.noFailures') }}</p></div></td></tr>
                  <template v-for="r in rtRows" :key="r.file">
                    <tr class="rt-row" :class="{ fail: rtState(r) !== 'pass' }">
                      <td>
                        <button v-if="r.diffs?.length" class="twist" :aria-expanded="open.has(r.file)" :aria-label="$t(open.has(r.file) ? 'c.collapse' : 'c.expand')" @click="toggle(r.file)">
                          <Icon :name="open.has(r.file) ? 'chevD' : 'chevR'" small />
                        </button>
                      </td>
                      <td class="mono" :title="r.file">
                        {{ sampleName(r.file) }}
                        <span v-if="!r.gate" class="tag" :title="$t('dashboard.nonGateTip')">{{ $t('dashboard.nonGate') }}</span>
                      </td>
                      <td class="mono faint">{{ r.profile || '—' }}</td>
                      <td class="num">{{ r.lines?.toLocaleString() ?? '—' }}</td>
                      <td class="num"><span :class="{ faint: !r.unknown }">{{ r.unknown ?? '—' }}</span></td>
                      <td>
                        <span class="tag" :class="resultClass(r)">
                          <Icon v-if="rtState(r) === 'pass'" name="check" small />
                          <Icon v-else-if="rtState(r) === 'diff'" name="x" small />
                          {{ rtState(r) === 'pass' ? $t('dashboard.resPass')
                            : rtState(r) === 'diff' ? $t('dashboard.resDiff', { n: r.diffs?.length ?? 0 })
                            : rtState(r) === 'unknown' ? $t('dashboard.resUnknown')
                            : $t('dashboard.resMissing') }}
                        </span>
                      </td>
                      <td class="mono" :class="{ faint: !rtStale }">
                        {{ regression.kb_version }}
                        <span v-if="rtStale" class="tag warn" style="font-family: var(--font-ui)">{{ $t('dashboard.rerun') }}</span>
                      </td>
                    </tr>
                    <tr v-if="r.diffs?.length && open.has(r.file)" class="rt-diff">
                      <td colspan="7">
                        <div class="diffbox">
                          <div class="diffhead">
                            <span class="tag fail">{{ $t('dashboard.diffLine', { n: r.diffs[0]!.line }) }}</span>
                            <span>{{ $t('dashboard.diffCount', { n: r.diffs.length }) }}</span>
                          </div>
                          <div class="code diff">
                            <div v-for="(l, i) in diffLines(r.diffs)" :key="i" class="l" :class="l.kind">
                              <span class="n">{{ l.no ?? '' }}</span><span class="g" /><span class="t"><span v-if="l.ws" class="ws">{{ l.ws }}</span>{{ l.text }}</span>
                            </div>
                          </div>
                          <div class="diffhead" style="border-top: 1px solid var(--line); border-bottom: 0">
                            <Icon name="info" small /><span class="muted">{{ $t('dashboard.diffNote') }}</span>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </section>

          <div class="stack">
            <section class="panel" data-testid="profiles-panel">
              <div class="panel-h"><h2>Profiles</h2><router-link class="small" :to="{ name: 'coverage' }">{{ $t('dashboard.coverageMatrix') }}</router-link></div>
              <div v-if="!profileList.length" class="empty"><p>{{ $t('c.empty') }}</p></div>
              <div v-for="p in profileList" :key="p.id" class="prof">
                <span class="vendor" style="min-width: 0">
                  <i v-if="p.vendor" :class="p.vendor">{{ p.vendor === 'hw' ? 'HW' : 'CS' }}</i>
                  <router-link class="pn" :to="{ name: 'profiles', query: { id: p.id } }" :title="p.id">{{ p.id }}</router-link>
                </span>
                <div v-if="!p.unfilled" class="meter"><div class="bar"><i :style="{ width: p.pct + '%' }" /></div><span class="val">{{ p.pct }}%</span></div>
                <span v-else class="tag unfilled">{{ $t('st.unfilled') }}</span>
                <div v-if="p.inherits" class="pd">{{ $t('dashboard.inherits') }} <span class="mono">{{ p.inherits }}</span></div>
                <div v-if="!p.unfilled" class="pd">
                  <span class="stackbar" style="width: 90px">
                    <i :style="{ width: p.cred.verified + '%', background: 'var(--teal)' }" />
                    <i :style="{ width: p.cred.reviewed + '%', background: 'var(--blue)' }" />
                    <i :style="{ width: p.cred.draft + '%', background: 'var(--amber)' }" />
                  </span>
                  <span>verified {{ p.cred.verified }}%, reviewed {{ p.cred.reviewed }}%, draft {{ p.cred.draft }}%</span>
                </div>
              </div>
            </section>

            <section class="panel">
              <div class="panel-h"><h2>{{ $t('dashboard.quick') }}</h2></div>
              <div class="panel-b qa">
                <router-link :to="{ name: 'devices', query: { import: '1' } }"><Icon name="upload" /><span><span class="qt">{{ $t('dashboard.import') }}</span><br><span class="qd">{{ $t('dashboard.qaImport') }}</span></span></router-link>
                <router-link :to="{ name: 'review' }"><Icon name="inbox" /><span><span class="qt">{{ $t('dashboard.qaReview') }}</span><br><span class="qd">{{ $t('dashboard.qaReviewN', { n: summary.review.pending.toLocaleString() }) }}</span></span></router-link>
                <router-link :to="{ name: 'ingest' }"><Icon name="book" /><span><span class="qt">{{ $t('dashboard.qaIngest') }}</span><br><span class="qd">{{ $t('dashboard.qaIngestD') }}</span></span></router-link>
                <router-link :to="{ name: 'releases' }"><Icon name="tag" /><span><span class="qt">{{ $t('dashboard.qaRelease') }}</span><br><span class="qd">{{ $t('dashboard.qaReleaseD') }}</span></span></router-link>
              </div>
            </section>

            <section class="panel" data-testid="recent-imports">
              <div class="panel-h"><h2>{{ $t('dashboard.recent') }}</h2><router-link class="small" :to="{ name: 'devices' }">{{ $t('dashboard.allDevices', { n: summary.devices.count }) }}</router-link></div>
              <div v-if="!recent.length" class="empty"><p>{{ $t('dashboard.noDevices') }}</p></div>
              <router-link v-for="d in recent" :key="d.id" class="imp" :to="{ name: 'device-graph', params: { id: d.id } }">
                <span :class="d.parsed === false || d.roundtrip === false ? 'st-err' : d.unknown || d.stale ? 'st-warn' : 'st-ok'"><Icon name="file" small /></span>
                <span class="in mono" :title="d.source_name">{{ d.name }}</span>
                <time :title="fmtTime(d.collected_at, true)">{{ fmtTime(d.collected_at) }}</time>
                <span class="id">
                  <span class="mono">{{ d.source_name }}</span> ·
                  <template v-if="d.parsed === false">{{ $t('dashboard.impParseFail') }}</template>
                  <template v-else>
                    {{ $t('dashboard.impLines', { n: (d.lines ?? 0).toLocaleString(), u: d.unknown ?? 0 }) }}{{ $t('dashboard.sep') }}{{ d.roundtrip ? $t('rt.pass') : $t('rt.fail') }}
                  </template>
                </span>
              </router-link>
            </section>
          </div>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.strip .v.amber { color: var(--amber-ink); }
.strip .v.red { color: var(--red-ink); }
.strip a.k:hover { text-decoration: none; color: var(--ink); }
.dash { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr) 360px; margin-top: 14px; align-items: start; }
@media (max-width: 1300px) { .dash { grid-template-columns: minmax(0, 1fr) 320px; } }
@media (max-width: 1100px) { .dash { grid-template-columns: minmax(0, 1fr); } }
.panel-h .meta { flex: 1; }
.rt-wrap { max-height: 600px; overflow: auto; }
.rt-wrap td.mono { white-space: nowrap; }
.rt-row.fail td { background: color-mix(in srgb, var(--red-soft) 55%, transparent); }
.rt-diff td { padding: 0 !important; background: var(--surface) !important; }
.rt-diff .diffbox { margin: 4px 10px 12px 34px; border: 1px solid var(--red-line); border-radius: 6px; overflow: hidden; }
.rt-diff .diffhead { display: flex; gap: 10px; align-items: center; padding: 7px 10px; background: var(--surface-2); border-bottom: 1px solid var(--line); font-size: 12px; flex-wrap: wrap; }
.rt-diff .code { max-height: 360px; }
.twist { width: 18px; height: 18px; border: 0; background: none; color: var(--ink-3); cursor: pointer; padding: 0; display: inline-flex; align-items: center; justify-content: center; }
.twist:hover { color: var(--ink); }
.prof { display: grid; grid-template-columns: minmax(0, 1fr) 96px; gap: 4px 12px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); }
.prof:last-child { border-bottom: 0; }
.prof .meter { min-width: 0; }
.prof .pn { font: 11.5px var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prof .pd { font-size: 11.5px; color: var(--ink-3); grid-column: 1 / -1; display: flex; gap: 8px; align-items: center; }
.qa { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.qa a { display: flex; gap: 10px; align-items: flex-start; padding: 10px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); text-decoration: none; background: var(--surface); }
.qa a:hover { border-color: var(--teal-line); background: var(--teal-soft); text-decoration: none; }
.qa a .ico { color: var(--teal-ink); margin-top: 2px; flex: none; }
.qa .qt { font-weight: 600; font-size: 12.5px; }
.qa .qd { font-size: 11.5px; color: var(--ink-3); }
.imp { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; gap: 2px 10px; padding: 9px 14px; border-bottom: 1px solid var(--line); align-items: start; color: var(--ink); text-decoration: none; }
.imp:hover { background: var(--surface-2); text-decoration: none; }
.imp:last-child { border-bottom: 0; }
.imp .ico { margin-top: 2px; }
.imp .st-ok { color: var(--ink-3); }
.imp .st-warn { color: var(--amber-ink); }
.imp .st-err { color: var(--red-ink); }
.imp .in { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.imp .id { font-size: 11.5px; color: var(--ink-3); grid-column: 2 / 4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.imp time { font-size: 11.5px; color: var(--ink-3); white-space: nowrap; }
</style>
