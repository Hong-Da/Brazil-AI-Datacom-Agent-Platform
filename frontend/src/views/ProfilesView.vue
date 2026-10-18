<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { download, errorText, get } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import CompareTab from './profiles/CompareTab.vue'
import EntryEditor from './profiles/EntryEditor.vue'
import NewProfileDialog from './profiles/NewProfileDialog.vue'
import { domainsOf, entryOrigin, filterEntries, hasDefault, type EntryFilter } from './profiles/entries'
import HiddenLegend from '@/components/hidden-legend.vue'
import ShowDefaultToggle from '@/components/show-default-toggle.vue'
import { rememberedFlag } from '@/stores/prefs'
import { useTerms } from '@/stores/terms'
import { styleForm } from './schema/styles'
import { credPercents, formatDefault, pct, treeOrder, vendorBadge, vendorName } from './profiles/format'
import type { Entry, ProfileDetail, ProfileList } from './profiles/types'

const route = useRoute()
const router = useRouter()
const status = useStatus()
const { t } = useI18n()
const terms = useTerms()
/** 默认值列（REQ-028）：Profile 管理就是维护缺省值的地方，默认显示；选择每个浏览器记住 */
const showDefault = rememberedFlag('profiles-default', true)

const tab = ref<'list' | 'cmp'>(route.query.tab === 'cmp' ? 'cmp' : 'list')
const list = ref<ProfileList | null>(null)
const listErr = ref('')
const selId = ref(String(route.query.profile || ''))
const detail = ref<ProfileDetail | null>(null)
const parentDetail = ref<ProfileDetail | null>(null)
const detailErr = ref('')
const loadingDetail = ref(false)
const selNode = ref(String(route.query.node || ''))
const filter = reactive<EntryFilter>({ q: '', domain: '', origin: '', cred: '', showDeprecated: false })
const showNew = ref(false)
const exporting = ref(false)
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined

function say(msg: string) {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 2600)
}
onBeforeUnmount(() => clearTimeout(toastTimer))

async function loadList() {
  listErr.value = ''
  try {
    list.value = await get<ProfileList>('/kb/profiles')
    if (!list.value.profiles.some((p) => p.id === selId.value)) selId.value = list.value.profiles[0]?.id ?? ''
  } catch (e) {
    listErr.value = errorText(e)
  }
}

async function loadDetail(keepNode = true) {
  if (!selId.value) { detail.value = null; return }
  const id = selId.value
  loadingDetail.value = true
  detailErr.value = ''
  try {
    const d = await get<ProfileDetail>(`/kb/profiles/${encodeURIComponent(id)}`)
    const parent = d.profile.inherits ? await get<ProfileDetail>(`/kb/profiles/${encodeURIComponent(d.profile.inherits)}`) : null
    if (id !== selId.value) return
    detail.value = d
    parentDetail.value = parent
    if (!keepNode || !d.entries.some((e) => e.node === selNode.value)) selNode.value = ''
  } catch (e) {
    detailErr.value = errorText(e)
  } finally {
    loadingDetail.value = false
  }
}

let ready = false
onMounted(async () => {
  await loadList()
  await loadDetail()
  ready = true
})

watch(selId, () => { if (ready) loadDetail(false) })
watch([tab, selId, selNode], () => {
  const query = { ...route.query, tab: tab.value === 'cmp' ? 'cmp' : undefined, profile: selId.value || undefined, node: selNode.value || undefined }
  router.replace({ query })
})

const profiles = computed(() => treeOrder(list.value?.profiles ?? []))
const selProfile = computed(() => profiles.value.find((p) => p.id === selId.value))
const parentMap = computed(() => new Map<string, Entry>((parentDetail.value?.entries ?? []).map((e) => [e.node, e])))
const entries = computed(() => detail.value?.entries ?? [])
const domains = computed(() => domainsOf(entries.value))
const formOf = (e: Entry) => styleForm(terms, e.node, e.type, terms.style)
const shown = computed(() => filterEntries(entries.value, filter, parentMap.value, formOf))
const defaultCount = computed(() => entries.value.filter(hasDefault).length)
const selEntry = computed(() => entries.value.find((e) => e.node === selNode.value))
const liveCount = computed(() => entries.value.filter((e) => !e.deprecated || filter.showDeprecated).length)

function originLabel(e: Entry): string {
  const o = entryOrigin(e, parentMap.value)
  if (o === 'override') return t('profiles.overridden')
  if (o === 'own') return t('profiles.thisProfile')
  if (o === 'inherited') return t('profiles.inheritedFrom', { p: e.origin ?? '' })
  return '—'
}

async function onChanged(msg: string) {
  say(msg)
  await Promise.all([loadDetail(), loadList()])
  status.refresh()
}

