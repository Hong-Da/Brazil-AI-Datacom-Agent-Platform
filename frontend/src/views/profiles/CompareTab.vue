<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import { pickLang } from '@/i18n'
import { compareCsv, compareSummary, filterCompare, warnOf } from './compare'
import { saveText } from './csv'
import { formatDefault } from './format'
import type { CompareResult, EntryState, ProfileRow } from './types'

const props = defineProps<{ profiles: ProfileRow[]; initial?: string }>()
const { t, locale } = useI18n()

function pickB(a: string): string {
  const va = props.profiles.find((p) => p.id === a)?.vendor
  return (props.profiles.find((p) => p.vendor !== va) ?? props.profiles.find((p) => p.id !== a) ?? props.profiles[0])?.id ?? ''
}
const a = ref(props.profiles.some((p) => p.id === props.initial) ? props.initial! : props.profiles[0]?.id ?? '')
const b = ref(pickB(a.value))
const onlyDiff = ref(true)
const q = ref('')
const data = ref<CompareResult | null>(null)
const loading = ref(false)
const err = ref('')

async function load() {
  if (!a.value || !b.value) return
  loading.value = true
  err.value = ''
  try {
    data.value = await get<CompareResult>(`/kb/profile-compare?a=${encodeURIComponent(a.value)}&b=${encodeURIComponent(b.value)}`)
  } catch (e) {
    err.value = errorText(e)
  } finally {
    loading.value = false
  }
}
watch([a, b], load, { immediate: true })

const rows = computed(() => (data.value ? filterCompare(data.value.rows, onlyDiff.value, q.value) : []))
const sum = computed(() => (data.value ? compareSummary(data.value) : null))

function stateText(s: EntryState): string {
  return s === 'supported' ? t('st.supported') : s === 'unsupported' ? t('st.unsupported') : t('st.unfilled')
}
function exportCsv() {
  if (!data.value) return
  saveText(`profile-diff_${data.value.a}_vs_${data.value.b}.csv`, compareCsv(data.value, rows.value))
}
</script>

<template>
  <section data-testid="compare-tab">
    <div class="toolbar" style="margin-bottom:14px">
      <select v-model="a" class="select mono cmp-sel" data-testid="compare-a">
        <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
      </select>
      <span class="faint">{{ $t('profiles.vs') }}</span>
      <select v-model="b" class="select mono cmp-sel" data-testid="compare-b">
        <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
      </select>
      <span class="divider"></span>
      <label class="input-wrap"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('profiles.filterPh')" data-testid="compare-q"></label>
      <label class="check"><input v-model="onlyDiff" type="checkbox" data-testid="compare-only-diff"><span>{{ $t('profiles.onlyDiff') }}</span></label>
      <span class="grow"></span>
      <button class="btn btn-sm" :disabled="!data || !rows.length" data-testid="compare-export" @click="exportCsv">
        <Icon name="download" small />{{ $t('profiles.exportDiff') }}
      </button>
    </div>

    <div v-if="err" class="notice err" style="margin-bottom:14px">
      <Icon name="err" /><div class="grow small">{{ err }}</div>
      <button class="btn btn-xs" @click="load">{{ $t('c.retry') }}</button>
    </div>

    <template v-if="sum">
      <div class="cmp-sum" data-testid="compare-summary">
        <div><div class="v">{{ sum.total }}</div><div class="k">{{ $t('profiles.cmpTotal') }}</div></div>
        <div><div class="v" style="color:var(--red-ink)">{{ sum.support }}</div><div class="k">{{ $t('profiles.cmpSupport') }}</div></div>
        <div><div class="v" style="color:var(--amber-ink)">{{ sum.default }}</div><div class="k">{{ $t('profiles.cmpDefault') }}</div></div>
        <div><div class="v">{{ sum.unfilled }}</div><div class="k">{{ $t('profiles.cmpUnfilled') }}</div></div>
        <div><div class="v">{{ sum.same }}</div><div class="k">{{ $t('profiles.cmpSame') }}</div></div>
      </div>
      <div class="notice info" style="margin-bottom:14px"><Icon name="info" /><div class="grow small">{{ $t('profiles.cmpNotice') }}</div></div>
    </template>

    <div class="panel">
      <div class="tbl-wrap">
        <table class="tbl cmp-tbl" data-testid="compare-table">
          <thead><tr>
            <th>{{ $t('profiles.schemaNode') }}</th>
            <th class="mono">{{ data?.a || a }}</th>
            <th class="mono">{{ data?.b || b }}</th>
            <th>{{ $t('profiles.transWarn') }}</th>
          </tr></thead>
          <tbody>
            <tr v-if="loading && !data"><td colspan="4"><div class="empty"><p>{{ $t('c.loading') }}</p></div></td></tr>
            <tr v-else-if="data && !rows.length"><td colspan="4"><div class="empty"><p>{{ onlyDiff ? $t('profiles.cmpNoDiff') : $t('profiles.noMatch') }}</p></div></td></tr>
            <tr v-for="r in rows" :key="r.node" :class="{ 'd-support': warnOf(r.kind) === 'unsupported', 'd-default': r.kind === 'default' }">
              <td>
                <div class="mono">{{ r.node }}</div>
                <div class="small faint">{{ pickLang(r.semantic, String(locale)) }}</div>
              </td>
              <td v-for="(s, i) in [r.a, r.b]" :key="i" :class="['side', { dv: r.kind === 'default' }]">
                <span :class="['supmark', s.state === 'supported' ? 'yes' : s.state === 'unsupported' ? 'no' : 'na']">
                  <Icon :name="s.state === 'supported' ? 'check' : s.state === 'unsupported' ? 'x' : 'minus'" small />{{ stateText(s.state) }}
                </span>
                <span v-if="s.state === 'supported' && formatDefault(s.default)" class="mono small" style="margin-left:6px">{{ formatDefault(s.default) }}</span>
              </td>
              <td>
                <span v-if="warnOf(r.kind) === 'unsupported'" class="tag t-red">{{ $t('profiles.warnUnsupported') }}</span>
                <span v-else-if="r.kind === 'default'" class="tag t-amber">{{ $t('profiles.warnDefault') }}</span>
                <span v-else-if="r.kind === 'unfilled'" class="tag unfilled">{{ $t('profiles.warnGap') }}</span>
                <span v-else class="faint small">{{ $t('c.none') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cmp-sel { width: 260px; max-width: 100%; }
.cmp-tbl td { vertical-align: top; }
.cmp-tbl tr.d-support td.side { background: color-mix(in srgb, var(--red-soft) 70%, transparent); }
.cmp-tbl tr.d-default td.dv { background: color-mix(in srgb, var(--amber-soft) 80%, transparent); }
.cmp-sum { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--r-panel); background: var(--surface); margin-bottom: 14px; }
.cmp-sum > div { padding: 10px 14px; border-left: 1px solid var(--line); }
.cmp-sum > div:first-child { border-left: 0; }
.cmp-sum .v { font: 600 18px var(--font-display); }
.cmp-sum .k { font-size: 12px; color: var(--ink-2); }
.supmark { font-size: 12px; display: inline-flex; gap: 4px; align-items: center; }
.supmark.no { color: var(--red-ink); }
.supmark.yes { color: var(--teal-ink); }
.supmark.na { color: var(--ink-3); }
@media (max-width: 900px) { .cmp-sum { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
