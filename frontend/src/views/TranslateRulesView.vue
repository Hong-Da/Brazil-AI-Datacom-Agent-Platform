<script setup lang="ts">
/**
 * 翻译规则（REQ-032，预览 DevelopDocs/ui-preview/REQ-032/）：规则集列表、编辑（名称映射 / 命名规范 / 端口映射）、
 * 测试框（POST /translate-rules/match，由后端计算）、试运行（POST /translate-rules/test）、导入导出。
 * 内置规则集只读，可另存为；登录用户都可以保存自己的规则集（D-0135）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { ApiError, del, download, errorText, get, post, put } from '@/api'
import type { Device } from '@/views/devices/logic'
import NamingReportPanel from './translate-rules/NamingReportPanel.vue'
import {
  SECTIONS, blankRules, copyId, issueAt, move, newNameRule, newNamingRule, newPortRule, normalize, titleOf, toSave, validId,
  type Issue, type MatchResult, type NamingReport, type RuleSetDetail, type RuleSetInfo, type Rules, type Section, type TypeInfo,
} from './translate-rules/logic'

interface ProfileLite { id: string; title: string; vendor: string; family: string }

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))

// ---------------------------------------------------------------- 列表与基础数据
const items = ref<RuleSetInfo[]>([])
const types = ref<TypeInfo[]>([])
const profiles = ref<ProfileLite[]>([])
const devices = ref<Device[]>([])
const loadError = ref('')
const families = computed(() => [...new Set(profiles.value.map((p) => p.family))].sort())
const typeTitle = (id: string) => {
  const x = types.value.find((y) => y.id === id)
  return x ? `${(x.title as Record<string, string>)[lang.value] || x.title['zh-CN'] || id}` : id
}

async function loadList(): Promise<void> {
  loadError.value = ''
  try {
    const r = await get<{ items: RuleSetInfo[]; types: TypeInfo[] }>('/translate-rules')
    items.value = r.items
    types.value = r.types
  } catch (e) {
    loadError.value = errorText(e)
  }
}
async function loadBase(): Promise<void> {
  try {
    const [p, d] = await Promise.all([get<{ profiles: ProfileLite[] }>('/kb/profiles'), get<{ devices: Device[] }>('/devices')])
    profiles.value = p.profiles
    devices.value = d.devices
  } catch { /* 试运行的下拉框为空时可以粘贴配置 */ }
}

// ---------------------------------------------------------------- 当前规则集
const current = ref<RuleSetDetail | null>(null)
const rules = ref<Rules>(blankRules())
const isNew = ref(false)
const newId = ref('')
const dirty = ref(false)
const busy = ref(false)
const notice = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const issues = ref<Issue[]>([])
const showYaml = ref(false)
const readonly = computed(() => !isNew.value && !!current.value?.builtin)
const editId = computed(() => (isNew.value ? newId.value.trim() : current.value?.id ?? ''))

async function open(id: string): Promise<void> {
  if (dirty.value && !confirm(t('translate-rules.discard'))) return
  notice.value = null
  issues.value = []
  try {
    const d = await get<RuleSetDetail>(`/translate-rules/${encodeURIComponent(id)}`)
    current.value = d
    rules.value = normalize(d.rules)
    isNew.value = false
    dirty.value = false
    report.value = null
    void router.replace({ query: { id } })
  } catch (e) {
    notice.value = { kind: 'err', text: errorText(e) }
  }
}
function startNew(from?: Rules): void {
  if (dirty.value && !confirm(t('translate-rules.discard'))) return
  current.value = null
  isNew.value = true
  const taken = items.value.map((i) => i.id)
  newId.value = from ? copyId(from.id, taken) : ''
  rules.value = from ? normalize({ ...JSON.parse(JSON.stringify(from)), id: newId.value }) : blankRules()
  dirty.value = !!from
  issues.value = []
  notice.value = null
  report.value = null
  void router.replace({ query: { new: '1' } })
}
watch(rules, () => { dirty.value = true }, { deep: true, flush: 'sync' })

