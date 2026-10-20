<script setup lang="ts">
/**
 * 网络成员（M9，/p/<项目>/n/<网络>/members；预览 DevelopDocs/ui-preview/M9/members.html）：
 * 本网络引用的设备、本网络用的版本（跟随最新 / 固定，可批量）、还在哪些网络、怎么加入的；从项目设备池添加、移出（记为排除）；
 * 右栏：最近自动加入的设备（可撤销本网络的自动加入）、自动加入规则（设备名通配 / 管理网段，命中预览）、排除的设备。
 * 默认网络包含全部设备：不能移出、没有规则（全部新设备自动加入）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import NetChip from '@/components/net-chip.vue'
import { errorText, get, post, put, del } from '@/api'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { shortTime } from './account/account'
import type { Version } from './add-device/logic'
import {
  colorClass, filterMembers, joinOf, joinedRecently, netOrder,
  type DevNet, type Member, type MemberFilter, type MemberList, type NetRow, type RuleList, type RulePreview,
} from './networks/logic'

const route = useRoute()
const router = useRouter()
const project = useProject()
const network = useNetwork()
const { t } = useI18n()

const slug = computed(() => String(route.params.network ?? ''))
const net = computed(() => network.info)
const isDefault = computed(() => !!net.value?.default)
const canWrite = computed(() => project.canWrite)
const base = computed(() => `/projects/${encodeURIComponent(project.ref ?? '')}/networks/${encodeURIComponent(slug.value)}`)

const members = ref<Member[]>([])
const rules = ref<RuleList | null>(null)
const hits = ref<Record<number, RulePreview>>({})
const loading = ref(true)
const err = ref('')
const msg = ref('')
const q = ref('')
const f = ref<MemberFilter>('')
const sel = ref<Set<number>>(new Set())
const shown = computed(() => filterMembers(members.value, q.value, f.value))
const counts = computed(() => ({
  all: members.value.length,
  shared: filterMembers(members.value, '', 'shared').length,
  pin: filterMembers(members.value, '', 'pin').length,
  new: filterMembers(members.value, '', 'new').length,
}))
/** 成员条的网络（固定顺序：列表顺序） */
const barNets = computed(() => netOrder(network.list))
function inNet(m: Member, n: NetRow): boolean {
  return n.slug === slug.value || m.also_in.some((x) => x.id === n.id)
}
const others = (m: Member) => m.also_in.filter((x) => !x.default)
/** 最近自动加入的成员（规则、导入；24 小时内） */
const recent = computed(() => members.value.filter((m) => (m.join_source === 'rule' || m.join_source === 'import') && joinedRecently(m)))

async function load(): Promise<void> {
  if (!project.ref || !slug.value) return
  loading.value = true
  err.value = ''
  try {
    const [m, r] = await Promise.all([get<MemberList>(`${base.value}/members`), get<RuleList>(`${base.value}/join-rules`)])
    members.value = m.members
    rules.value = r
    const ids = new Set(m.members.map((x) => x.device_id))
    sel.value = new Set([...sel.value].filter((x) => ids.has(x)))
    void loadHits()
  } catch (e) {
    err.value = errorText(e)
  } finally {
    loading.value = false
  }
}
async function loadHits(): Promise<void> {
  const out: Record<number, RulePreview> = {}
  for (const r of rules.value?.rules ?? []) {
    try { out[r.id] = await post<RulePreview>(`${base.value}/join-rules/preview`, { kind: r.kind, pattern: r.pattern }) } catch { /* 预览失败不影响列表 */ }
  }
  hits.value = out
}
async function act(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
  err.value = ''
  msg.value = ''
  try {
    await fn()
    msg.value = ok
    await Promise.all([load(), network.load(project.ref ?? '', true)])
    return true
  } catch (e) {
    err.value = errorText(e)
    return false
  }
}

