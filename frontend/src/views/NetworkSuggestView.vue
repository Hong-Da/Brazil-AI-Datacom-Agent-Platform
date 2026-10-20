<script setup lang="ts">
/**
 * 建网建议（M9，/p/<项目>/networks/suggest；预览 DevelopDocs/ui-preview/M9/suggest.html）：选一种依据（连通分量、IGP 域、
 * BGP AS、设备名规则、管理网段、AI 拓扑整理的分组），代码在项目全部设备的配置图上算出划分（GET /network-suggestions），
 * 先预览再采纳（POST /network-suggestions/adopt，每个建议建一个网络）；也可以把建议的设备加到已有网络。
 * AI 分组先经代码校验（设备都在项目里、组内连通），不通过的不能采纳；未配置 AI 时其他依据照常可用。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import NetChip from '@/components/net-chip.vue'
import { errorText, get, post } from '@/api'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { useStatus } from '@/stores/status'
import { BASES, colorClass, netOrder, type AdoptResult, type Basis, type DevNet, type NetBrief, type Suggestion, type SuggestResult } from './networks/logic'

const project = useProject()
const network = useNetwork()
const status = useStatus()
const { t } = useI18n()

const ICON: Record<Basis, string> = { components: 'network', igp: 'layers', bgp: 'globe', name: 'tag', subnet: 'globe', ai: 'spark' }
const basis = ref<Basis>('igp')
const params = reactive({ ignore_mgmt: true, protocol: 'all' as 'all' | 'isis' | 'ospf', regex: '^(.+)-[^-]+$', prefix: 24 })
const res = ref<SuggestResult | null>(null)
const counts = ref<Partial<Record<Basis, number>>>({})
const loading = ref(false)
const err = ref('')
const msg = ref('')
const names = ref<Record<string, string>>({})
const withRule = ref<Record<string, boolean>>({})
const state = ref<Record<string, { done?: NetBrief; into?: NetBrief; skip?: boolean }>>({})
const canWrite = computed(() => project.canWrite)
const aiOn = computed(() => !!status.summary?.ai.configured)
const existing = computed(() => netOrder(network.list).filter((n) => !n.default))
const base = computed(() => `/projects/${encodeURIComponent(project.ref ?? '')}`)

function query(): string {
  const q = new URLSearchParams({ basis: basis.value })
  if (basis.value === 'components') q.set('ignore_mgmt', String(params.ignore_mgmt))
  if (basis.value === 'igp') q.set('protocol', params.protocol)
  if (basis.value === 'name' && params.regex.trim()) q.set('regex', params.regex.trim())
  if (basis.value === 'subnet') q.set('prefix', String(params.prefix))
  return q.toString()
}
function bodyParams(): Record<string, unknown> {
  return { ignore_mgmt: params.ignore_mgmt, protocol: params.protocol, regex: params.regex.trim() || null, prefix: params.prefix }
}

let seq = 0
async function run(): Promise<void> {
  if (!project.ref) return
  const my = ++seq
  loading.value = true
  err.value = ''
  try {
    const r = await get<SuggestResult>(`${base.value}/network-suggestions?${query()}`)
    if (my !== seq) return
    res.value = r
    counts.value = { ...counts.value, [basis.value]: r.total }
    state.value = {}
    names.value = Object.fromEntries(r.suggestions.map((s) => [s.key, s.name]))
    withRule.value = Object.fromEntries(r.suggestions.map((s) => [s.key, true]))
  } catch (e) {
    if (my !== seq) return
    res.value = null
    err.value = errorText(e)
  } finally {
    if (my === seq) loading.value = false
  }
}
let timer: ReturnType<typeof setTimeout> | null = null
watch(basis, () => { msg.value = ''; void run() })
watch(() => [params.ignore_mgmt, params.protocol, params.prefix], () => void run())
watch(() => params.regex, () => {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => void run(), 400)
})

const list = computed(() => res.value?.suggestions ?? [])
const canRule = computed(() => basis.value === 'name' || basis.value === 'subnet')
const open = (s: Suggestion) => !state.value[s.key] && s.adoptable
const adoptableN = computed(() => list.value.filter(open).length)
const otherName = (k: string) => names.value[k] ?? list.value.find((s) => s.key === k)?.name ?? k
function devList(s: Suggestion): string {
  const shown = s.devices.slice(0, 5).map((d) => d.name).join(', ')
  return s.devices.length > 5 ? t('net.s.andMore', { list: shown, n: s.devices.length - 5 }) : shown
}

async function adopt(keys: string[]): Promise<void> {
  if (!keys.length) return
  err.value = ''
  msg.value = ''
  try {
    const nm: Record<string, string> = {}
    for (const k of keys) if (names.value[k]?.trim()) nm[k] = names.value[k].trim()
    // 规则按每个建议的勾选分两批（接口的 with_rules 对整批生效）
    const withR = canRule.value ? keys.filter((k) => withRule.value[k]) : []
    const without = keys.filter((k) => !withR.includes(k))
    const out: AdoptResult[] = []
    for (const [ks, wr] of [[withR, true], [without, false]] as const) {
      if (ks.length) out.push(await post<AdoptResult>(`${base.value}/network-suggestions/adopt`, { basis: basis.value, params: bodyParams(), keys: ks, with_rules: wr, names: nm }))
    }
    const created = out.flatMap((r) => r.created)
    const st = { ...state.value }
    for (const c of created) st[c.key] = { done: c.network }
    state.value = st
    const skipped = out.flatMap((r) => r.skipped)
    msg.value = t('net.s.created', { n: created.length }) + (skipped.length ? t('net.s.skippedN', { n: skipped.length }) : '')
    await network.load(project.ref ?? '', true)
  } catch (e) {
    err.value = errorText(e)
  }
}
async function addInto(s: Suggestion, slug: string): Promise<void> {
  if (!slug) return
  const n = existing.value.find((x) => x.slug === slug)
  if (!n) return
  err.value = ''
  try {
    await post(`${base.value}/networks/${encodeURIComponent(slug)}/members`, { device_ids: s.devices.map((d) => d.id), policy: 'follow' })
    state.value = { ...state.value, [s.key]: { into: n } }
    msg.value = t('net.s.addedInto', { n: n.name })
    await network.load(project.ref ?? '', true)
  } catch (e) {
    err.value = errorText(e)
  }
}
function skip(s: Suggestion, on: boolean): void {
  const st = { ...state.value }
  if (on) st[s.key] = { skip: true }
  else delete st[s.key]
  state.value = st
}

// ---------------------------------------------------------------- 划分结果预览：每格一台设备（项目设备池顺序）
const pool = ref<{ id: number; name: string; networks?: DevNet[] }[]>([])
interface MapRow { key: string; label: string; cls: string; ai: boolean; ids: Set<number>; net?: NetBrief }
const mapRows = computed<{ existing: MapRow[]; sugg: MapRow[] }>(() => {
  const ex = existing.value.map((n) => ({ key: n.slug, label: n.name, cls: colorClass(n.color), ai: false, ids: new Set(pool.value.filter((d) => d.networks?.some((x) => x.id === n.id)).map((d) => d.id)), net: n }))
  const sg = list.value.filter((s) => !state.value[s.key]?.skip && s.check.status !== 'reject').map((s) => ({ key: s.key, label: names.value[s.key] ?? s.name, cls: 'nc-teal', ai: basis.value === 'ai', ids: new Set(s.devices.map((d) => d.id)) }))
  return { existing: ex, sugg: sg }
})
function cellCls(rows: MapRow[], r: MapRow, id: number): string {
  if (!r.ids.has(id)) return ''
  return rows.filter((x) => x.ids.has(id)).length > 1 ? 'ov' : 'on'
}

onMounted(async () => {
  if (!project.ref) return
  void network.load(project.ref)
  try {
    pool.value = (await get<{ devices: { id: number; name: string; networks?: DevNet[] }[] }>('/devices', { network: false })).devices.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  } catch { /* 预览图只是辅助 */ }
  void run()
})
watch(() => project.ref, () => void run())
</script>