async function save(): Promise<void> {
  const id = editId.value
  if (!validId(id)) {
    notice.value = { kind: 'err', text: t('translate-rules.badId') }
    return
  }
  busy.value = true
  issues.value = []
  notice.value = null
  try {
    const d = await put<RuleSetDetail>(`/translate-rules/${encodeURIComponent(id)}`, { rules: toSave(rules.value) })
    await loadList()
    current.value = d
    rules.value = normalize(d.rules)
    isNew.value = false
    dirty.value = false
    notice.value = { kind: 'ok', text: t('translate-rules.saved', { id }) }
    void router.replace({ query: { id } })
  } catch (e) {
    if (e instanceof ApiError && e.data && Array.isArray((e.data as { issues?: Issue[] }).issues)) issues.value = (e.data as { issues: Issue[] }).issues
    notice.value = { kind: 'err', text: errorText(e) }
  } finally {
    busy.value = false
  }
}
async function remove(): Promise<void> {
  const id = current.value?.id
  if (!id || current.value?.builtin || !confirm(t('translate-rules.confirmDelete', { id }))) return
  try {
    await del(`/translate-rules/${encodeURIComponent(id)}`)
    current.value = null
    rules.value = blankRules()
    dirty.value = false
    await loadList()
    void router.replace({ query: {} })
  } catch (e) {
    notice.value = { kind: 'err', text: errorText(e) }
  }
}
async function exportYaml(): Promise<void> {
  if (current.value) await download(`/translate-rules/${encodeURIComponent(current.value.id)}/export`, `${current.value.id}.yaml`)
}
const fileInput = ref<HTMLInputElement>()
async function importFile(ev: Event): Promise<void> {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  try {
    const info = await post<RuleSetInfo>('/translate-rules/import', { source: await f.text() })
    await loadList()
    await open(info.id)
  } catch (e) {
    if (e instanceof ApiError && e.data && Array.isArray((e.data as { issues?: Issue[] }).issues)) issues.value = (e.data as { issues: Issue[] }).issues
    notice.value = { kind: 'err', text: errorText(e) }
  } finally {
    if (fileInput.value) fileInput.value.value = ''
  }
}

const issueIn = (sec: Section, i: number, field: string) =>
  issues.value.some((x) => { const a = issueAt(x.where); return a.section === sec && a.index === i && (!field || a.field.startsWith(field)) })
const issueText = (x: Issue) => `${x.where}: ${t(`translate-rules.issue.${x.key.replace('naming.issue.', '')}`, x.args as Record<string, string>)}`

// ---------------------------------------------------------------- 页签与规则行
const tab = ref<Section>('names')
function add(): void {
  if (tab.value === 'names') rules.value.names.push(newNameRule())
  else if (tab.value === 'naming') rules.value.naming.push(newNamingRule())
  else rules.value.ports.push(newPortRule())
}
function moveRow(i: number, d: -1 | 1): void {
  if (tab.value === 'names') rules.value.names = move(rules.value.names, i, d)
  else if (tab.value === 'naming') rules.value.naming = move(rules.value.naming, i, d)
  else rules.value.ports = move(rules.value.ports, i, d)
}
function removeRow(i: number): void {
  rules.value[tab.value].splice(i, 1)
}
const rangeText = (r: [number, number] | null) => (r ? `${r[0]}-${r[1]}` : '')
function setRange(i: number, v: string): void {
  const m = /^\s*(\d+)\s*[-–~]\s*(\d+)\s*$/.exec(v)
  rules.value.ports[i].range = m ? [Number(m[1]), Number(m[2])] : null
}
const numOrNull = (v: string) => (v.trim() === '' || Number.isNaN(Number(v)) ? null : Number(v))

