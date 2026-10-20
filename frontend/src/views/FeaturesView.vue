<script setup lang="ts">
/**
 * 特性能力查询（预览 DevelopDocs/ui-preview/M5/features.html，REQ-023）：搜索特性 / 命令 / Schema 路径 → 一句话结论（由知识库计算，非 AI）
 * → 特性矩阵（行 = Schema 节点，列 = Profile，格子 = 支持情况与默认值）→ 格子详情（命令写法、默认值来源、可信度、继承）；Profile 对比。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import AiEntryButton from '@/components/ai-suggest/AiEntryButton.vue'
import AiSuggestPanel from '@/components/ai-suggest/AiSuggestPanel.vue'
import { featureScope } from '@/components/ai-suggest/logic'
import { errorText, get } from '@/api'
import { pickLang } from '@/i18n'
import { noteText, type Note } from '@/i18n/note'
import { useTerms } from '@/stores/terms'
import { saveText, toCsv } from '@/views/profiles/csv'
import {
  defaultDiffers, defaultPair, diffCsvRows, groupByDomain, kindFor, quickAnswer, showDefault, sortDiff, supOf, supported, synParts,
  type DiffResult, type DiffRow, type Feature, type FeaturesResult, type PCell, type ProfileInfo,
} from './m5/features'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const terms = useTerms()

const DOMAINS = ['interface', 'vrf', 'static-route', 'bgp', 'routing-policy', 'ospf', 'isis', 'bfd', 'mgmt', 'mpls', 'l2vpn', 'acl', 'vrrp', 'qos', 'sr', 'evpn', 'clock']
const EXAMPLES = ['BFD for BGP', 'mtu', 'log-neighbor-changes', 'bgp.peer.bfd', 'label', 'evpn']
const domName = (d: string) => { const k = `features.dom.${d}`; const s = t(k); return s === k ? d : s }
const featName = (f: { node: string; semantic: Record<string, string | undefined> }) => pickLang(f.semantic as Record<string, string>, lang.value) || f.semantic.en || f.node

// ---------------------------------------------------------------- 查询
const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const fam = ref('')
const dom = ref('')
const diffOnly = ref(false)
const includeSame = ref(false)
const res = ref<FeaturesResult | null>(null)
const allProfiles = ref<ProfileInfo[]>([])
const hidden = ref<Set<string>>(new Set())
const error = ref('')
const loading = ref(false)
let seq = 0
async function load(): Promise<void> {
  const my = ++seq
  loading.value = true
  error.value = ''
  const p = new URLSearchParams({ limit: '2000' })
  if (q.value.trim()) p.set('q', q.value.trim())
  if (dom.value) p.set('domain', dom.value)
  if (includeSame.value) p.set('include_same', 'true')
  try {
    const r = await get<FeaturesResult>(`/features?${p}`)
    if (my !== seq) return
    res.value = r
    if (!allProfiles.value.length) {
      // 首次拿到 Profile 列表时定对比的默认两列：不能放在 onMounted 里等首次加载，用户很快输入时首次加载的结果会被丢弃
      allProfiles.value = r.profiles
      ;[pa.value, pb.value] = defaultPair(r.profiles, pa.value, pb.value)
    }
    if (!sel.value || !r.items.some((x) => x.node === sel.value!.node)) sel.value = r.items[0] ? { node: r.items[0].node, pid: visible.value[0]?.id ?? r.profiles[0]?.id } : null
  } catch (e) {
    if (my === seq) { res.value = null; error.value = errorText(e) }
  } finally {
    if (my === seq) loading.value = false
  }
}
let qt = 0
watch(q, () => { window.clearTimeout(qt); qt = window.setTimeout(() => { void load(); void router.replace({ query: { ...route.query, q: q.value || undefined } }) }, 250) })
watch([dom, includeSame], () => { void load() })

const families = computed(() => [...new Set(allProfiles.value.map((p) => p.family))])
const visible = computed(() => allProfiles.value.filter((p) => !hidden.value.has(p.id) && (!fam.value || p.family === fam.value)))
const pids = computed(() => visible.value.map((p) => p.id))
function togglePid(id: string): void {
  const s = new Set(hidden.value)
  if (s.has(id)) s.delete(id)
  else if (allProfiles.value.length - s.size > 1) s.add(id)
  hidden.value = s
}
const rows = computed(() => (res.value?.items ?? []).filter((f) => !diffOnly.value || kindFor(f, pids.value) !== 'same'))
const groups = computed(() => groupByDomain(rows.value, DOMAINS))
const collapsed = ref<Set<string>>(new Set())
function toggleGroup(d: string): void { const s = new Set(collapsed.value); if (s.has(d)) s.delete(d); else s.add(d); collapsed.value = s }
const answer = computed(() => (q.value.trim() && rows.value.length ? quickAnswer(rows.value, visible.value) : null))
const profById = (id: string) => allProfiles.value.find((p) => p.id === id)
const shortId = (id: string) => id.replace(/^(huawei-atn-|cisco-iosxe-asr920-|nokia-sros-)/, '')

// ---------------------------------------------------------------- 详情
const sel = ref<{ node: string; pid: string } | null>(null)
const selF = computed<Feature | null>(() => (sel.value ? res.value?.items.find((x) => x.node === sel.value!.node) ?? null : null))
const selC = computed<PCell | null>(() => (selF.value && sel.value ? selF.value.profiles[sel.value.pid] ?? null : null))
const deps = ref<{ kind: string; from: string; to: string; note?: Note }[]>([])
watch(() => sel.value?.node, async (n) => {
  deps.value = []
  if (!n) return
  try { deps.value = (await get<{ deps: typeof deps.value }>(`/features/detail?node=${encodeURIComponent(n)}`)).deps ?? [] } catch { /* 没有依赖信息 */ }
})
const supWord = (s: string) => t(`features.sup.${s}`)
const fmtRange = (f: Feature) => {
  if (Array.isArray(f.range) && f.range.length === 2) return `${f.range[0]}–${f.range[1]}`
  if (Array.isArray(f.choices)) return (f.choices as unknown[]).join(' / ')
  return ''
}
const cliFor = computed(() => (sel.value ? `lmesh feature --detail ${sel.value.node} --profile ${sel.value.pid} --output json` : ''))
const apiFor = computed(() => (sel.value ? `GET /api/v1/features/detail?node=${sel.value.node}&profile=${sel.value.pid}` : ''))

