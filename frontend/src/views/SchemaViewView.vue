<script setup lang="ts">
/** Schema 视图：Schema 全集按功能域分栏显示；按单个 Profile 着色，或对比两个 Profile；可显示依赖边。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { get, errorText } from '@/api'
import { pickLang } from '@/i18n'
import { stripVendor } from '@/vendor'
import { noteText } from '@/i18n/note'
import Icon from '@/components/Icon.vue'
import {
  allDeps, allNodes, buildTree, compareGroups, coverageOf, credibilityCounts, depApplies, depStyle, edgesOf, fmtValue,
  EDGE_STYLES, type CompareData, type CompareRow, type CoverageData, type EntryState, type ProfileDetail,
  type ProfileEntry, type ProfileRow, type SchemaData, type SchemaNode,
} from './schema/model'
import { edgePath, fitText, layoutGroups, PH, type PillPos } from './schema/layout'
import StyleForms from './schema/StyleForms.vue'
import { styleForm } from './schema/styles'
import { useTerms } from '@/stores/terms'
import { useAuth } from '@/stores/auth'
import KbRoRibbon from '@/components/kb-ro-ribbon.vue'
import KbSuggest from '@/components/kb-suggest.vue'
import type { SuggestKind } from '@/views/kbsugg/logic'
import VendorBadge from '@/components/vendor-badge.vue'

type Mode = 'one' | 'cmp' | 'all'

const { t, locale } = useI18n()
const route = useRoute()
const terms = useTerms()
const auth = useAuth()
// 普通用户只读，可以提建议（REQ-036）
const suggest = ref<{ target: string; current: string; kind: SuggestKind } | null>(null)
const ribbon = ref<InstanceType<typeof KbRoRibbon> | null>(null)
const sent = ref('')
function onSuggested(): void {
  suggest.value = null
  sent.value = t('kbsugg.submitted')
  void ribbon.value?.reload()
  setTimeout(() => { sent.value = '' }, 4000)
}

const loading = ref(true)
const error = ref('')
const schema = ref<SchemaData | null>(null)
const profiles = ref<ProfileRow[]>([])
const coverage = ref<CoverageData | null>(null)
const details = reactive<Record<string, Map<string, ProfileEntry>>>({})
const cmp = ref<CompareData | null>(null)
const cmpError = ref('')

const q0 = route.query
const mode = ref<Mode>(q0.mode === 'cmp' || q0.mode === 'all' ? q0.mode : 'one')
const pa = ref('')
const pb = ref('')
const sel = ref<string | null>(typeof q0.node === 'string' ? q0.node : null)
const q = ref('')
const onlyDiff = ref(false)
const showEdges = ref(true)
const gview = ref<HTMLElement | null>(null)

const domains = computed(() => schema.value?.domains ?? [])
const nodes = computed(() => allNodes(domains.value))
const deps = computed(() => allDeps(domains.value))
const byId = computed(() => new Map(nodes.value.map((n) => [n.id, n])))
const deprecated = computed(() => new Set(nodes.value.filter((n) => n.deprecated).map((n) => n.id)))
const groups = computed(() => buildTree(domains.value))
const layout = computed(() => layoutGroups(groups.value))
const profileById = computed(() => new Map(profiles.value.map((p) => [p.id, p])))
const cmpRows = computed(() => new Map((cmp.value?.rows ?? []).map((r) => [r.node, r])))
const lang = computed(() => String(locale.value))

function sem(n: { semantic: Record<string, string> } | undefined): string {
  return n ? pickLang(n.semantic, lang.value) : ''
}
function domName(d: string): string {
  const k = `schema-view.dom.${d}`
  const v = t(k)
  return v === k ? d : v
}
function stateOf(id: string, pid: string): EntryState {
  return coverage.value?.matrix[id]?.[pid] ?? 'unfilled'
}
function entryOf(id: string, pid: string): ProfileEntry | undefined {
  return details[pid]?.get(id)
}
function differs(id: string): boolean {
  const r = cmpRows.value.get(id)
  return !!r && r.kind !== 'same'
}

/* ---------------- 数据加载 ---------------- */
async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [s, p, c] = await Promise.all([
      get<SchemaData>('/kb/schema'),
      get<{ profiles: ProfileRow[] }>('/kb/profiles'),
      get<CoverageData>('/kb/coverage'),
    ])
    schema.value = s
    profiles.value = p.profiles
    coverage.value = c
    const ids = p.profiles.map((x) => x.id)
    const qa = typeof q0.a === 'string' && ids.includes(q0.a) ? q0.a : ''
    const qb = typeof q0.b === 'string' && ids.includes(q0.b) ? q0.b : ''
    if (!ids.includes(pa.value)) pa.value = qa || ids[0] || ''
    if (!ids.includes(pb.value)) pb.value = qb || ids.find((x) => x !== pa.value) || ids[0] || ''
    if (!ids.length) mode.value = 'all'
    for (const k of Object.keys(details)) delete details[k]
    // 各 Profile 的条目（可信度、继承、默认值）后台加载，用于着色和节点卡片
    for (const id of ids) void loadDetail(id)
    if (mode.value === 'cmp') void loadCompare()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function loadDetail(pid: string): Promise<void> {
  if (!pid || details[pid]) return
  try {
    const d = await get<ProfileDetail>(`/kb/profiles/${encodeURIComponent(pid)}`)
    details[pid] = new Map(d.entries.map((e) => [e.node, e]))
  } catch { /* 取不到时只按覆盖矩阵着色，不显示可信度 */ }
}