// ---------------------------------------------------------------- 测试框（后端计算）
const testValue = ref('')
const testType = ref('*')
const testTo = ref('')
const match = ref<MatchResult | null>(null)
const matchError = ref('')
let matchTimer = 0
function scheduleMatch(): void {
  window.clearTimeout(matchTimer)
  matchTimer = window.setTimeout(runMatch, 350)
}
async function runMatch(): Promise<void> {
  match.value = null
  matchError.value = ''
  if (!testValue.value.trim()) return
  try {
    match.value = await post<MatchResult>('/translate-rules/match', {
      rules: toSave(rules.value), kind: tab.value === 'ports' ? 'port' : 'name', type: testType.value, value: testValue.value, to: testTo.value || null,
    })
  } catch (e) {
    matchError.value = errorText(e)
  }
}
watch([testValue, testType, testTo, tab, rules], scheduleMatch, { deep: true })
const matchRule = computed(() => {
  const m = match.value
  if (!m || m.rule === null) return t('translate-rules.noHit')
  return t(`translate-rules.ruleRef.${m.kind === 'port' ? 'ports' : 'names'}`, { n: m.rule + 1 })
})

// ---------------------------------------------------------------- 试运行
const runDevice = ref<number | null>(null)
const runText = ref('')
const runTo = ref('')
const running = ref(false)
const runError = ref('')
const report = ref<NamingReport | null>(null)
async function dryRun(): Promise<void> {
  running.value = true
  runError.value = ''
  try {
    const body: Record<string, unknown> = { rules: toSave(rules.value), to: runTo.value || null }
    if (runText.value.trim()) body.text = runText.value
    else body.device_id = runDevice.value
    report.value = await post<NamingReport>('/translate-rules/test', body)
  } catch (e) {
    runError.value = errorText(e)
    if (e instanceof ApiError && e.data && Array.isArray((e.data as { issues?: Issue[] }).issues)) issues.value = (e.data as { issues: Issue[] }).issues
  } finally {
    running.value = false
  }
}

const builtin = computed(() => items.value.filter((i) => i.builtin))
const mine = computed(() => items.value.filter((i) => !i.builtin))
const counts = computed(() => ({ names: rules.value.names.length, naming: rules.value.naming.length, ports: rules.value.ports.length }))