// ---------------------------------------------------------------- 标签页与对比
const tab = ref<'matrix' | 'compare'>(route.query.tab === 'compare' ? 'compare' : 'matrix')
const pa = ref(typeof route.query.a === 'string' ? route.query.a : '')
const pb = ref(typeof route.query.b === 'string' ? route.query.b : '')
const withSyntax = ref(false)
const ctype = ref('')
const cmp = ref<DiffResult | null>(null)
const cmpError = ref('')
const cmpLoading = ref(false)
async function loadCmp(): Promise<void> {
  if (!pa.value || !pb.value || pa.value === pb.value) { cmp.value = null; return }
  cmpLoading.value = true
  cmpError.value = ''
  const p = new URLSearchParams({ a: pa.value, b: pb.value })
  if (dom.value) p.set('domain', dom.value)
  if (withSyntax.value) p.set('include_same', 'true')
  try { cmp.value = await get<DiffResult>(`/features/diff?${p}`) } catch (e) { cmp.value = null; cmpError.value = errorText(e) } finally { cmpLoading.value = false }
}
watch([pa, pb, withSyntax, dom, tab], () => { if (tab.value === 'compare') void loadCmp() })
watch(tab, (v) => { void router.replace({ query: { ...route.query, tab: v === 'compare' ? 'compare' : undefined } }) })
function swapAB(): void { const x = pa.value; pa.value = pb.value; pb.value = x }
const cmpRows = computed(() => {
  const hit = q.value.trim() && res.value ? new Set(res.value.items.map((x) => x.node)) : null
  const all = (cmp.value?.rows ?? []).filter((r) => (r.kind !== 'same' || r.syntax_differs) && (!hit || hit.has(r.node)))
  return sortDiff(all.filter((r) => !ctype.value || (ctype.value === 'syntax' ? r.kind === 'same' : r.kind === ctype.value)))
})
// ---------- AI 能力对比说明（M8-3）：在对比表里选中一个特性后，解释两家的差异与替代写法（写法由代码与命令卡核对）
const cmpSel = ref<string | null>(null)
const aiFeat = computed(() => (cmpSel.value && pa.value && pb.value && pa.value !== pb.value && cmpRows.value.some((r) => r.node === cmpSel.value) ? { node: cmpSel.value, a: pa.value, b: pb.value } : null))
const aiScope = computed(() => (aiFeat.value ? featureScope(aiFeat.value.node, aiFeat.value.a, aiFeat.value.b) : ''))
const aiPanel = ref<InstanceType<typeof AiSuggestPanel> | null>(null)
const aiOpen = ref(false)
const aiState = ref('loading')
const aiShown = computed(() => aiOpen.value || ['done', 'running', 'empty', 'failed', 'cancelled'].includes(aiState.value))
watch(aiScope, () => { aiOpen.value = false })
async function runAi(): Promise<void> {
  aiOpen.value = true
  await nextTick()
  await aiPanel.value?.start()
}
const syntaxCount = computed(() => (cmp.value?.rows ?? []).filter((r) => r.kind === 'same' && r.syntax_differs).length)
const inheritNote = computed(() => {
  const c = cmp.value
  if (!c) return null
  if (c.a.inherits === c.b.id) return { child: c.a.id, parent: c.b.id }
  if (c.b.inherits === c.a.id) return { child: c.b.id, parent: c.a.id }
  return null
})
const kindName = (k: string) => (k === 'same' ? t('features.k.syntax') : t(`features.k.${k}`))
function dlCsv(): void {
  if (!cmp.value) return
  const head = [t('features.csv.node'), t('features.csv.domain'), t('features.csv.kind'), `A ${t('features.csv.syntax')}`, `A ${t('features.csv.default')}`, `B ${t('features.csv.syntax')}`, `B ${t('features.csv.default')}`]
  const text = toCsv(diffCsvRows(cmpRows.value, head, kindName, (s) => t(`features.sup.${s === 'unsupported' ? 'n' : 'u'}`)))
  saveText(`features-${cmp.value.a.id}_vs_${cmp.value.b.id}.csv`, `﻿${text}`)
}
function cellSide(c: PCell): DiffRow['a'] { return c }

