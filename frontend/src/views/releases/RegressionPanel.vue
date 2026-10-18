<script setup lang="ts">
import { computed, ref } from 'vue'
import { post, waitTask, errorText } from '@/api'
import Icon from '@/components/Icon.vue'
import { fmtTime, samplePassed, sortSamples, type Regression, type SampleResult } from './logic'

const props = defineProps<{ regression: Regression | null; stale: boolean; loading: boolean }>()
const emit = defineEmits<{ updated: [reg: Regression]; running: [on: boolean] }>()

const running = ref(false)
const progress = ref(0)
const runError = ref('')
const open = ref<Set<string>>(new Set())

const rows = computed(() => sortSamples(props.regression?.results ?? []))
const failedAll = computed(() => rows.value.filter((r) => !samplePassed(r)).length)

function toggle(f: string): void {
  const s = new Set(open.value)
  if (s.has(f)) s.delete(f)
  else s.add(f)
  open.value = s
}
function vendor(p?: string): string { return p?.startsWith('cisco') ? 'cs' : p?.startsWith('huawei') ? 'hw' : '' }
function pct(c?: number): string { return c == null ? '—' : `${(c * 100).toFixed(c >= 0.9995 ? 0 : 1)}%` }

async function run(): Promise<void> {
  running.value = true
  emit('running', true)
  progress.value = 0
  runError.value = ''
  try {
    const { task_id } = await post<{ task_id: string }>('/roundtrip', { samples: true })
    const t = await waitTask<Regression>(task_id, (x) => (progress.value = x.progress))
    if (t.status === 'done' && t.result) {
      emit('updated', t.result)
      open.value = new Set(sortSamples(t.result.results).filter((r) => !samplePassed(r) && r.gate !== false).map((r) => r.file).slice(0, 1))
    } else runError.value = t.message || 'failed'
  } catch (e) {
    runError.value = errorText(e)
  } finally {
    running.value = false
    emit('running', false)
  }
}
defineExpose({ run })

function failLabel(r: SampleResult): string {
  if (r.error) return r.error
  return ''
}
</script>

<template>
  <div class="panel" data-testid="regression-panel">
    <div class="panel-h">
      <h2>{{ $t('releases.regTitle') }}</h2>
      <span class="meta">
        <template v-if="running">{{ $t('releases.regRunning', { p: progress }) }}</template>
        <template v-else-if="regression?.at">{{ $t('releases.regAt', { t: fmtTime(regression.at), v: regression.kb_version ?? '—' }) }}</template>
      </span>
      <button class="btn btn-sm" type="button" :disabled="running" data-testid="regression-run" @click="run">
        <Icon name="play" small />{{ regression ? $t('releases.regRerun') : $t('releases.regRun') }}
      </button>
    </div>
    <div class="panel-b" style="padding-bottom: 0">
      <div v-if="running" style="margin-bottom: 12px">
        <div class="progress striped"><i :style="{ width: Math.max(progress, 4) + '%' }" /></div>
        <p class="small faint mt8">{{ $t('releases.regRunningHint') }}</p>
      </div>
      <div v-if="runError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow small">{{ runError }}</div></div>
      <template v-if="!running && regression">
        <div v-if="regression.failed" class="notice err" style="margin-bottom: 12px" data-testid="regression-failed">
          <Icon name="err" /><div class="grow"><b>{{ $t('releases.regFailed', { n: regression.failed, total: regression.samples }) }}</b>
            <div class="small">{{ $t('releases.regFailedHint') }}</div></div>
        </div>
        <div v-else class="notice ok" style="margin-bottom: 12px" data-testid="regression-passed">
          <Icon name="ok" /><div class="grow"><b>{{ $t('releases.regPassed', { n: regression.samples }) }}</b>
            <div v-if="failedAll" class="small">{{ $t('releases.regNonGate', { n: failedAll }) }}</div></div>
        </div>
        <div v-if="stale" class="notice warn" style="margin-bottom: 12px" data-testid="regression-stale">
          <Icon name="warn" /><div class="grow small">{{ $t('releases.regStale') }}</div>
        </div>
      </template>
      <p v-if="!running && !regression && !loading" class="small muted" style="margin-bottom: 12px">{{ $t('releases.regNone') }}</p>
    </div>
    <div v-if="rows.length" class="tbl-wrap" style="max-height: 420px">
      <table class="tbl compact" data-testid="regression-table">
        <thead><tr>
          <th>{{ $t('releases.sample') }}</th>
          <th>Profile</th>
          <th class="num">{{ $t('releases.lines') }}</th>
          <th>{{ $t('releases.roundtrip') }}</th>
          <th class="num">{{ $t('releases.unknown') }}</th>
          <th class="num">{{ $t('releases.coverage') }}</th>
          <th>{{ $t('releases.gate') }}</th>
        </tr></thead>
        <tbody>
          <template v-for="r in rows" :key="r.file">
            <tr :class="{ 'is-sel': !samplePassed(r) && r.gate !== false }">
              <td><span class="vendor"><i v-if="vendor(r.profile)" :class="vendor(r.profile)">{{ vendor(r.profile) === 'cs' ? 'C' : 'HW' }}</i><span class="mono small">{{ r.file }}</span></span></td>
              <td class="mono small nowrap">{{ r.profile ?? '—' }}</td>
              <td class="num">{{ r.lines?.toLocaleString('en-US') ?? '—' }}</td>
              <td>
                <span v-if="r.ok" class="tag pass"><Icon name="check" small />{{ $t('releases.identical') }}</span>
                <button v-else class="tag fail tag-btn" type="button" @click="toggle(r.file)">
                  <Icon name="x" small />{{ failLabel(r) || $t('releases.differs', { n: r.diffs?.length ?? 0 }) }}
                </button>
              </td>
              <td class="num"><span :class="{ 'unk-n': (r.unknown ?? 0) > 0 }">{{ r.unknown ?? '—' }}</span></td>
              <td class="num">{{ pct(r.coverage) }}</td>
              <td><span :class="['tag', r.gate === false ? '' : 't-teal']">{{ r.gate === false ? $t('releases.gateNo') : $t('releases.gateYes') }}</span></td>
            </tr>
            <tr v-if="!r.ok && open.has(r.file) && r.diffs?.length" class="fail-detail">
              <td colspan="7"><div class="inner">
                <div v-for="(d, i) in r.diffs" :key="i" class="code diff" style="margin-bottom: 8px">
                  <div v-for="(l, j) in d.original" :key="'o' + j" class="l del"><span class="n">{{ d.line + j }}</span><span class="g" /><span class="t">{{ l }}</span></div>
                  <div v-for="(l, j) in d.rendered" :key="'r' + j" class="l add"><span class="n" /><span class="g" /><span class="t">{{ l }}</span></div>
                </div>
                <p class="small faint">{{ $t('releases.diffLegend') }}</p>
              </div></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.fail-detail td { background: var(--surface-2) !important; padding: 0 !important; }
.fail-detail .inner { padding: 10px 12px 12px; }
.diff { border: 1px solid var(--line); border-radius: 6px; overflow: auto; }
.tag-btn { cursor: pointer; border: 0; font-family: inherit; }
.unk-n { color: var(--red-ink); font-weight: 600; }
.tbl td.mono, .tbl td.small.mono { white-space: nowrap; }
</style>