onMounted(async () => {
  await Promise.all([loadList(), loadBase()])
  if (devices.value.length) runDevice.value = devices.value[0].id
  const q = route.query
  if (q.id) await open(String(q.id))
  else if (q.new) startNew()
  else if (items.value.length) await open(items.value[0].id)
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.tpl') }}</span><span class="sep">/</span><span>{{ $t('nav.translate-rules') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('translate-rules.title') }}</h1>
          <p class="ph-sub">{{ $t('translate-rules.sub') }}</p>
        </div>
        <div class="ph-actions">
          <input ref="fileInput" type="file" accept=".yaml,.yml" hidden data-testid="trs-import-file" @change="importFile">
          <button class="btn" type="button" data-testid="trs-import" @click="fileInput?.click()"><Icon name="upload" small />{{ $t('translate-rules.import') }}</button>
          <button class="btn btn-primary" type="button" data-testid="trs-new" @click="startNew()"><Icon name="plus" small />{{ $t('translate-rules.new') }}</button>
        </div>
      </div>
      <div v-if="loadError" class="notice err" style="margin-bottom: 12px"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="loadList">{{ $t('c.retry') }}</button></div>

      <div class="layout">
        <!-- 列表 -->
        <aside class="panel list" data-testid="trs-list">
          <div class="panel-h"><h2>{{ $t('translate-rules.sets') }}</h2><span class="meta">{{ items.length }}</span></div>
          <div v-for="grp in [{ k: 'builtin', rows: builtin }, { k: 'mine', rows: mine }]" :key="grp.k" class="grp">
            <div class="grp-h">{{ $t(`translate-rules.${grp.k}`) }}</div>
            <div v-if="!grp.rows.length" class="small faint pad">{{ grp.k === 'mine' ? $t('translate-rules.noMine') : '—' }}</div>
            <button
              v-for="i in grp.rows" :key="i.id" type="button" class="item" :aria-current="current?.id === i.id && !isNew" :data-testid="`trs-item-${i.id}`"
              @click="open(i.id)"
            >
              <span class="it">{{ titleOf(i, lang) }}</span>
              <span class="mono small faint">{{ i.id }}</span>
              <span class="small faint">
                <template v-if="i.valid !== false">{{ i.from || '*' }} → {{ i.to || '*' }} · {{ i.counts?.names ?? 0 }} / {{ i.counts?.naming ?? 0 }} / {{ i.counts?.ports ?? 0 }}</template>
                <span v-else class="tag fail">{{ $t('translate-rules.invalidN', { n: i.issues?.length ?? 0 }) }}</span>
              </span>
            </button>
          </div>
        </aside>

        <!-- 编辑 -->
        <section v-if="current || isNew" class="panel editor" data-testid="trs-editor">
          <div class="ed-h">
            <div class="ed-id">
              <template v-if="isNew">
                <label class="small" for="trs-id">{{ $t('translate-rules.id') }}</label>
                <input id="trs-id" v-model="newId" class="input mono" :class="{ 'is-error': newId && !validId(newId) }" placeholder="my-rules" data-testid="trs-id">
              </template>
              <template v-else>
                <h2>{{ titleOf(current!, lang) }}</h2>
                <span class="mono small faint">{{ current!.id }}</span>
                <span v-if="current!.builtin" class="tag default"><Icon name="lock" small />{{ $t('translate-rules.readonly') }}</span>
              </template>
            </div>
            <div class="ed-act">
              <button class="btn btn-sm" type="button" :aria-pressed="showYaml" data-testid="trs-yaml" :disabled="isNew" @click="showYaml = !showYaml"><Icon name="file" small />YAML</button>
              <button v-if="!isNew" class="btn btn-sm" type="button" data-testid="trs-export" @click="exportYaml"><Icon name="download" small />{{ $t('translate-rules.export') }}</button>
              <button v-if="!isNew" class="btn btn-sm" type="button" data-testid="trs-saveas" @click="startNew(rules)"><Icon name="copy" small />{{ $t('translate-rules.saveAs') }}</button>
              <button v-if="!isNew && !current?.builtin" class="btn btn-sm" type="button" data-testid="trs-delete" @click="remove"><Icon name="trash" small />{{ $t('c.delete') }}</button>
              <button class="btn btn-primary btn-sm" type="button" :disabled="readonly || busy" data-testid="trs-save" @click="save"><Icon name="check" small />{{ $t('c.save') }}</button>
            </div>
          </div>
          <div v-if="notice" class="notice" :class="notice.kind" data-testid="trs-notice"><Icon :name="notice.kind === 'ok' ? 'ok' : 'err'" /><div class="grow">{{ notice.text }}</div></div>
          <ul v-if="issues.length" class="issues" data-testid="trs-issues"><li v-for="(x, i) in issues" :key="i">{{ issueText(x) }}</li></ul>

          <pre v-if="showYaml && current" class="yaml" data-testid="trs-yaml-text">{{ current.source }}</pre>

          <fieldset class="meta-f" :disabled="readonly">
            <label><span>{{ $t('translate-rules.titleF') }}</span><input v-model="rules.title[lang as 'zh-CN']" class="input" data-testid="trs-title"></label>
            <label><span>{{ $t('translate-rules.from') }}</span>
              <select v-model="rules.from" class="select"><option :value="null">*</option><option v-for="f in families" :key="f" :value="f">{{ f }}</option></select>
            </label>
            <label><span>{{ $t('translate-rules.to') }}</span>
              <select v-model="rules.to" class="select"><option :value="null">*</option><option v-for="f in families" :key="f" :value="f">{{ f }}</option></select>
            </label>
          </fieldset>

          <div class="tabs" role="tablist">
            <button v-for="s in SECTIONS" :key="s" type="button" role="tab" :aria-selected="tab === s" :data-testid="`trs-tab-${s}`" @click="tab = s">
              {{ $t(`translate-rules.sec.${s}`) }}<span class="count">{{ counts[s] }}</span>
            </button>
          </div>
          <p class="small faint hint">{{ $t(`translate-rules.hint.${tab}`) }}</p>

          <div class="ed-body">
            <fieldset class="rules-f" :disabled="readonly">
              <!-- 名称映射 -->
              <table v-if="tab === 'names'" class="tbl compact" data-testid="trs-names">
                <thead><tr><th /><th>{{ $t('translate-rules.col.on') }}</th><th>{{ $t('translate-rules.col.type') }}</th><th>{{ $t('translate-rules.col.match') }}</th><th>{{ $t('translate-rules.col.from') }}</th><th>{{ $t('translate-rules.col.to') }}</th><th>Aa</th><th /></tr></thead>
                <tbody>
                  <tr v-for="(r, i) in rules.names" :key="i" :class="{ off: !r.enabled }">
                    <td class="ord"><span class="no">{{ i + 1 }}</span><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('translate-rules.up')" @click="moveRow(i, -1)"><Icon name="chevD" small class="up" /></button><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('translate-rules.down')" @click="moveRow(i, 1)"><Icon name="chevD" small /></button></td>
                    <td><label class="switch"><input v-model="r.enabled" type="checkbox"><span /></label></td>
                    <td><select v-model="r.type" class="select"><option value="*">{{ $t('translate-rules.allTypes') }}</option><option v-for="x in types" :key="x.id" :value="x.id">{{ typeTitle(x.id) }}</option></select></td>
                    <td><select v-model="r.match" class="select"><option v-for="m in ['exact', 'wildcard', 'regex']" :key="m" :value="m">{{ $t(`translate-rules.m.${m}`) }}</option></select></td>
                    <td><input v-model="r.from" class="input mono" :class="{ 'is-error': issueIn('names', i, 'from') }" :data-testid="`trs-name-from-${i}`"></td>
                    <td><input v-model="r.to" class="input mono" :class="{ 'is-error': issueIn('names', i, 'to') }" :data-testid="`trs-name-to-${i}`"></td>
                    <td><input v-model="r.ignore_case" type="checkbox" :title="$t('translate-rules.ignoreCase')"></td>
                    <td><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('c.delete')" @click="removeRow(i)"><Icon name="x" small /></button></td>
                  </tr>
                </tbody>
              </table>
              <!-- 命名规范 -->
              <table v-else-if="tab === 'naming'" class="tbl compact" data-testid="trs-naming">
                <thead><tr><th /><th>{{ $t('translate-rules.col.on') }}</th><th>{{ $t('translate-rules.col.type') }}</th><th>{{ $t('translate-rules.col.pattern') }}</th><th>{{ $t('translate-rules.col.fix') }}</th><th>{{ $t('translate-rules.col.actions') }}</th><th>{{ $t('translate-rules.col.max') }}</th><th /></tr></thead>
                <tbody>
                  <tr v-for="(r, i) in rules.naming" :key="i" :class="{ off: !r.enabled }">
                    <td class="ord"><span class="no">{{ i + 1 }}</span><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('translate-rules.up')" @click="moveRow(i, -1)"><Icon name="chevD" small class="up" /></button><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('translate-rules.down')" @click="moveRow(i, 1)"><Icon name="chevD" small /></button></td>
                    <td><label class="switch"><input v-model="r.enabled" type="checkbox"><span /></label></td>
                    <td><select v-model="r.type" class="select"><option value="*">{{ $t('translate-rules.allTypes') }}</option><option v-for="x in types" :key="x.id" :value="x.id">{{ typeTitle(x.id) }}</option></select></td>
                    <td><input v-model="r.pattern" class="input mono" :class="{ 'is-error': issueIn('naming', i, 'pattern') }" placeholder="RP_[A-Z0-9_]+"></td>
                    <td><label class="switch"><input v-model="r.fix" type="checkbox"><span /></label></td>
                    <td class="acts">
                      <select v-model="r.case" class="select" :disabled="!r.fix"><option v-for="c in ['keep', 'upper', 'lower']" :key="c" :value="c">{{ $t(`translate-rules.case.${c}`) }}</option></select>
                      <input v-model="r.prefix" class="input mono sm" :placeholder="$t('translate-rules.prefix')" :disabled="!r.fix">
                      <input v-model="r.suffix" class="input mono sm" :placeholder="$t('translate-rules.suffix')" :disabled="!r.fix">
                      <span v-for="(p, j) in r.replace" :key="j" class="rep"><input v-model="p.from" class="input mono xs" :disabled="!r.fix">→<input v-model="p.to" class="input mono xs" :disabled="!r.fix"><button type="button" class="btn btn-ghost btn-xs" @click="r.replace.splice(j, 1)"><Icon name="x" small /></button></span>
                      <button type="button" class="btn btn-ghost btn-xs" :disabled="!r.fix" @click="r.replace.push({ from: '', to: '' })"><Icon name="plus" small />{{ $t('translate-rules.replace') }}</button>
                      <label class="check small"><input v-model="r.truncate" type="checkbox" :disabled="!r.fix"><span>{{ $t('translate-rules.truncate') }}</span></label>
                    </td>
                    <td><input :value="r.max_length ?? ''" class="input mono xs" :placeholder="$t('translate-rules.maxAuto')" @input="r.max_length = numOrNull(($event.target as HTMLInputElement).value)"></td>
                    <td><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('c.delete')" @click="removeRow(i)"><Icon name="x" small /></button></td>
                  </tr>
                </tbody>
              </table>
              <!-- 端口映射 -->
              <table v-else class="tbl compact" data-testid="trs-ports">
                <thead><tr><th /><th>{{ $t('translate-rules.col.on') }}</th><th>{{ $t('translate-rules.col.match') }}</th><th>{{ $t('translate-rules.col.from') }}</th><th>{{ $t('translate-rules.col.to') }}</th><th>{{ $t('translate-rules.col.range') }}</th><th>{{ $t('translate-rules.col.speed') }}</th><th /></tr></thead>
                <tbody>
                  <tr v-for="(r, i) in rules.ports" :key="i" :class="{ off: !r.enabled }">
                    <td class="ord"><span class="no">{{ i + 1 }}</span><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('translate-rules.up')" @click="moveRow(i, -1)"><Icon name="chevD" small class="up" /></button><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('translate-rules.down')" @click="moveRow(i, 1)"><Icon name="chevD" small /></button></td>
                    <td><label class="switch"><input v-model="r.enabled" type="checkbox"><span /></label></td>
                    <td><select v-model="r.match" class="select"><option v-for="m in ['exact', 'pattern', 'type']" :key="m" :value="m">{{ $t(`translate-rules.pm.${m}`) }}</option></select></td>
                    <td><input v-model="r.from" class="input mono" :class="{ 'is-error': issueIn('ports', i, 'from') }" :placeholder="r.match === 'pattern' ? 'GigabitEthernet0/2/{n}' : r.match === 'type' ? '100GE' : 'GigabitEthernet0/2/0'" :data-testid="`trs-port-from-${i}`"></td>
                    <td><input v-model="r.to" class="input mono" :placeholder="r.match === 'pattern' ? 'GigabitEthernet0/0/{n+1}' : r.match === 'type' ? 'HundredGigE' : 'TenGigabitEthernet0/0/24'" :data-testid="`trs-port-to-${i}`"></td>
                    <td><input :value="rangeText(r.range)" class="input mono xs" placeholder="0-7" :disabled="r.match === 'exact'" @change="setRange(i, ($event.target as HTMLInputElement).value)"></td>
                    <td><input :value="r.speed ?? ''" class="input mono xs" placeholder="Gbps" @input="r.speed = numOrNull(($event.target as HTMLInputElement).value)"></td>
                    <td><button type="button" class="btn btn-ghost btn-xs" :aria-label="$t('c.delete')" @click="removeRow(i)"><Icon name="x" small /></button></td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!rules[tab].length" class="small faint pad">{{ $t('translate-rules.noRules') }}</div>
              <button type="button" class="btn btn-sm mt8" :data-testid="`trs-add-${tab}`" @click="add"><Icon name="plus" small />{{ $t('translate-rules.addRule') }}</button>
            </fieldset>

            <!-- 测试框 -->
            <aside class="tester" data-testid="trs-tester">
              <h3><Icon name="play" small />{{ $t('translate-rules.test') }}</h3>
              <div class="row wrap" style="gap: 6px">
                <select v-if="tab !== 'ports'" v-model="testType" class="select" :aria-label="$t('translate-rules.col.type')">
                  <option value="*">{{ $t('translate-rules.allTypes') }}</option>
                  <option v-for="x in types" :key="x.id" :value="x.id">{{ typeTitle(x.id) }}</option>
                </select>
                <select v-model="testTo" class="select" :aria-label="$t('translate-rules.target')">
                  <option value="">{{ $t('translate-rules.targetAuto') }}</option>
                  <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
                </select>
              </div>
              <input v-model="testValue" class="input mono mt8" :placeholder="tab === 'ports' ? 'GigabitEthernet0/2/3.100' : 'RAN-4G'" data-testid="trs-test-input">
              <div v-if="matchError" class="small" style="color: var(--red-ink)">{{ matchError }}</div>
              <div v-else-if="match" class="chain" data-testid="trs-test-result">
                <div><span class="k">{{ $t('translate-rules.hit') }}</span><span>{{ matchRule }}</span></div>
                <div v-if="match.kind === 'name'"><span class="k">{{ $t('translate-rules.mapped') }}</span><span class="mono">{{ match.mapped }}</span></div>
                <div v-if="match.fixes?.length"><span class="k">{{ $t('translate-rules.col.actions') }}</span><span>{{ match.fixes.map((f) => $t(`translate-rules.fix.${f}`)).join('、') }}</span></div>
                <div class="final"><span class="k">{{ $t('translate-rules.final') }}</span><b class="mono">{{ match.result }}</b></div>
                <div v-if="match.kind === 'name'" class="small faint">
                  {{ match.max_length ? $t('translate-rules.limit', { n: match.max_length, src: $t(`translate-rules.limitSrc.${match.limit_source}`) }) : $t('translate-rules.noLimit') }}
                </div>
                <div v-for="(p, i) in match.problems ?? []" :key="i" class="prob"><Icon name="warn" small />{{ p.problem === 'length' ? $t('translate-rules.problem.length', { name: match.result, length: p.length ?? 0, max: p.max_length ?? 0 }) : $t('translate-rules.problem.pattern', { name: match.result, pattern: p.pattern ?? '' }) }}</div>
              </div>
              <div v-else class="small faint">{{ $t('translate-rules.testHint') }}</div>
            </aside>
          </div>

          <!-- 试运行 -->
          <div class="dry" data-testid="trs-dry">
            <h3><Icon name="target" small />{{ $t('translate-rules.dryRun') }}</h3>
            <div class="row wrap" style="gap: 8px">
              <select v-model="runDevice" class="select" :aria-label="$t('translate-rules.device')" :disabled="!!runText.trim()" data-testid="trs-run-device">
                <option v-if="!devices.length" :value="null">{{ $t('translate-rules.noDevices') }}</option>
                <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}</option>
              </select>
              <select v-model="runTo" class="select" :aria-label="$t('translate-rules.target')" data-testid="trs-run-to">
                <option value="">{{ $t('translate-rules.targetAuto') }}</option>
                <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.id }}</option>
              </select>
              <button class="btn btn-primary btn-sm" type="button" :disabled="running || (!runText.trim() && runDevice === null)" data-testid="trs-run" @click="dryRun"><Icon name="play" small />{{ running ? $t('translate-rules.running') : $t('translate-rules.run') }}</button>
            </div>
            <textarea v-model="runText" class="textarea mono mt8" rows="3" :placeholder="$t('translate-rules.pastePh')" data-testid="trs-run-text" />
            <div v-if="runError" class="notice err mt8"><Icon name="err" /><div class="grow">{{ runError }}</div></div>
          </div>
          <NamingReportPanel v-if="report" :report="report" testid="trs-report" />
        </section>
        <div v-else class="empty"><Icon name="pencil" /><h3>{{ $t('translate-rules.emptyTitle') }}</h3><p>{{ $t('translate-rules.emptyText') }}</p></div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 14px; align-items: start; }