// ---------------------------------------------------------------- 版本策略
const versions = ref<Record<number, Version[]>>({})
async function loadVersions(m: Member): Promise<void> {
  if (versions.value[m.device_id]) return
  try {
    const r = await get<{ versions: Version[] }>(`/devices/${m.device_id}/versions`, { network: false })
    versions.value = { ...versions.value, [m.device_id]: r.versions }
  } catch { /* 取不到时只有“跟随最新 / 固定在当前版本” */ }
}
/** 下拉的值：follow 或固定的版本编号 */
const verValue = (m: Member) => (m.policy === 'pin' ? String(m.version_id) : 'follow')
function verOptions(m: Member): { v: string; label: string }[] {
  const out = [{ v: 'follow', label: t('net.m.follow', { v: m.latest_seq ?? '—' }) }]
  const list = versions.value[m.device_id]
  if (list?.length) {
    for (const x of [...list].sort((a, b) => b.seq - a.seq)) out.push({ v: String(x.id), label: t('net.m.pinAt', { v: x.seq }) })
  } else {
    if (m.policy === 'pin' && m.version_id) out.push({ v: String(m.version_id), label: t('net.m.pinAt', { v: m.seq ?? '—' }) })
    if (m.latest_version_id && m.latest_version_id !== m.version_id) out.push({ v: String(m.latest_version_id), label: t('net.m.pinAt', { v: m.latest_seq ?? '—' }) })
  }
  return out
}
async function setVersion(m: Member, v: string): Promise<void> {
  const body = v === 'follow' ? { device_ids: [m.device_id], policy: 'follow' } : { device_ids: [m.device_id], policy: 'pin', version_id: Number(v) }
  await act(() => put(`${base.value}/members`, body), v === 'follow' ? t('net.m.nowFollow') : t('net.m.nowPin'))
}
async function bulk(policy: 'follow' | 'pin'): Promise<void> {
  const ids = [...sel.value]
  if (!ids.length) return
  if (await act(() => put(`${base.value}/members`, { device_ids: ids, policy }), t('net.m.bulkDone', { n: ids.length }))) sel.value = new Set()
}
function toggle(id: number, on: boolean): void {
  const s = new Set(sel.value)
  if (on) s.add(id)
  else s.delete(id)
  sel.value = s
}

// ---------------------------------------------------------------- 移出
const rmIds = ref<number[] | null>(null)
const rmNames = computed(() => (rmIds.value ?? []).map((id) => members.value.find((m) => m.device_id === id)?.name ?? String(id)))
const rmRule = computed(() => (rmIds.value ?? []).map((id) => members.value.find((m) => m.device_id === id)).filter((m) => m && (m.join_source === 'rule' || m.rule)).map((m) => m!.name))
async function doRemove(): Promise<void> {
  const ids = rmIds.value ?? []
  if (!ids.length) return
  if (await act(() => post(`${base.value}/members/remove`, { device_ids: ids }), t('net.m.removed', { n: ids.length }))) {
    rmIds.value = null
    sel.value = new Set()
  }
}

// ---------------------------------------------------------------- 从设备池添加
interface PoolDev { id: number; name: string; vendor: string | null; versions?: number; networks?: DevNet[] }
const addOpen = ref(false)
const pool = ref<PoolDev[]>([])
const poolErr = ref('')
const af = reactive({ q: '', f: '', sel: new Set<number>(), policy: 'follow' as 'follow' | 'pin', busy: false })
const poolShown = computed(() => {
  const ids = new Set(members.value.map((m) => m.device_id))
  const k = af.q.trim().toLowerCase()
  return pool.value.filter((d) => {
    if (ids.has(d.id)) return false
    if (k && !d.name.toLowerCase().includes(k)) return false
    const non = (d.networks ?? []).filter((x) => !x.default)
    if (af.f === 'none') return !non.length
    if (af.f.startsWith('n:')) return non.some((x) => x.slug === af.f.slice(2))
    return true
  })
})
async function openAdd(): Promise<void> {
  Object.assign(af, { q: '', f: '', sel: new Set<number>(), policy: 'follow', busy: false })
  addOpen.value = true
  poolErr.value = ''
  try {
    pool.value = (await get<{ devices: PoolDev[] }>('/devices', { network: false })).devices
  } catch (e) {
    poolErr.value = errorText(e)
  }
}
function toggleAdd(id: number, on: boolean): void {
  const s = new Set(af.sel)
  if (on) s.add(id)
  else s.delete(id)
  af.sel = s
}
async function doAdd(): Promise<void> {
  const ids = [...af.sel]
  if (!ids.length) return
  af.busy = true
  if (await act(() => post(`${base.value}/members`, { device_ids: ids, policy: af.policy }), t('net.m.added', { n: ids.length }))) {
    addOpen.value = false
    f.value = ''
  }
  af.busy = false
}