let cmpSeq = 0
async function loadCompare(): Promise<void> {
  if (!pa.value || !pb.value) return
  const seq = ++cmpSeq
  cmpError.value = ''
  try {
    const d = await get<CompareData>(`/kb/profile-compare?a=${encodeURIComponent(pa.value)}&b=${encodeURIComponent(pb.value)}`)
    if (seq === cmpSeq) cmp.value = d
  } catch (e) {
    if (seq === cmpSeq) { cmp.value = null; cmpError.value = errorText(e) }
  }
}

watch([mode, pa, pb], () => { if (mode.value === 'cmp') void loadCompare() })
onMounted(load)

/* ---------------- 图 ---------------- */
function pillClass(p: PillPos): string[] {
  const n = p.item.node
  const c = ['pill']
  if (n.type === 'object') c.push('obj')
  if (n.deprecated) c.push('dep')
  if (mode.value === 'one' && !n.deprecated && pa.value) {
    const st = stateOf(n.id, pa.value)
    if (st === 'unsupported') c.push('uns')
    else if (st === 'unfilled') c.push('unf')
  }
  if (mode.value === 'cmp' && !n.deprecated && differs(n.id)) c.push('diff')
  if (mode.value === 'cmp' && onlyDiff.value && !differs(n.id)) c.push('dim')
  const s = q.value.trim().toLowerCase()
  if (s && !n.id.toLowerCase().includes(s)) c.push('dim')
  if (sel.value === n.id) c.push('sel')
  else if (sel.value && related.value.has(n.id)) c.push('rel')
  return c
}
const related = computed(() => {
  const s = new Set<string>()
  if (sel.value) for (const e of edgesOf(deps.value, sel.value)) s.add(e.other)
  return s
})
function stripe(n: SchemaNode): string {
  if (mode.value !== 'one' || n.deprecated || !pa.value || stateOf(n.id, pa.value) !== 'supported') return ''
  return entryOf(n.id, pa.value)?.credibility ?? ''
}
function inherited(n: SchemaNode): boolean {
  return mode.value === 'one' && !!pa.value && stateOf(n.id, pa.value) === 'supported' && !!entryOf(n.id, pa.value)?.inherited
}
/** 对比模式右侧小方块：支持时按可信度着色，否则显示不支持 / 未填写。 */
function square(id: string, pid: string): string {
  const st = stateOf(id, pid)
  if (st === 'unsupported') return 'uns'
  if (st === 'unfilled') return 'unf'
  return entryOf(id, pid)?.credibility ?? 'reviewed'
}
function pillText(p: PillPos): string {
  return fitText(p.item.name, p.w, mode.value === 'cmp' ? 44 : inherited(p.item.node) ? 44 : 22)
}