<template>
  <main class="main">
    <div class="page" data-testid="suggest-page">
      <div class="crumbs"><span>{{ project.info?.name }}</span><span class="sep">/</span><router-link :to="{ name: 'networks', params: { project: project.ref } }">{{ $t('nav.networks') }}</router-link><span class="sep">/</span><span>{{ $t('nav.network-suggest') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.network-suggest') }}</h1>
          <p class="ph-sub">{{ $t('net.s.sub') }}</p>
        </div>
      </div>

      <div class="nw-basis" role="group" :aria-label="$t('net.s.basis')" data-testid="suggest-basis">
        <button v-for="b in BASES" :key="b" type="button" :class="['nw-bcard', { ai: b === 'ai', off: b === 'ai' && !aiOn }]" :aria-pressed="basis === b" :data-testid="`basis-${b}`" @click="basis = b">
          <span class="t"><Icon :name="ICON[b]" small />{{ $t(`net.s.b.${b}`) }}</span>
          <span class="d">{{ $t(`net.s.bd.${b}`) }}</span>
          <span class="r">{{ b === 'ai' && !aiOn ? $t('net.s.aiOff') : counts[b] !== undefined ? $t('net.s.nSugg', { n: counts[b] }) : '—' }}</span>
        </button>
      </div>

      <div v-if="err" class="notice err mt12" data-testid="suggest-error"><Icon name="err" /><div class="grow">{{ err }}</div></div>
      <div v-if="msg" class="notice ok mt12" data-testid="suggest-msg"><Icon name="ok" /><div class="grow">{{ msg }}</div><router-link class="btn btn-sm" :to="{ name: 'networks', params: { project: project.ref } }">{{ $t('net.s.toList') }}</router-link></div>

      <section class="panel mt12">
        <div v-if="basis !== 'bgp'" class="nw-bparams" data-testid="suggest-params">
          <label v-if="basis === 'components'" class="check"><input v-model="params.ignore_mgmt" type="checkbox"><span>{{ $t('net.s.ignoreMgmt') }}</span></label>
          <template v-if="basis === 'igp'">
            <span>{{ $t('net.s.protocol') }}</span>
            <div class="seg" role="group">
              <button v-for="p in (['all', 'isis', 'ospf'] as const)" :key="p" type="button" :aria-pressed="params.protocol === p" @click="params.protocol = p">{{ $t(`net.s.proto.${p}`) }}</button>
            </div>
            <span class="small faint">{{ $t('net.s.igpNote') }}</span>
          </template>
          <template v-if="basis === 'name'">
            <label class="row" style="gap: 8px"><span>{{ $t('net.s.regex') }}</span><input v-model="params.regex" class="input mono" style="width: 220px" data-testid="suggest-regex"></label>
            <span class="small faint">{{ $t('net.s.regexNote') }}</span>
          </template>
          <template v-if="basis === 'subnet'">
            <span>{{ $t('net.s.prefix') }}</span>
            <div class="seg" role="group">
              <button v-for="p in [16, 22, 24, 26]" :key="p" type="button" :aria-pressed="params.prefix === p" @click="params.prefix = p">/{{ p }}</button>
            </div>
          </template>
          <span v-if="basis === 'ai'" class="small faint"><span class="nw-aitag"><Icon name="spark" small />AI</span> {{ $t('net.s.aiNote') }}</span>
        </div>
        <div v-else class="nw-bparams"><span class="small faint">{{ $t('net.s.bgpNote') }}</span></div>

        <div v-if="basis === 'ai' && !aiOn && !list.length" class="notice info" style="margin: 12px 14px"><Icon name="info" /><div class="grow"><b>{{ $t('net.s.aiOffTitle') }}</b><br>{{ $t('net.s.aiOffText') }}</div></div>
        <div v-if="loading" class="empty" style="padding: 24px"><p>{{ $t('c.loading') }}</p></div>
        <div v-else-if="res && !list.length" class="empty" style="padding: 24px" data-testid="suggest-empty"><Icon name="wand" /><p>{{ $t('net.s.none') }}</p></div>
        <div v-else-if="list.length" class="nw-sgl" data-testid="suggest-list">
          <div class="nw-sgrow head"><span /><span>{{ $t('net.s.colName') }}</span><span>{{ $t('net.colDevices') }}</span><span>{{ $t('net.s.colContains') }}</span><span>{{ $t('net.s.colOverlap') }}</span><span /></div>
          <div v-for="s in list" :key="s.key" :class="['nw-sgrow', { ai: basis === 'ai', 'is-done': state[s.key]?.done || state[s.key]?.into, 'is-skip': state[s.key]?.skip, 'is-bad': s.check.status === 'reject' }]" :data-testid="`sugg-${s.key}`">
            <span><span v-if="basis === 'ai'" class="nw-aitag" :title="$t('net.s.aiChecked')"><Icon name="spark" small /></span><i v-else class="nw-sq nc-teal" /></span>
            <div style="display: flex; flex-direction: column; gap: 4px; min-width: 0">
              <input v-model="names[s.key]" class="input nmin" :disabled="!!state[s.key] || !canWrite" :aria-label="$t('net.s.colName')" :data-testid="`sugg-name-${s.key}`">
              <label v-if="canRule && s.rule && !state[s.key]" class="check small" style="color: var(--ink-2)"><input v-model="withRule[s.key]" type="checkbox"><span>{{ $t('net.s.asRule') }}<code>{{ s.rule.pattern }}</code></span></label>
            </div>
            <span class="cnt"><b>{{ s.count }}</b></span>
            <span class="devs">{{ devList(s) }}<template v-if="basis === 'ai' && s.check.status === 'pass'"><br><span class="nw-vchk"><Icon name="ok" small />{{ $t('net.s.checkPass') }}</span></template></span>
            <div class="ovl">
              <span v-if="s.check.status === 'reject'" class="nw-vchk bad"><Icon name="err" small />{{ $t('net.s.checkFail') }}</span>
              <template v-else-if="s.same_as"><span class="same"><Icon name="ok" small />{{ $t('net.s.sameAs') }}</span><NetChip :net="s.same_as" /></template>
              <template v-else>
                <template v-if="s.overlap_existing.length">
                  <span>{{ $t('net.s.overlapExisting') }}</span>
                  <span class="nw-chips"><span v-for="o in s.overlap_existing" :key="o.slug" class="row" style="gap: 3px"><NetChip :net="o" /><span class="small">{{ o.devices }}</span></span></span>
                </template>
                <span v-else class="small faint">{{ $t('net.s.noOverlap') }}</span>
                <span v-if="s.overlap_suggestions.length" class="small">{{ $t('net.s.overlapOthers', { list: s.overlap_suggestions.map(otherName).join('、') }) }}</span>
              </template>
            </div>
            <div class="ops">
              <template v-if="state[s.key]?.done"><span class="nw-vchk"><Icon name="ok" small />{{ $t('net.s.done') }}</span><NetChip :net="state[s.key]!.done!" :to="{ name: 'members', params: { project: project.ref, network: state[s.key]!.done!.slug } }" /></template>
              <template v-else-if="state[s.key]?.into"><span class="nw-vchk"><Icon name="ok" small />{{ $t('net.s.addedTo') }}</span><NetChip :net="state[s.key]!.into!" /></template>
              <template v-else-if="state[s.key]?.skip"><span class="small faint">{{ $t('net.s.skipped') }}</span><button class="btn btn-sm btn-ghost" type="button" @click="skip(s, false)">{{ $t('net.s.restore') }}</button></template>
              <template v-else-if="!s.adoptable">
                <span class="small faint">{{ s.same_as ? $t('net.s.exists') : $t('net.s.cannot') }}</span>
                <button class="btn btn-sm btn-ghost" type="button" @click="skip(s, true)">{{ $t('net.s.dismiss') }}</button>
              </template>
              <template v-else-if="canWrite">
                <button :class="['btn btn-sm', basis === 'ai' ? 'btn-ai' : 'btn-primary']" type="button" :data-testid="`sugg-adopt-${s.key}`" @click="adopt([s.key])">{{ $t('net.s.adopt') }}</button>
                <select v-if="existing.length" class="select" :aria-label="$t('net.s.into')" :data-testid="`sugg-into-${s.key}`" @change="addInto(s, ($event.target as HTMLSelectElement).value)">
                  <option value="">{{ $t('net.s.into') }}</option>
                  <option v-for="n in existing" :key="n.slug" :value="n.slug">{{ n.name }}</option>
                </select>
                <button class="btn btn-sm btn-ghost" type="button" @click="skip(s, true)">{{ $t('net.s.dismiss') }}</button>
              </template>
            </div>
          </div>
        </div>
        <div v-if="list.length" class="nw-sgfoot">
          <span class="small muted">{{ $t('net.s.foot') }}</span><span class="grow" style="flex: 1" />
          <button v-if="canWrite" :class="['btn', basis === 'ai' ? 'btn-ai' : 'btn-primary']" type="button" :disabled="!adoptableN" data-testid="adopt-all" @click="adopt(list.filter(open).map((s) => s.key))">{{ $t('net.s.adoptAll', { n: adoptableN }) }}</button>
        </div>
      </section>

      <section v-if="pool.length" class="panel mt12" data-testid="suggest-map">
        <div class="panel-h"><h2>{{ $t('net.s.mapTitle') }}</h2><span class="meta">{{ $t('net.s.mapMeta') }}</span></div>
        <div class="nw-pmap">
          <div class="small faint">{{ $t('net.s.mapExisting') }}</div>
          <div v-for="r in mapRows.existing" :key="r.key" class="nw-pmrow">
            <span class="lab"><NetChip v-if="r.net" :net="r.net" /></span>
            <div :class="['nw-pmcells', r.cls]" :style="{ gridTemplateColumns: `repeat(${pool.length}, minmax(0, 1fr))` }"><i v-for="d in pool" :key="d.id" :class="cellCls(mapRows.existing, r, d.id)" :title="d.name" /></div>
            <span class="n">{{ r.ids.size }}</span>
          </div>
          <div v-if="!mapRows.existing.length" class="small faint">—</div>
          <div class="nw-pmsep" />
          <div class="small faint">{{ $t('net.s.mapSugg') }}</div>
          <div v-for="r in mapRows.sugg" :key="r.key" class="nw-pmrow">
            <span class="lab"><span v-if="r.ai" class="nw-aitag"><Icon name="spark" small /></span><i v-else class="nw-sq nc-teal" /><span>{{ r.label }}</span></span>
            <div :class="['nw-pmcells', r.cls, { ai: r.ai }]" :style="{ gridTemplateColumns: `repeat(${pool.length}, minmax(0, 1fr))` }"><i v-for="d in pool" :key="d.id" :class="cellCls(mapRows.sugg, r, d.id)" :title="d.name" /></div>
            <span class="n">{{ r.ids.size }}</span>
          </div>
          <div v-if="!mapRows.sugg.length" class="small faint">—</div>
        </div>
      </section>
    </div>
  </main>
</template>