// ---------------------------------------------------------------- 自动加入规则
const rk = ref<'name' | 'subnet'>('name')
const rv = ref('')
const rnow = ref(true)
const rprev = ref<RulePreview | null>(null)
const rprevErr = ref('')
let timer: ReturnType<typeof setTimeout> | null = null
watch([rk, rv], () => {
  if (timer) clearTimeout(timer)
  rprev.value = null
  rprevErr.value = ''
  if (!rv.value.trim()) return
  timer = setTimeout(async () => {
    try { rprev.value = await post<RulePreview>(`${base.value}/join-rules/preview`, { kind: rk.value, pattern: rv.value.trim() }) } catch (e) { rprevErr.value = errorText(e) }
  }, 300)
})
async function addRule(): Promise<void> {
  if (!rv.value.trim()) return
  if (await act(() => post(`${base.value}/join-rules`, { kind: rk.value, pattern: rv.value.trim(), apply_existing: rnow.value }), t('net.r.added'))) {
    rv.value = ''
  }
}
async function delRule(id: number): Promise<void> {
  await act(() => del(`${base.value}/join-rules/${id}`), t('net.r.deleted'))
}
async function unexclude(id: number): Promise<void> {
  await act(() => post(`${base.value}/members/unexclude`, { device_ids: [id] }), t('net.r.unexcluded'))
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') { addOpen.value = false; rmIds.value = null }
}
onMounted(() => {
  document.addEventListener('keydown', onKey)
  void load()
  if (route.query.created === '1') {
    msg.value = t('net.createdHint')
    void router.replace({ query: { ...route.query, created: undefined } })
  }
})
watch(slug, () => { sel.value = new Set(); f.value = ''; void load() })
</script>