const edges = computed(() => {
  if (!showEdges.value) return []
  const pos = layout.value.pos
  const prof = mode.value === 'one' ? pa.value : null
  return deps.value
    .filter((d) => depApplies(d, prof))
    .map((d, i) => {
      const a = pos.get(d.from), b = pos.get(d.to)
      if (!a || !b) return null
      const style = depStyle(d.kind)
      const hot = !!sel.value && (d.from === sel.value || d.to === sel.value)
      return {
        key: `${i}-${d.kind}-${d.from}-${d.to}`,
        d: edgePath(a, b, i),
        cls: ['g-edge', style, hot ? 'is-hot' : sel.value ? 'is-dim' : 'faint'],
        mutex: style === 'mutex',
        marker: `url(#sv-${style})`,
        title: `${t('e.' + style)}: ${d.from} → ${d.to}${noteText(d.note, lang.value) ? '\n' + noteText(d.note, lang.value) : ''}`,
      }
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)
})

function pick(id: string | null, scroll = false): void {
  sel.value = id
  if (scroll && id && gview.value) {
    const p = layout.value.pos.get(id)
    if (p) gview.value.scrollTop = Math.max(0, p.y - 160)
  }
}
function onPill(id: string): void {
  pick(sel.value === id ? null : id)
}

/* ---------------- 侧栏 ---------------- */
const selNode = computed(() => (sel.value ? byId.value.get(sel.value) : undefined))
const selEdges = computed(() => (sel.value ? edgesOf(deps.value, sel.value) : []))
const covA = computed(() => (coverage.value && pa.value ? coverageOf(nodes.value, coverage.value.matrix, pa.value) : null))
const covB = computed(() => (coverage.value && pb.value ? coverageOf(nodes.value, coverage.value.matrix, pb.value) : null))
const credA = computed(() => {
  const d = details[pa.value]
  return d ? credibilityCounts([...d.values()], deprecated.value) : null
})
const credTotal = computed(() => (credA.value ? credA.value.verified + credA.value.reviewed + credA.value.draft : 0))
const domainRows = computed(() =>
  domains.value.map((d) => ({
    domain: d.domain,
    count: d.nodes.length,
    cov: coverage.value && pa.value ? coverageOf(d.nodes, coverage.value.matrix, pa.value) : null,
  })),
)
const inactive = computed(() =>
  pa.value ? nodes.value.filter((n) => !n.deprecated && stateOf(n.id, pa.value) !== 'supported') : [],
)
const groupsCmp = computed(() => compareGroups(cmp.value?.rows ?? [], deprecated.value))
const cmpSections = computed(() => [
  { key: 'onlyA', ab: 'a', rows: groupsCmp.value.onlyA },
  { key: 'onlyB', ab: 'b', rows: groupsCmp.value.onlyB },
  { key: 'defaults', ab: '', rows: groupsCmp.value.defaults },
  { key: 'unfilledEither', ab: '', rows: groupsCmp.value.unfilled },
])
const sideTitle = computed(() => {
  if (selNode.value) return t('schema-view.node')
  if (mode.value === 'cmp') return t('schema-view.compare')
  return mode.value === 'one' ? t('schema-view.profileCoverage') : t('schema-view.schemaTotals')
})
const profA = computed(() => profileById.value.get(pa.value))
const noMatch = computed(() => {
  const s = q.value.trim().toLowerCase()
  return !!s && !nodes.value.some((n) => n.id.toLowerCase().includes(s))
})

function shortProfile(id: string): string {
  return stripVendor(id)
}
function cmpValue(r: CompareRow): string {
  return `${fmtValue(r.a.default) || '—'} / ${fmtValue(r.b.default) || '—'}`
}
</script>

<template>
  <main class="main">
    <div class="page fill">
      <div class="ph" style="margin-bottom: 10px">
        <div class="ph-text">
          <h1>{{ $t('nav.schema-view') }}</h1>
          <p class="ph-sub">{{ $t('schema-view.sub') }}</p>
        </div>
        <div class="ph-actions">
          <span v-if="schema" class="tag mono">{{ $t('schema-view.kbVersion', { v: schema.kb_version }) }}</span>
          <router-link class="btn" :to="{ name: 'coverage' }" data-testid="sv-to-coverage"><Icon name="matrix" small />{{ $t('nav.coverage') }}</router-link>
          <router-link v-if="auth.isKbEditor" class="btn" :to="{ name: 'schema-edit', query: sel ? { node: sel } : {} }" data-testid="sv-to-edit"><Icon name="tree" small />{{ $t('nav.schema-edit') }}</router-link>
        </div>
      </div>

      <KbRoRibbon ref="ribbon" full />
      <div v-if="sent" class="notice ok" style="margin-bottom: 10px" data-testid="kb-suggest-sent"><Icon name="check" /><div>{{ sent }}</div></div>
      <KbSuggest v-if="suggest" :target="suggest.target" :current="suggest.current" :kind="suggest.kind" @close="suggest = null" @submitted="onSuggested" />
      <div v-if="loading" class="panel"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>
      <div v-else-if="error" class="notice err" data-testid="sv-error">
        <Icon name="err" />
        <div class="grow"><b>{{ $t('schema-view.loadError') }}</b><div class="small mt8">{{ error }}</div></div>
        <button class="btn btn-sm" data-testid="sv-retry" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
      </div>
      <div v-else-if="!nodes.length" class="panel"><div class="empty"><p>{{ $t('schema-view.noNodes') }}</p></div></div>

      <template v-else>
        <div class="sv-bar" data-testid="sv-toolbar">
          <div class="seg" role="group" data-testid="sv-mode">
            <button type="button" :aria-pressed="mode === 'one'" :disabled="!profiles.length" @click="mode = 'one'">{{ $t('schema-view.modeOne') }}</button>
            <button type="button" :aria-pressed="mode === 'cmp'" :disabled="!profiles.length" @click="mode = 'cmp'">{{ $t('schema-view.modeCmp') }}</button>
            <button type="button" :aria-pressed="mode === 'all'" @click="mode = 'all'">{{ $t('schema-view.modeAll') }}</button>
          </div>
          <span v-if="mode !== 'all' && profiles.length" class="row">
            <span class="ab a">A</span>
            <select v-model="pa" class="select" data-testid="sv-profile-a">
              <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
            </select>
          </span>
          <span v-if="mode === 'cmp'" class="row">
            <span class="ab b">B</span>
            <select v-model="pb" class="select" data-testid="sv-profile-b">
              <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
            </select>
          </span>
          <label v-if="mode === 'cmp'" class="check"><input v-model="onlyDiff" type="checkbox" data-testid="sv-only-diff" /><span>{{ $t('schema-view.onlyDiff') }}</span></label>
          <span v-if="!profiles.length" class="small faint">{{ $t('schema-view.noProfiles') }}</span>
          <span style="flex: 1"></span>
          <label class="input-wrap" style="width: 220px">
            <Icon name="search" small />
            <input v-model="q" class="input" type="search" :placeholder="$t('schema-view.search')" data-testid="sv-search" />
          </label>
          <label class="check"><input v-model="showEdges" type="checkbox" data-testid="sv-show-edges" /><span>{{ $t('schema-view.showEdges') }}</span></label>
        </div>

        <div class="work">
          <section class="panel p-graph">
            <div ref="gview" class="gview canvas" data-testid="sv-graph" @click.self="pick(null)">
              <div v-if="noMatch" class="notice info nomatch"><Icon name="info" /><div class="grow small">{{ $t('schema-view.noMatch', { q: q.trim() }) }}</div></div>
              <svg :width="layout.width" :height="layout.height" :viewBox="`0 0 ${layout.width} ${layout.height}`" @click.self="pick(null)">
                <defs>
                  <marker v-for="s in ['ref', 'pre', 'side', 'cross']" :id="`sv-${s}`" :key="s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path :class="['mk', s]" d="M0 0L10 5L0 10z" />
                  </marker>
                  <marker id="sv-mutex" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="8" markerHeight="8" orient="auto">
                    <path class="mk mutex" d="M5 0v10" stroke-width="2.2" />
                  </marker>
                </defs>
                <g>
                  <path
                    v-for="e in edges" :key="e.key" :class="e.cls" :d="e.d"
                    :marker-start="e.mutex ? e.marker : undefined" :marker-end="e.marker"
                  ><title>{{ e.title }}</title></path>
                </g>
                <g v-for="g in layout.groups" :key="g.domain">
                  <rect class="grp-box" :x="g.x" :y="g.y" :width="g.w" :height="g.h" rx="8" />
                  <text class="grp-title" :x="g.x + 12" :y="g.y + 19">{{ g.domain }}</text>
                  <text class="grp-sub" :x="g.x + 12" :y="g.y + 32">{{ domName(g.domain) }}, {{ g.count }}</text>
                  <text v-if="mode === 'one' && coverage && pa" class="grp-pct" :x="g.x + g.w - 12" :y="g.y + 19" text-anchor="end">
                    {{ domainRows.find((d) => d.domain === g.domain)?.cov?.pct ?? 0 }}%
                  </text>
                  <text v-if="mode === 'cmp' && coverage" class="grp-pct" :x="g.x + g.w - 12" :y="g.y + 19" text-anchor="end">
                    A {{ coverageOf(domains.find((d) => d.domain === g.domain)?.nodes ?? [], coverage.matrix, pa).pct }}%
                    B {{ coverageOf(domains.find((d) => d.domain === g.domain)?.nodes ?? [], coverage.matrix, pb).pct }}%
                  </text>
                </g>
                <g
                  v-for="p in layout.pills" :key="p.item.node.id" :class="pillClass(p)" :data-id="p.item.node.id"
                  :transform="`translate(${p.x} ${p.y})`" data-testid="sv-node" @click="onPill(p.item.node.id)"
                >
                  <title>{{ p.item.node.id }}&#10;{{ sem(p.item.node) }}<template v-if="styleForm(terms, p.item.node.id, p.item.node.type, terms.style)">&#10;{{ $t(`style.${terms.style}`) }}: {{ styleForm(terms, p.item.node.id, p.item.node.type, terms.style) }}</template></title>
                  <rect class="box" :width="p.w" :height="PH" rx="4" />
                  <rect v-if="stripe(p.item.node)" :class="['stripe', stripe(p.item.node)]" x="0.5" y="3" width="3" :height="PH - 6" rx="1.5" />
                  <text x="9" y="14">{{ pillText(p) }}</text>
                  <text v-if="inherited(p.item.node)" class="inhmark" :x="p.w - 8" y="14" text-anchor="end">{{ $t('schema-view.inh') }}</text>
                  <template v-if="mode === 'cmp' && !p.item.node.deprecated">
                    <rect :class="['sq', square(p.item.node.id, pa)]" :x="p.w - 30" y="5" width="10" height="10" rx="2" />
                    <rect :class="['sq', square(p.item.node.id, pb)]" :x="p.w - 17" y="5" width="10" height="10" rx="2" />
                  </template>
                </g>
              </svg>
            </div>
            <div class="glegend" data-testid="sv-legend">
              <template v-if="mode === 'one'">
                <span class="k"><svg viewBox="0 0 22 12"><rect x="1" y="1" width="20" height="10" rx="2" class="sw-act" /></svg>{{ $t('schema-view.legendActive') }}</span>
                <span class="k"><span class="tag verified">verified</span><span class="tag reviewed">reviewed</span><span class="tag draft">draft</span></span>
                <span class="k"><svg viewBox="0 0 22 12"><rect x="1" y="1" width="20" height="10" rx="2" class="sw-uns" /></svg>{{ $t('st.unsupported') }}</span>
                <span class="k"><svg viewBox="0 0 22 12"><rect x="1" y="1" width="20" height="10" rx="2" class="sw-unf" /></svg>{{ $t('st.unfilled') }}</span>
              </template>
              <template v-else-if="mode === 'cmp'">
                <span class="k"><span class="ab a">A</span><span class="ab b">B</span>{{ $t('schema-view.legendCmp') }}</span>
                <span class="k"><svg viewBox="0 0 22 12"><rect x="1" y="1" width="20" height="10" rx="2" class="sw-diff" /></svg>{{ $t('schema-view.legendDiff') }}</span>
              </template>
              <span v-else class="k">{{ $t('schema-view.legendAll') }}</span>
              <span class="k"><svg viewBox="0 0 22 12"><rect x="1" y="1" width="20" height="10" rx="2" class="sw-dep" /></svg>deprecated</span>
              <template v-if="showEdges">
                <span v-for="s in EDGE_STYLES" :key="s" class="k"><svg viewBox="0 0 22 12"><path :class="['g-edge', s]" d="M1 6H21" /></svg>{{ $t('e.' + s) }}</span>
              </template>
            </div>
          </section>

          <aside class="panel p-side" data-testid="sv-side">
            <div class="panel-h"><h3>{{ sideTitle }}</h3></div>
            <div class="scroll">
              <!-- 节点卡片 -->
              <template v-if="selNode">
                <div class="row" style="justify-content: space-between">
                  <span class="mono" style="font-weight: 600; font-size: 13px; overflow-wrap: anywhere">{{ selNode.id }}</span>
                  <button class="btn btn-ghost btn-sm btn-icon" :title="$t('schema-view.clearSel')" data-testid="sv-clear-sel" @click="pick(null)"><Icon name="x" small /></button>
                </div>
                <p class="small muted mt8">{{ sem(selNode) }}</p>
                <StyleForms :id="selNode.id" :type="selNode.type" />
                <dl class="kv mt12">
                  <dt>{{ $t('schema-view.type') }}</dt><dd class="mono">{{ selNode.type }}</dd>
                  <template v-if="selNode.range"><dt>{{ $t('schema-view.range') }}</dt><dd class="mono">[{{ selNode.range.join(', ') }}]</dd></template>
                  <template v-if="selNode.choices?.length"><dt>{{ $t('schema-view.choices') }}</dt><dd class="mono">{{ selNode.choices.join(' / ') }}</dd></template>
                  <template v-if="selNode.ref"><dt>{{ $t('schema-view.ref') }}</dt><dd class="mono"><button class="link-btn mono" @click="pick(selNode.ref, true)">{{ selNode.ref }}</button></dd></template>
                  <template v-if="selNode.key?.length"><dt>{{ $t('schema-view.key') }}</dt><dd class="mono">{{ selNode.key.join(', ') }}</dd></template>
                  <template v-if="selNode.parent"><dt>{{ $t('schema-view.parent') }}</dt><dd class="mono"><button class="link-btn mono" @click="pick(selNode.parent, true)">{{ selNode.parent }}</button></dd></template>
                  <dt>{{ $t('schema-view.status') }}</dt><dd><span :class="['tag', selNode.status]">{{ selNode.status }}</span></dd>
                </dl>
                <div v-if="selNode.deprecated" class="notice warn mt12">
                  <Icon name="warn" />
                  <div class="grow small">
                    <template v-if="selNode.replaced_by">{{ $t('schema-view.deprecatedTo') }} <button class="link-btn mono" @click="pick(selNode.replaced_by, true)">{{ selNode.replaced_by }}</button></template>
                    <template v-else>{{ $t('schema-view.deprecatedNoRepl') }}</template>
                  </div>
                </div>
                <template v-if="profiles.length">
                  <div class="section-t" style="margin-top: 14px">{{ $t('schema-view.perProfile') }}</div>
                  <table class="ptab" data-testid="sv-per-profile">
                    <tbody>
                      <tr v-for="p in profiles" :key="p.id">
                        <td :title="p.id">{{ shortProfile(p.id) }}</td>
                        <td>
                          <span v-if="stateOf(selNode.id, p.id) === 'unsupported'" class="tag">{{ $t('st.unsupported') }}</span>
                          <span v-else-if="stateOf(selNode.id, p.id) === 'unfilled'" class="tag unfilled">{{ $t('st.unfilled') }}</span>
                          <template v-else>
                            <span :class="['tag', entryOf(selNode.id, p.id)?.credibility ?? 'supported']">{{ entryOf(selNode.id, p.id)?.credibility ?? $t('st.supported') }}</span>
                            <span v-if="entryOf(selNode.id, p.id)?.inherited" class="tag inherited" style="margin-left: 4px">{{ $t('src.inherited') }}</span>
                          </template>
                        </td>
                        <td class="mono small">{{ fmtValue(entryOf(selNode.id, p.id)?.default) }}</td>
                        <td v-if="!auth.isKbEditor" class="right"><button class="btn btn-xs btn-ghost" type="button" :title="$t('kbsugg.button')" :data-testid="`sv-suggest-default-${p.id}`" @click="suggest = { target: `${p.id}:${selNode.id}`, current: fmtValue(entryOf(selNode.id, p.id)?.default), kind: 'default' }"><Icon name="chat" small /></button></td>
                      </tr>
                    </tbody>
                  </table>
                </template>
                <template v-if="selEdges.length">
                  <div class="section-t">{{ $t('schema-view.deps') }}</div>
                  <div class="dlist">
                    <div v-for="(e, i) in selEdges" :key="i" class="ditem" :title="noteText(e.note, lang)" @click="pick(e.other, true)">
                      <span class="tag etag" :style="{ borderColor: `var(--e-${e.style})`, color: `var(--e-${e.style})` }">{{ $t('e.' + e.style) }}</span>
                      <span class="nm">{{ e.dir === 'in' ? '← ' : '' }}{{ e.other }}</span>
                    </div>
                  </div>
                </template>
                <div class="row mt12">
                  <router-link v-if="auth.isKbEditor" class="btn btn-sm" :to="{ name: 'schema-edit', query: { node: selNode.id } }" data-testid="sv-edit-node"><Icon name="tree" small />{{ $t('schema-view.editNode') }}</router-link>
                  <button v-else class="btn btn-sm" type="button" data-testid="sv-suggest-node" @click="suggest = { target: selNode.id, current: '', kind: 'description' }"><Icon name="chat" small />{{ $t('kbsugg.objectButton') }}</button>
                </div>
                <hr style="margin: 16px 0" />
              </template>

              <!-- 单个 Profile / 全集 -->
              <template v-if="mode === 'one' || mode === 'all'">
                <template v-if="mode === 'one' && covA">
                  <div class="row" style="gap: 8px">
                    <VendorBadge :of="profA?.vendor" />
                    <span class="mono" style="font-weight: 600">{{ pa }}</span>
                  </div>
                  <p v-if="profA" class="small faint mt8">
                    {{ [profA.platform, profA.software].filter(Boolean).join(', ') }}<template v-if="profA.inherits">, {{ $t('schema-view.inherits', { p: profA.inherits }) }}</template>
                  </p>
                  <div class="meter mt12"><div class="bar"><i :style="{ width: covA.pct + '%' }"></i></div><span class="val">{{ covA.pct }}%</span></div>
                  <p class="small muted mt8">{{ $t('schema-view.active', { a: covA.sup, t: covA.tot, u: covA.unf, n: covA.uns }) }}</p>
                  <template v-if="credA && credTotal">
                    <div class="stackbar mt12">
                      <i :style="{ width: (credA.verified * 100) / credTotal + '%', background: 'var(--teal)' }"></i>
                      <i :style="{ width: (credA.reviewed * 100) / credTotal + '%', background: 'var(--blue)' }"></i>
                      <i :style="{ width: (credA.draft * 100) / credTotal + '%', background: 'var(--amber)' }"></i>
                    </div>
                    <div class="legend mt8">
                      <span><i style="background: var(--teal)"></i>verified {{ credA.verified }}</span>
                      <span><i style="background: var(--blue)"></i>reviewed {{ credA.reviewed }}</span>
                      <span><i style="background: var(--amber)"></i>draft {{ credA.draft }}</span>
                    </div>
                  </template>
                </template>
                <p v-if="mode === 'all'" class="small muted">{{ $t('schema-view.nodesN', { n: nodes.length }) }} · {{ $t('schema-view.depsN', { n: deps.length }) }}</p>
                <div class="section-t">{{ $t('schema-view.byDomain') }}</div>
                <div v-for="d in domainRows" :key="d.domain" class="domrow">
                  <span class="mono" :title="domName(d.domain)">{{ d.domain }}</span>
                  <div v-if="mode === 'one' && d.cov" class="meter"><div class="bar"><i :style="{ width: d.cov.pct + '%' }"></i></div><span class="val">{{ d.cov.pct }}%</span></div>
                  <span v-else class="small muted">{{ $t('schema-view.nodesN', { n: d.count }) }}</span>
                </div>
                <template v-if="mode === 'one' && pa">
                  <div class="section-t">{{ $t('schema-view.inactive') }} <span class="pill-count">{{ inactive.length }}</span></div>
                  <p v-if="!inactive.length" class="small faint">{{ $t('schema-view.none') }}</p>
                  <div v-else class="dlist" data-testid="sv-inactive">
                    <div v-for="n in inactive" :key="n.id" class="ditem" @click="pick(n.id, true)">
                      <span class="nm">{{ n.id }}</span>
                      <span class="vv">{{ stateOf(n.id, pa) === 'unfilled' ? $t('st.unfilled') : $t('st.unsupported') }}</span>
                    </div>
                  </div>
                </template>
              </template>

              <!-- 对比 -->
              <template v-else>
                <div v-if="covA" class="cmp-meter"><span class="ab a">A</span><div class="meter"><div class="bar"><i class="b" :style="{ width: covA.pct + '%' }"></i></div></div><span class="small" style="font-weight: 600">{{ covA.pct }}%</span></div>
                <div v-if="covB" class="cmp-meter mt8"><span class="ab b">B</span><div class="meter"><div class="bar"><i :style="{ width: covB.pct + '%', background: 'var(--violet)' }"></i></div></div><span class="small" style="font-weight: 600">{{ covB.pct }}%</span></div>
                <div v-if="pa === pb" class="notice info mt12"><Icon name="info" /><div class="grow small">{{ $t('schema-view.sameProfile') }}</div></div>
                <div v-if="cmpError" class="notice err mt12">
                  <Icon name="err" /><div class="grow small">{{ cmpError }}</div>
                  <button class="btn btn-xs" @click="loadCompare">{{ $t('c.retry') }}</button>
                </div>
                <p v-else-if="!cmp" class="small faint mt12">{{ $t('c.loading') }}</p>
                <template v-else>
                  <template v-for="g in cmpSections" :key="g.key">
                    <div class="section-t">
                      <span v-if="g.ab" :class="['ab', g.ab]">{{ g.ab.toUpperCase() }}</span>{{ $t('schema-view.' + g.key) }}
                      <span class="pill-count">{{ g.rows.length }}</span>
                    </div>
                    <p v-if="!g.rows.length" class="small faint">{{ $t('schema-view.none') }}</p>
                    <div v-else class="dlist" :data-testid="`sv-cmp-${g.key}`">
                      <div v-for="r in g.rows" :key="r.node" class="ditem" :title="sem(r)" @click="pick(r.node, true)">
                        <span class="nm">{{ r.node }}</span>
                        <span v-if="g.key === 'defaults'" class="vv">{{ cmpValue(r) }}</span>
                        <span v-else-if="g.key === 'unfilledEither'" class="vv">{{ r.a.state === 'unfilled' ? 'A' : '' }}{{ r.a.state === 'unfilled' && r.b.state === 'unfilled' ? ' / ' : '' }}{{ r.b.state === 'unfilled' ? 'B' : '' }}</span>
                      </div>
                    </div>
                  </template>
                </template>
              </template>
            </div>
          </aside>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.sv-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.sv-bar .select { width: auto; min-width: 230px; font-family: var(--font-mono); font-size: 12px; }
.ab { display: inline-flex; width: 18px; height: 18px; border-radius: 4px; align-items: center; justify-content: center; font: 700 11px var(--font-ui); color: #fff; flex: none; margin-right: 4px; }
.ab.a { background: var(--blue); }
.ab.b { background: var(--violet); }
:root[data-theme="dark"] .ab { color: #0D171E; }
.work { flex: 1; min-height: 0; display: grid; gap: 10px; grid-template-columns: minmax(0, 1fr) 340px; }
@media (max-width: 1240px) { .work { grid-template-columns: minmax(0, 1fr) 290px; } }
.p-graph { display: flex; flex-direction: column; overflow: hidden; }
.gview { flex: 1; overflow: auto; min-height: 0; }
.nomatch { position: sticky; top: 8px; left: 8px; margin: 8px; width: max-content; z-index: 1; }
.glegend { display: flex; gap: 6px 14px; padding: 7px 12px; border-top: 1px solid var(--line); flex-wrap: wrap; align-items: center; font-size: 11.5px; color: var(--ink-2); }
.glegend .k { display: inline-flex; align-items: center; gap: 5px; }
.glegend svg { width: 22px; height: 12px; }
.glegend .g-edge { stroke-width: 2; }
.sw-act { fill: var(--surface); stroke: var(--line-strong); }
.sw-uns { fill: var(--surface-3); stroke: var(--line); }
.sw-unf { fill: none; stroke: var(--amber); stroke-dasharray: 3 2; }
.sw-diff { fill: var(--surface); stroke: var(--amber); stroke-width: 1.6; }
.sw-dep { fill: none; stroke: var(--line-strong); stroke-dasharray: 1.5 2; }
.p-side { display: flex; flex-direction: column; overflow: hidden; }
.p-side .scroll { flex: 1; padding: 14px; }
.grp-box { fill: var(--surface); fill-opacity: .72; stroke: var(--line-strong); stroke-width: 1; }
.grp-title { font: 600 12.5px var(--font-ui); fill: var(--teal-ink); }
.grp-sub { font: 11px var(--font-ui); fill: var(--ink-3); }
.grp-pct { font: 600 11.5px var(--font-ui); fill: var(--ink-2); }
.pill { cursor: pointer; }
.pill .box { fill: var(--surface); stroke: var(--line-strong); stroke-width: 1; }
.pill text { font: 11.5px var(--font-mono); fill: var(--ink); }
.pill.obj text { font-weight: 600; }
.pill.uns .box { fill: var(--surface-3); stroke: var(--line); }
.pill.uns text { fill: var(--ink-3); }
.pill.unf .box { fill: transparent; stroke: var(--amber); stroke-dasharray: 4 3; stroke-width: 1.4; }
.pill.dep text { text-decoration: line-through; fill: var(--ink-3); }
.pill.dep .box { fill: transparent; stroke-dasharray: 1.5 2.5; }
.pill.diff .box { stroke: var(--amber); stroke-width: 1.6; }
.pill.dim { opacity: .25; }
.pill:hover .box { stroke: var(--blue); }
.pill.rel .box { stroke: var(--blue); stroke-width: 1.8; }
.pill.sel .box { stroke: var(--amber); stroke-width: 2.4; }
.stripe.verified { fill: var(--teal); }
.stripe.reviewed { fill: var(--blue); }
.stripe.draft { fill: var(--amber); }
.sq.verified { fill: var(--teal); }
.sq.reviewed { fill: var(--blue); }
.sq.draft { fill: var(--amber); }
.sq.uns { fill: var(--line-strong); }
.sq.unf { fill: none; stroke: var(--amber); stroke-width: 1.4; stroke-dasharray: 2 1.5; }
.pill text.inhmark { font: 600 10px var(--font-ui); fill: var(--teal-ink); }
.g-edge.faint { opacity: .35; }
.mk.ref { fill: var(--e-ref); }
.mk.pre { fill: var(--e-pre); }
.mk.side { fill: var(--e-side); }
.mk.mutex { fill: var(--e-mutex); stroke: var(--e-mutex); }
.mk.cross { fill: var(--e-cross); }
.dlist { display: flex; flex-direction: column; gap: 2px; }
.ditem { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 4px; cursor: pointer; font: 12px var(--font-mono); }
.ditem:hover { background: var(--surface-2); }
.ditem .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ditem .vv { font-size: 11px; color: var(--ink-3); white-space: nowrap; }
.etag { font-family: var(--font-ui); background: transparent; }
.ptab { width: 100%; border-collapse: collapse; font-size: 12px; }
.ptab td { padding: 5px 4px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.ptab td:first-child { font: 11.5px var(--font-mono); color: var(--ink-2); }
.ptab tr:last-child td { border-bottom: 0; }
.domrow { display: grid; grid-template-columns: 128px minmax(0, 1fr); gap: 8px; align-items: center; margin-bottom: 6px; font-size: 12px; }
.domrow .mono { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cmp-meter { display: grid; grid-template-columns: 18px minmax(0, 1fr) 40px; gap: 6px; align-items: center; }
.cmp-meter .ab { margin-right: 0; }
</style>