const toast = ref('')
let tt = 0
function copy(s: string): void {
  const ok = () => { toast.value = t('c.copied'); window.clearTimeout(tt); tt = window.setTimeout(() => { toast.value = '' }, 2000) }
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(s).then(ok, ok)
  else ok()
}

onMounted(async () => {
  await load()
  if (tab.value === 'compare') void loadCmp()
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.kb') }}</span><span class="sep">/</span><span>{{ $t('nav.features') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('features.title') }}</h1>
          <p class="ph-sub">{{ $t('features.sub') }}</p>
        </div>
      </div>

      <section class="panel" aria-label="Query">
        <div class="qbar">
          <label class="input-wrap qsearch"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('features.searchPh')" data-testid="feat-search"></label>
          <span class="lbl">{{ $t('features.family') }}</span>
          <select v-model="fam" class="select" data-testid="feat-family"><option value="">{{ $t('features.all') }}</option><option v-for="f in families" :key="f" :value="f">{{ f }}</option></select>
          <span class="lbl">{{ $t('features.domain') }}</span>
          <select v-model="dom" class="select" data-testid="feat-domain"><option value="">{{ $t('features.allDomains') }}</option><option v-for="d in DOMAINS" :key="d" :value="d">{{ domName(d) }}</option></select>
          <label class="check"><span class="switch"><input v-model="diffOnly" type="checkbox" data-testid="feat-diff-only"><span /></span><span>{{ $t('features.diffOnly') }}</span></label>
        </div>
        <div class="pchips">
          <span class="k">Profile</span>
          <label v-for="p in allProfiles" :key="p.id" class="pchip"><input type="checkbox" :checked="!hidden.has(p.id)" @change="togglePid(p.id)"><DevChip :name="p.id" :vendor="p.vendor" /><span v-if="p.inherits" class="inh">↑ {{ shortId(p.inherits) }}</span></label>
        </div>
        <div class="examples">
          <span class="k">{{ $t('features.try') }}</span>
          <button v-for="x in EXAMPLES" :key="x" type="button" class="ex" :aria-pressed="q.toLowerCase() === x.toLowerCase()" @click="q = x">{{ x }}</button>
        </div>
      </section>

      <div v-if="answer" class="qa" data-testid="feat-answer">
        <span class="qi"><Icon name="ok" /></span>
        <div>
          <div class="qt">
            {{ featName(answer.feature) }} <code class="faint">{{ answer.feature.node }}</code>{{ $t('features.ansSup', { n: answer.supported.length, total: answer.total }) }}{{ !answer.defaults.length ? $t('features.ansNoDef') : answer.defaults.length === 1 ? $t('features.ansDef', { v: answer.defaults[0] }) : $t('features.ansDefs', { v: answer.defaults.join(' / ') }) }}
          </div>
          <div class="qrows">
            <span v-for="s in answer.syntaxByFamily" :key="s.family"><DevChip :name="s.pid" :vendor="profById(s.pid)?.vendor" /><code class="mono"><template v-for="(p, k) in synParts(s.syntax)" :key="k"><span :class="p.c">{{ p.s }}</span></template></code></span>
            <span v-for="p in answer.unsupported" :key="`n${p}`"><DevChip :name="p" :vendor="profById(p)?.vendor" /><span class="sup n" /><span class="faint">{{ supWord('n') }}</span></span>
            <span v-for="p in answer.unfilled" :key="`u${p}`"><DevChip :name="p" :vendor="profById(p)?.vendor" /><span class="sup u" /><span class="faint">{{ supWord('u') }}</span></span>
          </div>
          <div v-if="rows.length > 1" class="small faint mt8">{{ $t('features.ansMore', { n: rows.length - 1 }) }}</div>
        </div>
        <span class="src"><Icon name="db" small />{{ $t('features.byKb') }}</span>
      </div>

      <div class="tabs mt12" role="tablist" style="margin-bottom: 0">
        <button type="button" role="tab" :aria-selected="tab === 'matrix'" data-testid="feat-tab-matrix" @click="tab = 'matrix'"><Icon name="matrix" small /><span>{{ $t('features.matrix') }}</span><span class="count">{{ rows.length }}</span></button>
        <button type="button" role="tab" :aria-selected="tab === 'compare'" data-testid="feat-tab-compare" @click="tab = 'compare'"><Icon name="compare" small /><span>{{ $t('features.compare') }}</span></button>
      </div>

      <div v-if="error" class="notice err mt12"><Icon name="err" /><div class="grow">{{ error }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>

      <!-- ===================== 矩阵 ===================== -->
      <div v-if="tab === 'matrix'" class="fw">
        <section class="panel" aria-label="Matrix">
          <div class="fmx" data-testid="feat-matrix">
            <div v-if="loading && !res" class="empty"><p>{{ $t('c.loading') }}</p></div>
            <div v-else-if="res && !rows.length" class="empty" data-testid="feat-empty">
              <Icon name="search" />
              <h3>{{ q ? $t('features.noneFor', { q }) : $t('features.noneDiff') }}</h3>
              <p>{{ $t('features.noneText') }}</p>
              <div class="row wrap" style="justify-content: center"><button v-for="x in EXAMPLES.slice(0, 4)" :key="x" type="button" class="ex" @click="q = x">{{ x }}</button></div>
              <router-link class="btn btn-sm mt8" :to="{ name: 'ingest' }"><Icon name="book" small />{{ $t('features.toIngest') }}</router-link>
            </div>
            <table v-else-if="res">
              <thead>
                <tr>
                  <th>{{ $t('features.colFeature') }}</th>
                  <th v-for="p in visible" :key="p.id" class="pc">
                    <DevChip :name="p.id" :vendor="p.vendor" />
                    <span class="psw">{{ p.software }}</span>
                    <span v-if="p.inherits" class="pin">↑ {{ $t('features.inherits', { p: p.inherits }) }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <template v-for="g in groups" :key="g.domain">
                  <tr class="gh" @click="toggleGroup(g.domain)"><td :colspan="visible.length + 1"><span class="tw"><Icon :name="collapsed.has(g.domain) ? 'chevR' : 'chevD'" small /></span>{{ domName(g.domain) }}<span class="cnt">{{ g.items.length }}</span></td></tr>
                  <template v-if="!collapsed.has(g.domain)">
                    <tr v-for="f in g.items" :key="f.node" :class="{ 'is-diff': kindFor(f, pids) === 'differs' }">
                      <td><div class="fn"><b>{{ featName(f) }}</b><code>{{ f.node }}</code></div></td>
                      <td v-for="p in visible" :key="p.id">
                        <button type="button" class="cellbtn" :class="{ 'is-sel': sel?.node === f.node && sel?.pid === p.id }" :data-testid="`feat-cell-${f.node}-${p.id}`" @click="sel = { node: f.node, pid: p.id }">
                          <span class="sup" :class="supOf(f.profiles[p.id])" :title="supWord(supOf(f.profiles[p.id]))" />
                          <template v-if="supported(f.profiles[p.id])">
                            <span v-if="showDefault(f.profiles[p.id].default) !== ''" class="dval" :class="{ ddiff: defaultDiffers(f, pids, p.id) }">{{ showDefault(f.profiles[p.id].default) }}</span>
                            <span v-else class="dval none">{{ $t('features.noDefault') }}</span>
                          </template>
                          <span v-if="f.profiles[p.id]?.credibility === 'draft' && !f.profiles[p.id]?.inherited" class="tag draft" style="height: 16px; font-size: 10px">draft</span>
                        </button>
                      </td>
                    </tr>
                  </template>
                </template>
              </tbody>
            </table>
            <div v-if="res && !q && res.hidden_same && !includeSame" class="hidden-same" data-testid="feat-hidden-same">{{ $t('features.hiddenSame', { n: res.hidden_same }) }} <button class="link-btn" type="button" @click="includeSame = true">{{ $t('features.showSame') }}</button></div>
            <div v-if="res?.truncated" class="hidden-same">{{ $t('features.truncated', { n: res.items.length, total: res.total }) }}</div>
            <div class="legend">
              <span><span class="sup y" />{{ supWord('y') }}</span>
              <span><span class="sup n" />{{ supWord('n') }}</span>
              <span><span class="sup u" />{{ $t('features.legU') }}</span>
              <span><span class="sup i" />{{ $t('features.legI') }}</span>
              <span><code class="mono" style="color: var(--amber-ink); font-weight: 600">1</code>{{ $t('features.legDef') }}</span>
              <span><b style="color: var(--amber-ink)">≠</b>{{ $t('features.legDiff') }}</span>
            </div>
          </div>
        </section>

        <aside class="panel dp" aria-label="Details" data-testid="feat-detail">
          <template v-if="!selF || !sel">
            <div class="panel-h"><h3>{{ $t('features.details') }}</h3></div>
            <div class="panel-b"><div class="empty"><Icon name="info" /><p>{{ $t('features.pickCell') }}</p></div></div>
          </template>
          <template v-else>
            <div class="panel-h"><h3>{{ featName(selF) }}</h3><span class="sup" :class="supOf(selC ?? undefined)" /><span class="small faint">{{ supWord(supOf(selC ?? undefined)) }}</span></div>
            <div class="panel-b">
              <dl class="kv">
                <dt>{{ $t('features.path') }}</dt><dd><code>{{ selF.node }}</code></dd>
                <dt>{{ $t('features.domain') }}</dt><dd>{{ domName(selF.domain) }}</dd>
                <dt>{{ $t('features.type') }}</dt><dd class="mono">{{ selF.type }}<template v-if="fmtRange(selF)"> · {{ fmtRange(selF) }}</template></dd>
                <dt>Profile</dt><dd><DevChip :name="sel.pid" :vendor="profById(sel.pid)?.vendor" /><div class="small faint">{{ profById(sel.pid)?.software }} · {{ profById(sel.pid)?.platform }}</div></dd>
                <template v-if="selC?.inherited && selC.origin"><dt>{{ $t('features.inheritedFrom') }}</dt><dd><DevChip :name="selC.origin" :vendor="profById(selC.origin)?.vendor" /><div class="small faint">{{ $t('features.inheritedText') }}</div></dd></template>
              </dl>
              <template v-if="selC && supported(selC)">
                <div class="section-t mt16">{{ $t('features.syntax') }}</div>
                <div class="syn"><template v-for="(s, i) in selC.syntax ?? []" :key="i"><template v-if="i">{{ '\n' }}</template><template v-for="(p, k) in synParts(s)" :key="k"><span :class="p.c">{{ p.s }}</span></template></template></div>
                <div v-if="selC.undo?.length" class="small faint mt8">{{ $t('features.undo') }} <code>{{ selC.undo.join(' / ') }}</code></div>
                <div class="row mt8 small" style="flex-wrap: wrap"><span class="faint">{{ $t('features.cards') }}</span><code v-for="c in selC.cards ?? []" :key="c">{{ c }}</code><span v-if="selC.credibility" class="tag" :class="selC.credibility">{{ $t(`cred.${selC.credibility}`) }}</span></div>
                <div v-if="selC.views?.length" class="small faint mt8">{{ $t('features.views') }} {{ selC.views.join(', ') }}</div>
                <div class="section-t mt16">{{ $t('features.defaultT') }}</div>
                <dl class="kv">
                  <dt>{{ $t('features.defaultT') }}</dt><dd><span v-if="showDefault(selC.default) !== ''" class="dv" :data-k="$t('src.default')"><code>{{ showDefault(selC.default) }}</code></span><span v-else class="faint">{{ $t('c.none') }}</span></dd>
                  <dt>{{ $t('features.source') }}</dt><dd class="small">{{ selC.source || $t('features.noSource') }}</dd>
                  <template v-if="selC.when && Object.keys(selC.when).length"><dt>{{ $t('features.when') }}</dt><dd class="small mono">{{ Object.entries(selC.when).map(([k, v]) => `${k} ~ ${v}`).join('; ') }}</dd></template>
                </dl>
                <div v-if="selC.sources?.length" class="small faint mt8">{{ $t('features.docs') }} <span v-for="(s, i) in selC.sources" :key="i" class="mono">{{ s.title ?? '' }}{{ s.file ? ` (${s.file}${s.line ? `:${s.line}` : ''})` : '' }}{{ s.patched ? ` · ${s.patched}` : '' }}{{ i < selC.sources.length - 1 ? '；' : '' }}</span></div>
              </template>
              <div v-else-if="selC?.state === 'unsupported'" class="notice mt12"><Icon name="info" small /><div class="grow small">{{ selC.source || $t('features.unsupNote') }}</div></div>
              <div v-else class="notice warn mt12"><Icon name="warn" small /><div class="grow small">{{ $t('features.unfilledNote') }}</div></div>
              <template v-if="deps.length">
                <div class="section-t mt16">{{ $t('features.deps') }}</div>
                <ul class="deps"><li v-for="(d, i) in deps" :key="i"><span class="tag">{{ d.kind }}</span> <code>{{ d.from }}</code> → <code>{{ d.to }}</code><span v-if="noteText(d.note, lang)" class="faint"> {{ noteText(d.note, lang) }}</span></li></ul>
              </template>
              <div class="section-t mt16">{{ $t('features.others') }}</div>
              <div class="others">
                <button v-for="p in allProfiles" :key="p.id" type="button" :class="{ 'is-cur': p.id === sel.pid }" @click="sel = { node: selF.node, pid: p.id }">
                  <DevChip :name="p.id" :vendor="p.vendor" /><span class="sup" :class="supOf(selF.profiles[p.id])" /><span class="dval">{{ supported(selF.profiles[p.id]) && showDefault(selF.profiles[p.id].default) !== '' ? showDefault(selF.profiles[p.id].default) : '—' }}</span>
                </button>
              </div>
              <div class="row wrap mt12">
                <router-link class="btn btn-sm" :to="{ name: 'schema-view', query: { node: selF.node } }"><Icon name="layers" small />{{ $t('features.toSchema') }}</router-link>
                <router-link class="btn btn-sm" :to="{ name: 'profiles', query: { profile: sel.pid, node: selF.node } }"><Icon name="sliders" small />{{ $t('features.toProfile') }}</router-link>
                <router-link v-if="!selC || selC.state === 'unfilled'" class="btn btn-sm" :to="{ name: 'ingest' }"><Icon name="plus" small />{{ $t('features.addCard') }}</router-link>
              </div>
              <div class="section-t mt16">{{ $t('features.equivalent') }}</div>
              <div class="cmds">
                <div class="cmdline"><span class="pfx">$</span><span class="grow">{{ cliFor }}</span><button class="btn btn-xs btn-ghost" type="button" :aria-label="$t('c.copy')" @click="copy(cliFor)"><Icon name="copy" small /></button></div>
                <div class="cmdline"><span class="pfx">API</span><span class="grow">{{ apiFor }}</span><button class="btn btn-xs btn-ghost" type="button" :aria-label="$t('c.copy')" @click="copy(apiFor)"><Icon name="copy" small /></button></div>
              </div>
            </div>
          </template>
        </aside>
      </div>

      <!-- ===================== 对比 ===================== -->
      <div v-else data-testid="feat-compare">
        <section class="panel mt12" aria-label="Compare">
          <div class="cbar">
            <span class="vm a">A</span><select v-model="pa" class="select" data-testid="feat-cmp-a"><option v-for="p in allProfiles" :key="p.id" :value="p.id">{{ p.id }}</option></select>
            <button class="btn btn-sm btn-icon" type="button" :title="$t('features.swap')" :aria-label="$t('features.swap')" @click="swapAB"><Icon name="swap" small /></button>
            <span class="vm b">B</span><select v-model="pb" class="select" data-testid="feat-cmp-b"><option v-for="p in allProfiles" :key="p.id" :value="p.id">{{ p.id }}</option></select>
            <label class="check"><input v-model="withSyntax" type="checkbox"> <span>{{ $t('features.withSyntax') }}</span></label>
            <span class="ml-auto" />
            <button class="btn btn-sm" type="button" :disabled="!cmpRows.length" data-testid="feat-cmp-csv" @click="dlCsv"><Icon name="download" small /><span>{{ $t('features.csvBtn') }}</span></button>
            <AiEntryButton v-if="aiFeat" :skills="['feature-compare']" :busy="aiState === 'running'" small @run="runAi" />
            <button v-else class="btn btn-sm btn-ai" type="button" disabled :title="$t('ai-suggest.needTwoProfiles')" data-testid="feat-ai-off"><Icon name="spark" small />{{ $t('ai-suggest.btn') }}</button>
          </div>
        </section>
        <div v-if="pa === pb" class="notice warn mt12"><Icon name="warn" small /><div class="grow">{{ $t('features.sameProfile') }}</div></div>
        <div v-else-if="cmpError" class="notice err mt12"><Icon name="err" /><div class="grow">{{ cmpError }}</div><button class="btn btn-sm" type="button" @click="loadCmp">{{ $t('c.retry') }}</button></div>
        <div v-else-if="cmpLoading && !cmp" class="empty"><p>{{ $t('c.loading') }}</p></div>
        <template v-else-if="cmp">
          <div class="cstrip" data-testid="feat-cmp-strip">
            <button type="button" class="static"><div class="v">{{ cmp.counts.same ?? 0 }}</div><div class="k">{{ $t('features.k.same') }}</div></button>
            <button v-for="k in ['default', 'only_a', 'only_b', 'unfilled']" :key="k" type="button" :aria-pressed="ctype === k" @click="ctype = ctype === k ? '' : k"><div class="v" :style="k === 'default' && cmp.counts.default ? 'color: var(--amber-ink)' : ''">{{ cmp.counts[k] ?? 0 }}</div><div class="k">{{ $t(`features.k.${k}`) }}</div></button>
            <button type="button" :class="{ static: !withSyntax }" :aria-pressed="ctype === 'syntax'" :disabled="!withSyntax" @click="ctype = ctype === 'syntax' ? '' : 'syntax'"><div class="v">{{ withSyntax ? syntaxCount : '—' }}</div><div class="k">{{ $t('features.k.syntax') }}</div></button>
          </div>
          <div v-if="inheritNote" class="notice ok mt12"><Icon name="ok" small /><div class="grow"><b>{{ $t('features.inheritTitle', inheritNote) }}</b> {{ cmp.counts.default + cmp.counts.only_a + cmp.counts.only_b === 0 ? $t('features.inheritSame') : $t('features.inheritDiff') }}</div></div>
          <div v-if="aiFeat" v-show="aiShown" class="mt12" data-testid="feat-ai">
            <AiSuggestPanel ref="aiPanel" skill="feature-compare" :params="aiFeat" :scope="aiScope" @state="aiState = $event" />
          </div>
          <section class="panel mt12">
            <div class="panel-h">
              <h3>{{ $t('features.diffs') }}</h3><span class="meta">{{ cmpRows.length }}</span><span v-if="q.trim()" class="small faint">{{ $t('features.cmpFiltered', { q }) }}</span>
              <span v-if="cmp.counts.default" class="small" style="color: var(--amber-ink)">{{ $t('features.defNote') }}</span>
            </div>
            <div v-if="!cmpRows.length" class="panel-b"><div class="empty"><Icon name="ok" /><p>{{ $t('features.noDiffs') }}</p></div></div>
            <div v-else class="tbl-wrap">
              <table class="tbl ctbl" data-testid="feat-cmp-table">
                <thead><tr><th>{{ $t('features.colFeature') }}</th><th><span class="row" style="gap: 6px"><span class="vm a sm">A</span>{{ cmp.a.id }}</span></th><th><span class="row" style="gap: 6px"><span class="vm b sm">B</span>{{ cmp.b.id }}</span></th><th>{{ $t('features.kindCol') }}</th></tr></thead>
                <tbody>
                  <tr v-for="r in cmpRows" :key="r.node" :class="[`t-${r.kind}`, { 'is-sel': cmpSel === r.node }]" data-testid="feat-cmp-row" @click="cmpSel = r.node">
                    <td><div class="fn"><b>{{ featName(r) }}</b><code class="small faint">{{ r.node }}</code></div></td>
                    <td v-for="(c, i) in [cellSide(r.a), cellSide(r.b)]" :key="i">
                      <template v-if="supported(c)">
                        <div class="cmdc"><template v-for="(s, j) in c.syntax ?? []" :key="j"><template v-if="j"> ⏎ </template><template v-for="(p, k) in synParts(s)" :key="k"><span :class="p.c">{{ p.s }}</span></template></template></div>
                        <div class="dl">{{ $t('src.default') }} <code :class="{ dd: r.kind === 'default' }">{{ showDefault(c.default) || '—' }}</code><span v-if="c.inherited" class="sup i" /><span v-if="c.credibility === 'draft'" class="tag draft">draft</span></div>
                      </template>
                      <template v-else><span class="sup" :class="supOf(c)" /> <span class="small faint">{{ supWord(supOf(c)) }}</span><div v-if="c.source" class="dl">{{ c.source }}</div></template>
                    </td>
                    <td><span class="dt" :class="r.kind">{{ kindName(r.kind) }}</span><div v-if="r.kind === 'default'"><router-link class="tr-link" :to="{ name: 'translate' }"><Icon name="swap" small />{{ $t('features.trLink') }}</router-link></div></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="panel-f cfoot">
              <div class="cmds" style="flex: 1">
                <div class="cmdline"><span class="pfx">$</span><span class="grow">lmesh feature-diff {{ cmp.a.id }} {{ cmp.b.id }} --output json</span></div>
                <div class="cmdline"><span class="pfx">API</span><span class="grow">GET /api/v1/features/diff?a={{ cmp.a.id }}&amp;b={{ cmp.b.id }}</span></div>
              </div>
            </div>
          </section>
        </template>
      </div>
    </div>
    <div v-if="toast" class="m5-toast" role="status">{{ toast }}</div>
  </main>
</template>

<style scoped>
.ctbl tbody tr { cursor: pointer; }
.ctbl tbody tr.is-sel td { background: var(--hl-line); }
.qbar { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; padding: 10px 14px; }
.qbar .lbl { font-size: 12px; color: var(--ink-2); }
.qbar .qsearch { flex: 1; min-width: 280px; }
.qbar .select { width: auto; }
.pchips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 0 14px 10px; }
.pchips .k, .examples .k { font-size: 12px; color: var(--ink-3); margin-right: 2px; }
.pchip { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 9px 0 6px; border: 1px solid var(--line-strong); border-radius: 13px; background: var(--surface); cursor: pointer; font-size: 12px; color: var(--ink-2); }
.pchip input { accent-color: var(--teal); margin: 0; }
.pchip:has(input:checked) { border-color: var(--teal-line); background: var(--teal-soft); color: var(--ink); }
.pchip .inh { font-size: 11px; color: var(--ink-3); }
.examples { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 0 14px 12px; }
.ex { border: 1px dashed var(--line-strong); background: transparent; color: var(--ink-2); border-radius: 4px; height: 24px; padding: 0 8px; font: 12px var(--font-mono); cursor: pointer; }
.ex:hover { border-color: var(--blue); color: var(--blue-ink); }
.ex[aria-pressed="true"] { border-style: solid; border-color: var(--amber); background: var(--amber-soft); color: var(--amber-ink); font-weight: 600; }
.qa { margin-top: 12px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 6px 14px; align-items: start; padding: 12px 14px; border: 1px solid var(--teal-line); border-left: 3px solid var(--teal); border-radius: var(--r-panel); background: color-mix(in srgb, var(--teal-soft) 45%, var(--surface)); }
.qa .qi { width: 30px; height: 30px; border-radius: 6px; background: var(--teal-soft); color: var(--teal-ink); display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--teal-line); }
.qa .qt { font: 600 14px var(--font-display); }
.qa .qt code { font-size: 12.5px; }
.qa .qrows { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 6px; font-size: 12.5px; color: var(--ink-2); }
.qa .qrows > span { display: inline-flex; gap: 6px; align-items: center; }
.qa .src { font-size: 11.5px; color: var(--teal-ink); display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.pm { color: var(--teal-ink); }
.op { color: var(--ink-3); }
.fw { display: grid; grid-template-columns: minmax(0, 1fr) 390px; gap: 10px; margin-top: 10px; align-items: start; }
.fmx { overflow: auto; max-height: min(74vh, 860px); }
.fmx table { width: 100%; border-collapse: separate; border-spacing: 0; }
.fmx th { position: sticky; top: 0; z-index: 2; background: var(--surface-2); border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: bottom; font-weight: 600; font-size: 12px; color: var(--ink-2); }
.fmx th.pc { min-width: 130px; max-width: 200px; }
.fmx th.pc .dev { white-space: normal; overflow-wrap: anywhere; }
.fmx th .psw { display: block; font: 400 11px var(--font-mono); color: var(--ink-3); margin-top: 2px; }
.fmx th .pin { display: block; font-weight: 400; font-size: 11px; color: var(--teal-ink); margin-top: 2px; }
.fmx td { border-bottom: 1px solid var(--line); padding: 5px 10px; vertical-align: middle; }
.fmx tr.gh td { background: var(--surface-2); padding: 6px 10px; font-size: 12px; font-weight: 600; color: var(--ink-2); cursor: pointer; }
.fmx tr.gh td .cnt { font-weight: 400; color: var(--ink-3); margin-left: 6px; }
.fmx tr.gh .tw { display: inline-flex; vertical-align: -3px; color: var(--ink-3); margin-right: 4px; }
.fmx .fn { display: flex; flex-direction: column; gap: 1px; min-width: 200px; max-width: 360px; }
.fmx .fn b { font-weight: 600; font-size: 12.5px; }
.fmx .fn code { font-size: 11px; color: var(--ink-3); }
.fmx tr.is-diff .fn b::after { content: "≠"; margin-left: 6px; color: var(--amber-ink); font-weight: 700; }
.cellbtn { display: inline-flex; align-items: center; gap: 7px; border: 1px solid transparent; background: transparent; border-radius: 5px; padding: 3px 6px; cursor: pointer; font: inherit; color: var(--ink); min-height: 28px; width: 100%; text-align: left; }
.cellbtn:hover { background: var(--surface-2); border-color: var(--line); }
.cellbtn.is-sel { background: var(--hl-line); border-color: var(--hl-line-edge); }
.cellbtn .dval { font: 11.5px var(--font-mono); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.cellbtn .dval.none { color: var(--ink-3); font-family: var(--font-ui); }
.cellbtn .ddiff { color: var(--amber-ink); font-weight: 600; }
.hidden-same { padding: 8px 12px; font-size: 12px; color: var(--ink-2); border-top: 1px solid var(--line); }
.legend { padding: 8px 12px; border-top: 1px solid var(--line); position: sticky; bottom: 0; background: var(--surface); display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 11.5px; color: var(--ink-2); }
.legend > span { display: inline-flex; gap: 5px; align-items: center; }
.dp { position: sticky; top: 0; display: flex; flex-direction: column; max-height: min(74vh, 860px); }
.dp .panel-b { overflow: auto; }
.dp .kv dd { min-width: 0; overflow-wrap: anywhere; }
.syn { font: 12px/1.7 var(--font-mono); background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; color: var(--ink); white-space: pre-wrap; word-break: break-word; }
.syn .pm { color: var(--teal-ink); }
.syn .op { color: var(--ink-3); }
.others { display: flex; flex-direction: column; gap: 4px; }
.others button { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; border: 1px solid var(--line); background: var(--surface); border-radius: 5px; padding: 5px 8px; cursor: pointer; font: inherit; color: var(--ink); text-align: left; }
.others button:hover { border-color: var(--blue-line); }
.others button.is-cur { border-color: var(--hl-line-edge); background: var(--hl-line); }
.others .dval { font: 11.5px var(--font-mono); color: var(--ink-2); }
.deps { margin: 0; padding-left: 18px; font-size: 12px; color: var(--ink-2); line-height: 1.8; }
.cmds { display: flex; flex-direction: column; gap: 6px; }
.cmdline .grow { flex: 1; }
.cmdline .btn { flex: none; }
.cbar { display: flex; flex-wrap: wrap; gap: 10px 12px; align-items: center; padding: 10px 14px; }
.cbar .select { width: auto; min-width: 250px; }
.cstrip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-top: 10px; overflow: hidden; }
.cstrip > button { padding: 10px 14px; border: 0; border-left: 1px solid var(--line); background: transparent; text-align: left; font: inherit; color: var(--ink); cursor: pointer; min-width: 0; }
.cstrip > button:first-child { border-left: 0; }
.cstrip > button:hover:not(.static):not(:disabled) { background: var(--surface-2); }
.cstrip > button[aria-pressed="true"] { background: var(--blue-soft); box-shadow: inset 0 -2px 0 var(--blue); }
.cstrip > button.static, .cstrip > button:disabled { cursor: default; }
.cstrip .v { font: 600 21px/1.25 var(--font-display); }
.cstrip .k { font-size: 12px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ctbl td { vertical-align: top; }
.ctbl .fn { display: flex; flex-direction: column; gap: 1px; min-width: 200px; }
.ctbl .fn b { font-weight: 600; }
.ctbl td:last-child { white-space: nowrap; }
.ctbl td .cmdc { font: 11.5px/1.55 var(--font-mono); color: var(--ink); }
.ctbl td .dl { margin-top: 3px; font-size: 11.5px; color: var(--ink-3); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ctbl td .dl code { font-size: 11.5px; color: var(--ink); }
.ctbl tr.t-default td { background: color-mix(in srgb, var(--amber-soft) 50%, transparent); }
.ctbl tr.t-default td:first-child { box-shadow: inset 3px 0 0 var(--amber); }
.ctbl tr.t-default td code.dd { background: var(--amber-soft); border: 1px solid var(--amber-line); color: var(--amber-ink); border-radius: 3px; padding: 0 4px; font-weight: 600; }
.dt { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 4px; font-size: 11.5px; font-weight: 600; border: 1px solid; white-space: nowrap; }
.dt.only_a { color: var(--va); background: var(--blue-soft); border-color: var(--blue-line); }
.dt.only_b { color: var(--amber-ink); background: var(--amber-soft); border-color: var(--amber-line); }
.dt.default { color: var(--amber-ink); background: var(--surface); border-color: var(--amber); }
.dt.same { color: var(--ink-2); background: var(--surface-2); border-color: var(--line); }
.dt.unfilled { color: var(--ink-3); background: transparent; border-color: var(--line-strong); border-style: dashed; }
.cfoot { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.tr-link { font-size: 11.5px; display: inline-flex; gap: 4px; align-items: center; margin-top: 4px; }
@media (max-width: 1400px) { .fw { grid-template-columns: minmax(0, 1fr) 340px; } .cstrip { grid-template-columns: repeat(3, minmax(0, 1fr)); } .cstrip > button { border-top: 1px solid var(--line); } }
@media (max-width: 1000px) { .fw { grid-template-columns: minmax(0, 1fr); } .dp { position: static; max-height: none; } }
</style>