<template>
  <main class="main">
    <div class="page" data-testid="members-page">
      <div class="crumbs"><span>{{ project.info?.name }}</span><span class="sep">/</span><NetChip v-if="net" :net="net" /><span class="sep">/</span><span>{{ $t('nav.members') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.members') }}</h1>
          <p class="ph-sub">{{ $t('net.m.sub') }}</p>
        </div>
        <div v-if="canWrite && !isDefault" class="ph-actions"><button class="btn btn-primary" type="button" data-testid="add-members" @click="openAdd"><Icon name="plus" small />{{ $t('net.m.add') }}</button></div>
      </div>
      <div v-if="err" class="notice err" style="margin-bottom: 12px" data-testid="members-error"><Icon name="err" /><div class="grow">{{ err }}</div></div>
      <div v-if="msg" class="notice ok" style="margin-bottom: 12px" data-testid="members-msg"><Icon name="ok" /><div class="grow">{{ msg }}</div></div>

      <div class="nw-mlay">
        <section class="panel">
          <div class="nw-tools">
            <label class="input-wrap"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('net.m.search')" :aria-label="$t('net.m.search')"></label>
            <div class="seg" role="group" data-testid="members-filter">
              <button v-for="x in ([['', 'all'], ['shared', 'shared'], ['pin', 'pin'], ['new', 'new']] as const)" :key="x[0]" type="button" :aria-pressed="f === x[0]" @click="f = x[0]">{{ $t(`net.m.f.${x[1]}`) }} <span class="faint">{{ counts[x[1]] }}</span></button>
            </div>
          </div>
          <div v-if="sel.size && canWrite" class="nw-selbar" data-testid="members-selbar">
            <b>{{ sel.size }}</b>{{ $t('net.m.selected') }}<span class="grow" style="flex: 1" />
            <button class="btn btn-sm" type="button" data-testid="bulk-follow" @click="bulk('follow')">{{ $t('net.m.bulkFollow') }}</button>
            <button class="btn btn-sm" type="button" data-testid="bulk-pin" @click="bulk('pin')">{{ $t('net.m.bulkPin') }}</button>
            <button v-if="!isDefault" class="btn btn-sm btn-danger" type="button" data-testid="bulk-remove" @click="rmIds = [...sel]">{{ $t('net.m.remove') }}</button>
          </div>
          <div class="tbl-wrap">
            <table class="tbl" data-testid="members-table">
              <thead><tr>
                <th style="width: 30px" />
                <th>{{ $t('net.m.colDevice') }}</th><th>{{ $t('net.m.colMgmt') }}</th><th>{{ $t('net.m.colVersion') }}</th><th>{{ $t('net.m.colAlso') }}</th><th>{{ $t('net.m.colHow') }}</th><th />
              </tr></thead>
              <tbody>
                <tr v-if="loading && !members.length"><td colspan="7" class="faint">{{ $t('c.loading') }}</td></tr>
                <tr v-else-if="!shown.length"><td colspan="7"><div class="empty" style="padding: 20px"><p>{{ members.length ? $t('net.m.noMatch') : $t('net.m.empty') }}</p></div></td></tr>
                <tr v-for="m in shown" :key="m.device_id" :class="{ 'nw-isnew': joinedRecently(m) }" :data-testid="`member-${m.name}`">
                  <td><input type="checkbox" :checked="sel.has(m.device_id)" :aria-label="m.name" :disabled="!canWrite" @change="toggle(m.device_id, ($event.target as HTMLInputElement).checked)"></td>
                  <td><div class="devcell"><div><b class="mono">{{ m.name }}</b><small class="faint" style="display: block">{{ m.vendor ?? '' }}{{ m.profile ? ` · ${m.profile}` : '' }}</small></div></div></td>
                  <td class="mono small">{{ m.mgmt_address ?? '—' }}</td>
                  <td>
                    <div class="nw-verpick">
                      <select class="select" :value="verValue(m)" :disabled="!canWrite" :aria-label="$t('net.m.colVersion')" :data-testid="`member-ver-${m.name}`" @focus="loadVersions(m)" @change="setVersion(m, ($event.target as HTMLSelectElement).value)">
                        <option v-for="o in verOptions(m)" :key="o.v" :value="o.v">{{ o.label }}</option>
                      </select>
                      <span v-if="m.newer_available" class="nw-newer"><Icon name="info" small />{{ $t('net.m.newer', { v: m.latest_seq ?? '—' }) }}</span>
                    </div>
                  </td>
                  <td>
                    <div class="row" style="gap: 8px; flex-wrap: wrap">
                      <span class="nw-mbar" :title="barNets.filter((n) => inNet(m, n)).map((n) => n.name).join('、')"><i v-for="n in barNets" :key="n.slug" :class="[colorClass(n.color), { on: inNet(m, n), cur: n.slug === slug }]" /></span>
                      <span class="nw-chips">
                        <NetChip v-for="x in others(m)" :key="x.slug" :net="x" :to="{ name: 'members', params: { network: x.slug } }" />
                        <span v-if="!others(m).length" class="small faint">{{ $t('net.m.noOther') }}</span>
                      </span>
                    </div>
                  </td>
                  <td>
                    <span :class="['nw-how', { sugg: m.join_source === 'suggestion' }]" :title="m.joined_by ? `${m.joined_by} · ${shortTime(m.joined_at)}` : undefined">
                      <Icon :name="joinOf(m.join_source).icon" small />{{ $t(`net.how.${joinOf(m.join_source).key}`) }}<code v-if="m.rule">{{ m.rule.pattern }}</code>
                    </span>
                  </td>
                  <td class="right"><button v-if="canWrite && !isDefault" class="btn btn-sm btn-ghost" type="button" :data-testid="`member-rm-${m.name}`" @click="rmIds = [m.device_id]">{{ $t('net.m.removeOne') }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="panel-f small muted">{{ $t('net.m.foot', { n: members.length }) }}</div>
        </section>

        <div style="display: flex; flex-direction: column; gap: 14px">
          <div v-if="recent.length" class="nw-impnote" data-testid="recent-joined">
            <div class="h"><Icon name="upload" small /><span>{{ $t('net.m.recentTitle') }}</span></div>
            <div class="small muted">{{ $t('net.m.recentSub', { n: recent.length }) }}</div>
            <ul>
              <li v-for="m in recent" :key="m.device_id"><code>{{ m.name }}</code><Icon name="chevR" small /><span class="small faint">{{ m.rule ? $t('net.m.byRule', { p: m.rule.pattern }) : $t('net.m.byImport') }}</span></li>
            </ul>
            <div class="row" style="gap: 6px">
              <button class="btn btn-sm" type="button" @click="f = 'new'">{{ $t('net.m.onlyThese') }}</button>
              <button v-if="canWrite && !isDefault" class="btn btn-sm btn-ghost" type="button" data-testid="undo-auto" @click="rmIds = recent.map((m) => m.device_id)">{{ $t('net.m.undoAuto') }}</button>
            </div>
          </div>

          <section class="panel" data-testid="join-rules">
            <div class="panel-h"><h2>{{ $t('net.r.title') }}</h2></div>
            <div class="panel-b">
              <div v-if="rules?.all_new_devices" class="nw-rule"><Icon name="layers" /><div><div class="t">{{ $t('net.defaultNet') }}</div><code>{{ $t('net.r.allNew') }}</code></div></div>
              <template v-else>
                <div v-for="r in rules?.rules ?? []" :key="r.id" class="nw-rule" :data-testid="`rule-${r.id}`">
                  <Icon :name="r.kind === 'name' ? 'tag' : 'globe'" />
                  <div>
                    <div class="t">{{ $t(`net.r.kind.${r.kind}`) }}</div><code>{{ r.pattern }}</code>
                    <div v-if="hits[r.id]" class="hits">{{ hits[r.id].not_in_network ? $t('net.r.hitsMiss', { n: hits[r.id].matches, m: hits[r.id].not_in_network }) : $t('net.r.hitsAll', { n: hits[r.id].matches }) }}</div>
                  </div>
                  <button v-if="canWrite" class="btn btn-sm btn-ghost btn-icon" type="button" :title="$t('net.r.del')" :aria-label="$t('net.r.del')" :data-testid="`rule-del-${r.id}`" @click="delRule(r.id)"><Icon name="trash" small /></button>
                </div>
                <p v-if="!rules?.rules.length" class="small faint" style="margin: 0">{{ $t('net.r.none') }}</p>
                <div v-if="canWrite" class="nw-addrule">
                  <div class="small" style="font-weight: 600">{{ $t('net.r.add') }}</div>
                  <div class="row">
                    <select v-model="rk" class="select" :aria-label="$t('net.r.kindLabel')" data-testid="rule-kind"><option value="name">{{ $t('net.r.kind.name') }}</option><option value="subnet">{{ $t('net.r.kind.subnet') }}</option></select>
                    <input v-model="rv" class="input mono" :placeholder="rk === 'name' ? 'ran-hub-*' : '10.20.0.0/24'" :aria-label="$t('net.r.pattern')" data-testid="rule-pattern">
                  </div>
                  <div class="small" style="color: var(--ink-2)" data-testid="rule-preview">
                    <template v-if="rprev">
                      {{ rprev.not_in_network ? $t('net.r.prevMiss', { n: rprev.matches, m: rprev.not_in_network }) : rprev.matches ? $t('net.r.prevAll', { n: rprev.matches }) : $t('net.r.prevNone') }}
                      <span v-if="!rprev.mgmt_available" class="faint">{{ $t('net.r.noKb') }}</span>
                    </template>
                    <span v-else-if="rprevErr" style="color: var(--red-ink)">{{ rprevErr }}</span>
                  </div>
                  <label class="check small"><input v-model="rnow" type="checkbox"><span>{{ $t('net.r.applyNow') }}</span></label>
                  <div><button class="btn btn-sm" type="button" :disabled="!rv.trim()" data-testid="rule-add" @click="addRule"><Icon name="plus" small />{{ $t('net.r.addBtn') }}</button></div>
                </div>
                <div class="small muted" style="margin-top: 10px">{{ $t('net.r.note') }}</div>
                <div v-if="rules?.excluded.length" class="row small" style="margin-top: 8px; flex-wrap: wrap; gap: 6px" data-testid="excluded">
                  <span>{{ $t('net.r.excluded') }}</span>
                  <span v-for="x in rules.excluded" :key="x.id" class="nw-rulechip"><code>{{ x.name }}</code><button v-if="canWrite" class="btn btn-xs btn-ghost" type="button" style="height: 16px; padding: 0 3px" :title="$t('net.r.unexclude')" :aria-label="$t('net.r.unexclude')" @click="unexclude(x.id)"><Icon name="x" small /></button></span>
                </div>
              </template>
            </div>
          </section>
        </div>
      </div>
    </div>

    <!-- 从设备池添加 -->
    <div v-if="addOpen" class="modal-back" data-testid="add-dialog" @click.self="addOpen = false">
      <div class="modal" style="width: min(860px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwAddT">
        <div class="modal-h"><h2 id="nwAddT">{{ $t('net.m.addTitle', { n: net?.name ?? '' }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="addOpen = false"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 10px">
          <div v-if="poolErr" class="notice err"><Icon name="err" /><div class="grow">{{ poolErr }}</div></div>
          <div class="row" style="gap: 8px; flex-wrap: wrap">
            <label class="input-wrap" style="width: 240px"><Icon name="search" small /><input v-model="af.q" class="input" type="search" :placeholder="$t('net.m.search')" data-testid="pool-search"></label>
            <select v-model="af.f" class="select" style="width: auto">
              <option value="">{{ $t('net.m.poolAll') }}</option>
              <option value="none">{{ $t('net.m.poolOnlyDefault') }}</option>
              <option v-for="n in barNets.filter((x) => !x.default && x.slug !== slug)" :key="n.slug" :value="`n:${n.slug}`">{{ $t('net.m.poolIn', { n: n.name }) }}</option>
            </select>
          </div>
          <div class="nw-pool">
            <table class="tbl compact" data-testid="pool-table">
              <thead><tr>
                <th style="width: 30px"><input type="checkbox" :checked="poolShown.length > 0 && poolShown.every((d) => af.sel.has(d.id))" :aria-label="$t('net.m.selectAll')" @change="af.sel = ($event.target as HTMLInputElement).checked ? new Set(poolShown.map((d) => d.id)) : new Set()"></th>
                <th>{{ $t('net.m.colDevice') }}</th><th>{{ $t('net.m.colVersions') }}</th><th>{{ $t('net.m.colAlready') }}</th>
              </tr></thead>
              <tbody>
                <tr v-if="!poolShown.length"><td colspan="4"><div class="empty" style="padding: 20px"><p>{{ $t('net.m.poolEmpty') }}</p></div></td></tr>
                <tr v-for="d in poolShown" :key="d.id" :data-testid="`pool-${d.name}`">
                  <td><input type="checkbox" :checked="af.sel.has(d.id)" :aria-label="d.name" @change="toggleAdd(d.id, ($event.target as HTMLInputElement).checked)"></td>
                  <td class="mono">{{ d.name }}</td>
                  <td class="mono small">{{ d.versions ?? '—' }}</td>
                  <td><span class="nw-chips"><NetChip v-for="x in (d.networks ?? []).filter((y) => !y.default)" :key="x.slug" :net="x" /><span v-if="!(d.networks ?? []).some((y) => !y.default)" class="small faint">{{ $t('net.m.onlyDefault') }}</span></span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="row small" style="gap: 8px; flex-wrap: wrap">
            <span>{{ $t('net.m.addPolicy') }}</span>
            <div class="seg" role="group">
              <button type="button" :aria-pressed="af.policy === 'follow'" @click="af.policy = 'follow'">{{ $t('net.m.policyFollow') }}</button>
              <button type="button" :aria-pressed="af.policy === 'pin'" @click="af.policy = 'pin'">{{ $t('net.m.policyPin') }}</button>
            </div>
          </div>
        </div>
        <div class="modal-f">
          <span class="small faint">{{ $t('net.m.available', { n: poolShown.length }) }}</span><span class="grow" style="flex: 1" />
          <button class="btn" type="button" @click="addOpen = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="!af.sel.size || af.busy" data-testid="add-go" @click="doAdd">{{ af.sel.size ? $t('net.m.addN', { n: af.sel.size }) : $t('net.m.addBtn') }}</button>
        </div>
      </div>
    </div>

    <!-- 移出确认 -->
    <div v-if="rmIds" class="modal-back" data-testid="remove-dialog" @click.self="rmIds = null">
      <div class="modal" style="width: min(540px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwRmT">
        <div class="modal-h"><h2 id="nwRmT">{{ rmIds.length === 1 ? $t('net.m.rmOne', { n: rmNames[0] }) : $t('net.m.rmMany', { n: rmIds.length }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="rmIds = null"><Icon name="x" /></button></div>
        <div class="modal-b">
          <ul class="nw-rmlist">
            <li>{{ $t('net.m.rm1') }}</li>
            <li>{{ $t('net.m.rm2') }}</li>
            <li>{{ $t('net.m.rm3') }}<template v-if="rmRule.length"> <code v-for="x in rmRule" :key="x" style="margin-right: 4px">{{ x }}</code></template></li>
          </ul>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="rmIds = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger" type="button" data-testid="remove-go" @click="doRemove">{{ $t('net.m.remove') }}</button>
        </div>
      </div>
    </div>
  </main>
</template>