.list .grp { border-top: 1px solid var(--line); }
.list .grp-h { font-size: 11.5px; font-weight: 600; color: var(--ink-3); padding: 8px 12px 4px; text-transform: uppercase; letter-spacing: .02em; }
.list .pad { padding: 4px 12px 10px; }
.list .item { all: unset; box-sizing: border-box; width: 100%; cursor: pointer; display: flex; flex-direction: column; gap: 2px; padding: 8px 12px; border-left: 3px solid transparent; }
.list .item:hover { background: var(--surface-2); }
.list .item:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.list .item[aria-current="true"] { background: var(--teal-soft); border-left-color: var(--teal); }
.list .it { font-weight: 600; font-size: 13px; }
.editor { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; min-width: 0; }
.ed-h { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: space-between; }
.ed-id { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ed-id h2 { font-size: 16px; }
.ed-id .input { width: 220px; }
.ed-act { display: flex; gap: 6px; flex-wrap: wrap; }
.issues { margin: 0; padding: 8px 12px 8px 28px; border: 1px solid var(--red-line); background: var(--red-soft); color: var(--red-ink); border-radius: 6px; font-size: 12.5px; }
.yaml { margin: 0; max-height: 300px; overflow: auto; background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; font: 12px/1.5 var(--font-mono); white-space: pre; }
.meta-f { border: 0; padding: 0; margin: 0; display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.meta-f label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-2); }
.hint { margin: -6px 0 0; }
.ed-body { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 14px; align-items: start; }
.rules-f { border: 0; padding: 0; margin: 0; min-width: 0; overflow-x: auto; }
.rules-f .tbl { width: 100%; }
.rules-f .tbl td { vertical-align: middle; }
.rules-f .tbl .input, .rules-f .tbl .select { width: 100%; min-width: 120px; }
.rules-f .tbl .input.mono { min-width: 150px; }
.rules-f .tbl .input.sm { width: 76px; min-width: 76px; }
.rules-f .tbl .input.xs { width: 64px; min-width: 64px; }
.rules-f tr.off td { opacity: .55; }
.ord { white-space: nowrap; }
.ord .no { display: inline-block; width: 18px; text-align: right; font-size: 11.5px; color: var(--ink-3); margin-right: 2px; }
.ord :deep(.up) { transform: rotate(180deg); }
.acts { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; min-width: 260px; }
.acts .select { width: auto !important; }
.rep { display: inline-flex; gap: 2px; align-items: center; font-size: 11px; color: var(--ink-3); }
.pad { padding: 10px 2px; }
.tester { border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; position: sticky; top: 12px; }
.tester h3, .dry h3 { font-size: 13px; display: inline-flex; gap: 6px; align-items: center; }
.tester .select { flex: 1; min-width: 0; }
.chain { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
.chain > div { display: flex; gap: 8px; align-items: baseline; }
.chain .k { width: 76px; flex: none; color: var(--ink-3); font-size: 12px; }
.chain .final b { color: var(--teal-ink); font-size: 13.5px; }
.chain .prob { color: var(--amber-ink); gap: 4px; align-items: center; }
.dry { border-top: 1px solid var(--line); padding-top: 10px; }
.dry .textarea { width: 100%; font-size: 12px; }
.dry .select { width: auto; min-width: 220px; max-width: 100%; }
@media (max-width: 1500px) { .ed-body { grid-template-columns: minmax(0, 1fr); } .tester { position: static; } }
@media (max-width: 900px) { .layout { grid-template-columns: minmax(0, 1fr); } .meta-f { grid-template-columns: minmax(0, 1fr); } }
</style>