async function onCreated(id: string) {
  showNew.value = false
  say(t('profiles.createdMsg', { p: id }))
  await loadList()
  selId.value = id
  tab.value = 'list'
  status.refresh()
}

async function exportKb() {
  exporting.value = true
  try {
    await download('/kb/export', `lmesh-kb-${status.summary?.kb.version || 'draft'}.zip`)
  } catch (e) {
    say(errorText(e))
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('profiles.title') }}</h1>
          <p class="ph-sub">{{ $t('profiles.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" :disabled="exporting" :title="$t('profiles.exportKbHint')" data-testid="profiles-export-kb" @click="exportKb">
            <Icon name="download" small />{{ $t('profiles.exportKb') }}
          </button>
          <button class="btn btn-primary" :disabled="!list" data-testid="profiles-new" @click="showNew = true">
            <Icon name="plus" small />{{ $t('profiles.newProfile') }}
          </button>
        </div>
      </div>

      <div class="tabs" role="tablist">
        <button role="tab" :aria-selected="tab === 'list'" data-testid="tab-list" @click="tab = 'list'">{{ $t('profiles.tabList') }}</button>
        <button role="tab" :aria-selected="tab === 'cmp'" data-testid="tab-compare" @click="tab = 'cmp'">{{ $t('profiles.tabCompare') }}</button>
      </div>

      <div v-if="listErr" class="notice err" style="margin-bottom:14px" data-testid="profiles-error">
        <Icon name="err" /><div class="grow small">{{ listErr }}</div>
        <button class="btn btn-xs" @click="loadList().then(() => loadDetail())">{{ $t('c.retry') }}</button>
      </div>
      <div v-else-if="!list" class="panel"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>
      <div v-else-if="!profiles.length" class="panel">
        <div class="empty">
          <h3>{{ $t('profiles.noProfiles') }}</h3>
          <p>{{ $t('profiles.noProfilesHint') }}</p>
          <button class="btn btn-sm btn-primary" @click="showNew = true"><Icon name="plus" small />{{ $t('profiles.newProfile') }}</button>
        </div>
      </div>

      <!-- ============ 列表与条目 ============ -->
      <section v-else-if="tab === 'list'">
        <div class="panel">
          <div class="tbl-wrap">
            <table class="tbl pf-tbl" data-testid="profiles-table">
              <thead><tr>
                <th>Profile</th>
                <th>{{ $t('profiles.vendor') }}</th>
                <th class="col-plat">{{ $t('profiles.platform') }}</th>
                <th>{{ $t('profiles.software') }}</th>
                <th>{{ $t('profiles.entries') }}</th>
                <th>{{ $t('profiles.coverage') }}</th>
                <th>{{ $t('profiles.credDist') }}</th>
                <th class="col-dev">{{ $t('profiles.devices') }}</th>
              </tr></thead>
              <tbody>
                <tr v-for="p in profiles" :key="p.id" :class="['pf-row', { 'is-sel': p.id === selId }]" :data-testid="`profile-row-${p.id}`" @click="selId = p.id">
                  <td>
                    <div class="pf-name">
                      <span v-if="p.inherits" class="tree-l"></span>
                      <span :title="p.title">{{ p.id }}</span>
                      <span v-if="p.inherits" class="tag inherited" :title="$t('profiles.inheritsFrom', { p: p.inherits })">{{ $t('profiles.inherits', { p: p.inherits }) }}</span>
                    </div>
                  </td>
                  <td><span class="vendor"><i :class="vendorBadge(p.vendor).cls">{{ vendorBadge(p.vendor).text }}</i>{{ vendorName(p.vendor) }}</span></td>
                  <td class="col-plat trunc-cell" :title="p.platform">{{ p.platform || '—' }}</td>
                  <td class="mono">{{ p.software || '—' }}</td>
                  <td class="num">
                    {{ p.entries }}
                    <span v-if="p.inherits && !p.own_entries" class="tag t-amber ui-font">{{ $t('profiles.noOwnYet') }}</span>
                    <span v-else-if="p.inherits" class="faint small">({{ $t('profiles.own', { n: p.own_entries }) }})</span>
                  </td>
                  <td>
                    <div class="meter" :title="$t('profiles.unfilledN', { n: p.unfilled })">
                      <div class="bar"><i :style="{ width: pct(p.coverage) + '%' }" :class="{ a: p.coverage < 0.85 }"></i></div>
                      <span class="val">{{ pct(p.coverage) }}%</span>
                    </div>
                  </td>
                  <td>
                    <div class="stackbar credbar" :title="`verified ${p.credibility.verified} · reviewed ${p.credibility.reviewed} · draft ${p.credibility.draft} · ${$t('st.unfilled')} ${p.unfilled}`">
                      <i :style="{ width: credPercents(p).verified + '%', background: 'var(--teal)' }"></i>
                      <i :style="{ width: credPercents(p).reviewed + '%', background: 'var(--blue)' }"></i>
                      <i :style="{ width: credPercents(p).draft + '%', background: 'var(--amber)' }"></i>
                    </div>
                  </td>
                  <td class="num col-dev">{{ p.devices }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="panel-f small faint">
            <span class="legend">
              <span><i style="background:var(--teal)"></i>verified</span>
              <span><i style="background:var(--blue)"></i>reviewed</span>
              <span><i style="background:var(--amber)"></i>draft</span>
              <span><i style="background:var(--surface-3);border:1px solid var(--line-strong)"></i>{{ $t('st.unfilled') }}</span>
            </span>
          </div>
        </div>

        <div v-if="selProfile && selProfile.inherits && !selProfile.own_entries" class="notice info mt16" data-testid="profile-fresh">
          <Icon name="info" />
          <div class="grow small">{{ $t('profiles.freshHint', { p: selProfile.inherits }) }}</div>
          <router-link class="btn btn-xs btn-primary" :to="{ name: 'ingest' }">{{ $t('profiles.importDocs') }}</router-link>
        </div>

        <div class="entry-layout mt16">
          <div class="panel">
            <div class="panel-h">
              <h2>{{ $t('profiles.entries') }} <span class="mono faint" style="font-weight:400">{{ selId }}</span></h2>
            </div>
            <div class="panel-b" style="padding:10px 14px">
              <div class="toolbar">
                <label class="input-wrap"><Icon name="search" small /><input v-model="filter.q" class="input" type="search" :placeholder="$t('profiles.filterPh')" data-testid="entries-q"></label>
                <select v-model="filter.domain" class="select" data-testid="entries-domain">
                  <option value="">{{ $t('profiles.allDomains') }}</option>
                  <option v-for="d in domains" :key="d" :value="d">{{ d }}</option>
                </select>
                <select v-model="filter.origin" class="select" data-testid="entries-origin">
                  <option value="">{{ $t('profiles.allOrigins') }}</option>
                  <option value="own">{{ $t('profiles.originOwn') }}</option>
                  <option value="inherited">{{ $t('src.inherited') }}</option>
                  <option value="unfilled">{{ $t('st.unfilled') }}</option>
                </select>
                <select v-model="filter.cred" class="select" data-testid="entries-cred">
                  <option value="">draft / reviewed / verified</option>
                  <option value="draft">draft</option>
                  <option value="reviewed">reviewed</option>
                  <option value="verified">verified</option>
                </select>
                <label class="check"><input v-model="filter.showDeprecated" type="checkbox"><span>{{ $t('profiles.showDeprecated') }}</span></label>
                <ShowDefaultToggle v-model="showDefault" :count="defaultCount" testid="entries-show-default" />
                <span class="grow"></span>
                <span class="small faint" data-testid="entries-count">{{ shown.length }} / {{ liveCount }}</span>
              </div>
            </div>
            <div v-if="showDefault" class="ent-legend small faint"><HiddenLegend :derived="false" /><span>{{ $t('profiles.defaultLegend') }}</span></div>
            <div v-if="detailErr" class="notice err" style="margin:0 14px 14px">
              <Icon name="err" /><div class="grow small">{{ detailErr }}</div>
              <button class="btn btn-xs" @click="loadDetail()">{{ $t('c.retry') }}</button>
            </div>
            <div class="tbl-wrap" style="max-height:560px">
              <table class="tbl" data-testid="entries-table">
                <thead><tr>
                  <th>{{ $t('profiles.schemaNode') }}</th>
                  <th>{{ $t('profiles.supported') }}</th>
                  <th v-if="showDefault">{{ $t('profiles.default') }}</th>
                  <th class="col-sr">{{ $t('profiles.showRule') }}</th>
                  <th>{{ $t('profiles.origin') }}</th>
                  <th>{{ $t('profiles.credibility') }}</th>
                </tr></thead>
                <tbody>
                  <tr v-if="loadingDetail && !detail"><td :colspan="showDefault ? 6 : 5"><div class="empty"><p>{{ $t('c.loading') }}</p></div></td></tr>
                  <tr v-else-if="detail && !shown.length"><td :colspan="showDefault ? 6 : 5"><div class="empty"><p>{{ $t('profiles.noMatch') }}</p></div></td></tr>
                  <tr v-for="e in shown" :key="e.node" :class="['ent-row', { 'is-sel': e.node === selNode, dep: e.deprecated }]" :data-testid="`entry-row-${e.node}`" @click="selNode = e.node">
                    <td class="sch" :title="formOf(e) ? `${$t(`style.${terms.style}`)}: ${formOf(e)}` : undefined">
                      <span>{{ e.node }}</span>
                      <span v-if="formOf(e)" class="ent-form" data-testid="entry-form">{{ formOf(e) }}</span>
                    </td>
                    <td>
                      <span v-if="e.state === 'supported'" class="supmark yes"><Icon name="check" small /></span>
                      <span v-else-if="e.state === 'unsupported'" class="supmark no"><Icon name="x" small /></span>
                      <span v-else class="tag unfilled">{{ $t('st.unfilled') }}</span>
                    </td>
                    <td v-if="showDefault">
                      <span v-if="hasDefault(e)" class="dval hid-default" :title="$t('hid.defaultTip')" data-testid="entry-default-val"><span class="mono">{{ formatDefault(e.default) }}</span><span class="tag default">{{ $t('hid.default') }}</span></span>
                      <span v-else class="mono faint">{{ e.state === 'unfilled' ? '' : '—' }}</span>
                    </td>
                    <td class="mono small col-sr">{{ e.show_rule || '' }}</td>
                    <td>
                      <span :class="entryOrigin(e, parentMap) === 'inherited' ? 'origin-inh' : 'origin-own'">{{ originLabel(e) }}</span>
                    </td>
                    <td><span v-if="e.credibility" :class="['tag', e.credibility]">{{ e.credibility }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <EntryEditor
            v-if="selEntry && detail"
            :profile-id="detail.profile.id"
            :entry="selEntry"
            :parent-id="detail.profile.inherits"
            :parent-entries="parentMap"
            :show-rules="detail.show_rules"
            @changed="onChanged"
          />
          <aside v-else-if="detail" class="panel editor-empty">
            <div class="empty"><Icon name="sliders" /><p>{{ $t('profiles.pickEntry') }}</p></div>
          </aside>
        </div>
      </section>

      <!-- ============ Profile 对比 ============ -->
      <CompareTab v-else :profiles="profiles" :initial="selId" />
    </div>

    <NewProfileDialog v-if="showNew && list" :profiles="profiles" :families="list.families" @close="showNew = false" @created="onCreated" />
    <div v-if="toast" class="toast" role="status" data-testid="profiles-toast"><Icon name="ok" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
.pf-tbl td { vertical-align: middle; white-space: nowrap; }
.pf-name { display: flex; align-items: center; gap: 8px; font: 12.5px var(--font-mono); }
.pf-name .tree-l { width: 18px; height: 22px; border-left: 1.5px solid var(--line-strong); border-bottom: 1.5px solid var(--line-strong); border-radius: 0 0 0 4px; margin: -12px 0 0 6px; flex: none; }
.pf-row { cursor: pointer; }
.pf-row.is-sel td { background: var(--blue-soft); }
.pf-row.is-sel td:first-child { box-shadow: inset 3px 0 0 var(--blue); }
.credbar { width: 150px; }
.pf-tbl .meter { min-width: 100px; }
.trunc-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.ui-font { font-family: var(--font-ui); }
@media (max-width: 1100px) { .credbar { width: 70px; } .pf-tbl .col-dev, .pf-tbl .col-plat { display: none; } .pf-tbl .tag.t-amber { display: none; } }
.entry-layout { display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 14px; align-items: start; }
@media (max-width: 1500px) { .entry-layout { grid-template-columns: minmax(0, 1fr) 400px; } .col-sr { display: none; } }
@media (max-width: 1300px) { .entry-layout { grid-template-columns: minmax(0, 1fr) 380px; } }
@media (max-width: 1100px) { .entry-layout { grid-template-columns: minmax(0, 1fr); } }
.ent-row { cursor: pointer; }
.ent-row.is-sel td { background: var(--blue-soft); }
.ent-row.dep td { color: var(--ink-3); }
.ent-row.dep .sch { text-decoration: line-through; }
.ent-row .sch { font: 12px var(--font-mono); white-space: nowrap; }
.ent-row .sch > span { display: block; }
.ent-row .sch .ent-form { font-size: 11px; color: var(--ink-3); max-width: 340px; overflow: hidden; text-overflow: ellipsis; }
.ent-row.dep .sch .ent-form { text-decoration: none; }
.dval { display: inline-flex; align-items: center; gap: 6px; padding: 1px 4px 1px 6px; border-radius: 4px; }
.dval .tag { height: 17px; font-size: 10.5px; padding: 0 5px; }
.ent-legend { display: flex; align-items: center; gap: 10px; padding: 0 14px 8px; flex-wrap: wrap; }
.origin-own { color: var(--blue-ink); font-weight: 600; font-size: 12px; white-space: nowrap; }
.origin-inh { color: var(--teal-ink); font-size: 12px; white-space: nowrap; }
.supmark { font-size: 12px; display: inline-flex; gap: 4px; align-items: center; }
.supmark.no { color: var(--red-ink); }
.supmark.yes { color: var(--teal-ink); }
.editor-empty .empty { padding: 48px 20px; color: var(--ink-3); }
</style>
