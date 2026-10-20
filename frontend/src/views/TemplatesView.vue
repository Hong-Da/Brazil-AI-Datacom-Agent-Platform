<script setup lang="ts">
/**
 * 配置模板（预览 DevelopDocs/ui-preview/M3/templates.html）：模板列表（GET /templates）、模板详情（GET /templates/{id}）、
 * 编辑模板文件并保存（PUT /templates/{id}，有问题时 409 与问题清单）、校验配置（POST /templates/check）、从设备生成草稿（POST /templates/draft）。
 * M6（REQ-036，预览 DevelopDocs/ui-preview/M6/templates.html）：分“我的模板 / 共享模板”；共享模板对普通用户只读，
 * 可复制为我的模板（POST /templates/{id}/copy）或提建议（POST /kb/suggestions）；我的模板可删除；新建默认保存为我的模板。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { ApiError, del, errorText, get, post, put } from '@/api'
import { useAuth } from '@/stores/auth'
import KbSuggest from '@/components/kb-suggest.vue'
import { canEdit, copyId, initialTab, splitByTab, tabOf, validAssetId, type AssetTab } from './templates/scope'
import { pickLang } from '@/i18n'
import type { Device } from '@/views/devices/logic'
import { msg } from '@/views/m3/texts'
import TemplateTab from './templates/TemplateTab.vue'
import CheckTab from './templates/CheckTab.vue'
import DraftTab from './templates/DraftTab.vue'
import { skeleton } from './templates/logic'
import type { TemplateDetail, TemplateInfo, TemplateIssue } from './templates/types'
import VendorBadge from '@/components/vendor-badge.vue'

type Tab = 'text' | 'check' | 'draft'
interface ProfileLite { id: string; family: string; vendor: string }

const route = useRoute()
const auth = useAuth()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))
const title = (m: Record<string, string> | undefined) => pickLang(m, lang.value)

const list = ref<TemplateInfo[]>([])
const listLoading = ref(true)
const listError = ref('')
const devices = ref<Device[]>([])
const profiles = ref<ProfileLite[]>([])
const q = ref('')
const selId = ref<string | null>((route.query.id as string) || null)
const listTab = ref<AssetTab>('mine')
const tab = ref<Tab>(['text', 'check', 'draft'].includes(String(route.query.tab)) ? (route.query.tab as Tab) : 'text')

async function loadList(): Promise<void> {
  listLoading.value = true
  listError.value = ''
  try {
    list.value = (await get<{ templates: TemplateInfo[] }>('/templates')).templates
    if (!listLoaded) { listTab.value = initialTab(list.value, selId.value); listLoaded = true }
    const first = groups.value[listTab.value][0] ?? list.value[0]
    if (!selId.value && first && tab.value !== 'draft') selId.value = first.id
  } catch (e) {
    listError.value = errorText(e)
  } finally {
    listLoading.value = false
  }
}
let listLoaded = false
const groups = computed(() => splitByTab(list.value))
const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  const rows = groups.value[listTab.value]
  if (!s) return rows
  return rows.filter((x) => x.id.toLowerCase().includes(s) || Object.values(x.title ?? {}).some((v) => v.toLowerCase().includes(s)) || x.profile.includes(s))
})

// ---------------- 详情与编辑 ----------------
const detail = ref<TemplateDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const yaml = ref('')
const editing = ref(false)
const isNew = ref(false)
const newId = ref('')
const saving = ref(false)
const saveErr = ref('')
const issues = ref<TemplateIssue[]>([])
const savedMsg = ref('')
// 共享模板对普通用户只读；我的模板（与管理员看到的别人的模板）可以删除
const readonly = computed(() => !isNew.value && !!detail.value && !canEdit(detail.value))
const deletable = computed(() => !isNew.value && (detail.value?.scope === 'mine' || detail.value?.scope === 'user'))
const ownerOf = (id: string) => list.value.find((x) => x.id === id)?.owner ?? null
const newShared = ref(false)
const dirty = computed(() => (isNew.value ? !!yaml.value.trim() : !!detail.value && yaml.value !== detail.value.source))

async function loadDetail(id: string | null): Promise<void> {
  detail.value = null
  detailError.value = ''
  saveErr.value = ''
  issues.value = []
  savedMsg.value = ''
  editing.value = false
  if (!id) return
  detailLoading.value = true
  try {
    detail.value = await get<TemplateDetail>(`/templates/${encodeURIComponent(id)}`)
    yaml.value = detail.value.source
  } catch (e) {
    detailError.value = errorText(e)
  } finally {
    detailLoading.value = false
  }
}
watch(selId, (id) => {
  if (!isNew.value) void loadDetail(id)
  syncQuery()
})
watch(tab, syncQuery)
function syncQuery(): void {
  const qq: Record<string, string> = {}
  if (selId.value && !isNew.value) qq.id = selId.value
  if (tab.value !== 'text') qq.tab = tab.value
  void router.replace({ query: qq })
}

function pick(id: string): void {
  if (dirty.value && !window.confirm(t('templates.discard'))) return
  isNew.value = false
  if (tab.value === 'draft') tab.value = 'text'
  if (selId.value === id) void loadDetail(id)
  else selId.value = id
}
function startNew(): void {
  if (dirty.value && !window.confirm(t('templates.discard'))) return
  newShared.value = false
  const p = profiles.value[0]
  isNew.value = true
  detail.value = null
  newId.value = `new-template-${list.value.length + 1}`
  yaml.value = skeleton(newId.value, p?.id ?? '', p?.family ?? '')
  editing.value = true
  tab.value = 'text'
  saveErr.value = ''
  issues.value = []
  savedMsg.value = ''
}
function cancelEdit(): void {
  if (isNew.value) {
    isNew.value = false
    void loadDetail(selId.value)
    return
  }
  editing.value = false
  if (detail.value) yaml.value = detail.value.source
  saveErr.value = ''
  issues.value = []
}
async function save(): Promise<void> {
  const m = /^id:\s*(\S+)/m.exec(yaml.value)
  const id = (m ? m[1].replace(/^["']|["']$/g, '') : '') || detail.value?.id || newId.value
  saving.value = true
  saveErr.value = ''
  issues.value = []
  try {
    const shared = isNew.value && auth.isKbEditor && newShared.value
    await put(`/templates/${encodeURIComponent(id)}`, shared ? { source: yaml.value, shared: true } : { source: yaml.value })
    isNew.value = false
    await loadList()
    const saved = list.value.find((x) => x.id === id)
    if (saved) listTab.value = tabOf(saved)
    if (selId.value === id) await loadDetail(id)
    else selId.value = id
    savedMsg.value = t('templates.savedAs', { id })
  } catch (e) {
    saveErr.value = errorText(e)
    if (e instanceof ApiError && e.data && typeof e.data === 'object') issues.value = (e.data as { issues?: TemplateIssue[] }).issues ?? []
  } finally {
    saving.value = false
  }
}
// ---------------- 复制为我的模板、删除、提建议 ----------------
const copyOpen = ref(false)
const copyNew = ref('')
const copyBusy = ref(false)
const copyErr = ref('')
const delOpen = ref(false)
const delBusy = ref(false)
const delErr = ref('')
const suggestOpen = ref(false)
const toast = ref('')
function flash(m: string): void {
  toast.value = m
  setTimeout(() => { if (toast.value === m) toast.value = '' }, 2600)
}
function openCopy(): void {
  if (!detail.value) return
  copyNew.value = copyId(detail.value.id, list.value.map((x) => x.id))
  copyErr.value = ''
  copyOpen.value = true
}
async function doCopy(): Promise<void> {
  if (!detail.value || !validAssetId(copyNew.value)) return
  copyBusy.value = true
  copyErr.value = ''
  try {
    const id = copyNew.value.trim()
    await post(`/templates/${encodeURIComponent(detail.value.id)}/copy`, { new_id: id })
    copyOpen.value = false
    await loadList()
    listTab.value = 'mine'
    selId.value = id
    flash(t('templates.copied', { id }))
  } catch (e) {
    copyErr.value = errorText(e)
  } finally {
    copyBusy.value = false
  }
}
async function doDelete(): Promise<void> {
  if (!detail.value) return
  delBusy.value = true
  delErr.value = ''
  try {
    const id = detail.value.id
    await del(`/templates/${encodeURIComponent(id)}`)
    delOpen.value = false
    selId.value = null
    await loadList()
    flash(t('templates.deleted', { id }))
  } catch (e) {
    delErr.value = errorText(e)
  } finally {
    delBusy.value = false
  }
}
function onSuggested(id: number): void {
  suggestOpen.value = false
  flash(t('templates.suggested', { id }))
}

const issueText = (i: TemplateIssue) => `${i.where ? i.where + '：' : ''}${msg(i.key, i.args ?? {}, lang.value)}`
async function onDraftSaved(id: string): Promise<void> {
  await loadList()
  isNew.value = false
  selId.value = id
}

onMounted(async () => {
  const initial = selId.value
  await Promise.all([
    loadList(),
    get<{ devices: Device[] }>('/devices').then((d) => { devices.value = [...d.devices].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })) }).catch(() => {}),
    get<{ profiles: ProfileLite[] }>('/kb/profiles').then((p) => { profiles.value = p.profiles }).catch(() => {}),
  ])
  if (initial) void loadDetail(initial)
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.tpl') }}</span><span class="sep">/</span><span>{{ $t('nav.templates') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('templates.title') }}</h1>
          <p class="ph-sub">{{ $t('templates.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" type="button" data-testid="tpl-new" @click="startNew"><Icon name="plus" small />{{ $t('templates.new') }}</button>
          <button class="btn btn-primary" type="button" data-testid="tpl-todraft" @click="tab = 'draft'"><Icon name="wand" small />{{ $t('templates.toDraft') }}</button>
        </div>
      </div>

      <div class="tp">
        <section class="panel tlist" aria-label="Templates">
          <div class="panel-h"><h2>{{ $t('templates.list') }}</h2><span class="meta">{{ list.length }}</span></div>
          <div class="tabs scope-tabs" role="tablist" data-testid="tpl-scope-tabs">
            <button type="button" role="tab" :aria-selected="listTab === 'mine'" data-testid="tpl-scope-mine" @click="listTab = 'mine'">{{ $t('templates.tabMine') }} <span class="count">{{ groups.mine.length }}</span></button>
            <button type="button" role="tab" :aria-selected="listTab === 'shared'" data-testid="tpl-scope-shared" @click="listTab = 'shared'">{{ $t('templates.tabShared') }} <span class="count">{{ groups.shared.length }}</span></button>
          </div>
          <div class="panel-b">
            <p class="small faint scope-hint" data-testid="tpl-scope-hint">
              <template v-if="listTab === 'mine'">{{ $t('templates.hintMine') }}</template>
              <template v-else-if="auth.isKbEditor">{{ $t('templates.hintSharedEditor') }}</template>
              <template v-else><Icon name="lock" small /> {{ $t('templates.hintSharedRo') }}</template>
            </p>
            <label class="input-wrap" style="margin-bottom: 8px"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('templates.search')"></label>
            <div v-if="listLoading" class="empty small">{{ $t('c.loading') }}</div>
            <div v-else-if="listError" class="notice err"><Icon name="err" /><div class="grow">{{ listError }}</div><button class="btn btn-sm" type="button" @click="loadList">{{ $t('c.retry') }}</button></div>
            <div v-else-if="!groups[listTab].length" class="empty small" data-testid="tpl-empty">{{ listTab === 'mine' ? $t('templates.noMine') : $t('templates.noTemplates') }}</div>
            <div v-else data-testid="tpl-list">
              <div v-if="isNew" class="ti-row is-sel"><div class="nm">{{ $t('templates.newRow') }}</div><div class="id">{{ newId }}</div></div>
              <div
                v-for="x in shown" :key="x.id" class="ti-row" :class="{ 'is-sel': !isNew && x.id === selId && tab !== 'draft' }" tabindex="0" :data-tpl="x.id"
                data-testid="tpl-row" @click="pick(x.id)" @keydown.enter="pick(x.id)"
              >
                <div class="nm">{{ title(x.title) || x.id }}</div>
                <div class="id">{{ x.id }}</div>
                <div class="mt">
                  <span class="tag" :class="x.valid ? 'reviewed' : 'error'">v{{ x.version }}{{ x.valid ? '' : ` · ${$t('templates.invalid')}` }}</span>
                  <VendorBadge :of="x.family" />
                  <span>{{ $t('templates.varsN', { n: x.vars }) }}</span>
                  <span v-if="x.blocks">{{ $t('templates.blocksN', { n: x.blocks }) }}</span>
                  <span v-if="x.scope === 'user'" class="tag" :title="$t('templates.ownerTip')">{{ $t('templates.ownerIs', { u: x.owner ?? '—' }) }}</span>
                  <span v-else-if="x.scope === 'shared' && !canEdit(x)" class="ro-lock"><Icon name="lock" small /></span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel td" aria-label="Template" data-testid="tpl-detail">
          <template v-if="tab === 'draft'">
            <div class="td-h"><div style="flex: 1; min-width: 0"><h2>{{ $t('templates.toDraft') }}</h2><div class="id">{{ $t('templates.draftSub') }}</div></div></div>
            <div class="tabs" role="tablist">
              <button v-if="selId" type="button" role="tab" :aria-selected="false" @click="tab = 'text'">{{ $t('templates.tabText') }}</button>
              <button v-if="selId" type="button" role="tab" :aria-selected="false" @click="tab = 'check'">{{ $t('templates.tabCheck') }}</button>
              <button type="button" role="tab" :aria-selected="true">{{ $t('templates.tabDraft') }}</button>
            </div>
            <div class="td-b"><DraftTab :devices="devices" :profiles="profiles" @saved="onDraftSaved" @list-changed="loadList" /></div>
          </template>
          <template v-else-if="isNew || detail">
            <div class="td-h">
              <div style="flex: 1; min-width: 0">
                <h2>{{ isNew ? $t('templates.newRow') : title(detail?.title) || detail?.id }}</h2>
                <div v-if="detail && !isNew" class="id"><span>templates/{{ detail.file }}</span><span>v{{ detail.version }}</span><span>Profile {{ detail.profile }}</span><span v-if="detail.profiles.length">{{ $t('templates.applies') }} {{ detail.profiles.join(', ') }}</span></div>
                <p v-if="detail?.description && !isNew" class="small muted mt8">{{ title(detail.description) }}</p>
              </div>
              <div class="row wrap">
                <template v-if="!editing && !isNew && detail">
                  <span v-if="readonly" class="ro-lock" data-testid="tpl-readonly"><Icon name="lock" small />{{ $t('templates.readonly') }}</span>
                  <span v-else-if="detail.scope === 'user'" class="tag">{{ $t('templates.ownerIs', { u: ownerOf(detail.id) ?? '—' }) }}</span>
                  <button v-if="detail.scope !== 'mine'" class="btn btn-sm" type="button" data-testid="tpl-copy" @click="openCopy"><Icon name="copy" small />{{ $t('templates.copyMine') }}</button>
                  <button v-if="readonly" class="btn btn-sm btn-ghost" type="button" data-testid="tpl-suggest" @click="suggestOpen = true"><Icon name="pencil" small />{{ $t('templates.suggest') }}</button>
                  <button v-if="deletable" class="btn btn-sm btn-ghost btn-danger btn-icon" type="button" :title="$t('templates.delete')" :aria-label="$t('templates.delete')" data-testid="tpl-delete" @click="delErr = ''; delOpen = true"><Icon name="trash" small /></button>
                </template>
                <template v-if="editing || isNew">
                  <label v-if="isNew && auth.isKbEditor" class="check small" :title="$t('templates.sharedTip')"><input v-model="newShared" type="checkbox" data-testid="tpl-new-shared"> {{ $t('templates.saveShared') }}</label>
                  <span v-else-if="isNew" class="small faint">{{ $t('templates.saveMine') }}</span>
                  <button class="btn btn-sm" type="button" @click="cancelEdit">{{ $t('c.cancel') }}</button>
                  <button class="btn btn-sm btn-primary" type="button" :disabled="saving || !dirty" data-testid="tpl-save" @click="save"><Icon name="check" small />{{ saving ? $t('templates.saving') : $t('c.save') }}</button>
                </template>
              </div>
            </div>
            <div class="tabs" role="tablist">
              <button type="button" role="tab" :aria-selected="tab === 'text'" data-testid="tpl-tab-text" @click="tab = 'text'">{{ $t('templates.tabText') }}</button>
              <button type="button" role="tab" :aria-selected="tab === 'check'" :disabled="isNew" data-testid="tpl-tab-check" @click="tab = 'check'">{{ $t('templates.tabCheck') }}</button>
              <button type="button" role="tab" :aria-selected="false" data-testid="tpl-tab-draft" @click="tab = 'draft'">{{ $t('templates.tabDraft') }}</button>
            </div>
            <div class="td-b">
              <div v-if="saveErr" class="notice err" style="margin-bottom: 12px" data-testid="tpl-save-error"><Icon name="err" /><div class="grow">{{ saveErr }}<ul v-if="issues.length" class="issues"><li v-for="(i, k) in issues" :key="k">{{ issueText(i) }}</li></ul></div></div>
              <div v-if="savedMsg" class="notice ok" style="margin-bottom: 12px"><Icon name="ok" /><div>{{ savedMsg }}</div></div>
              <TemplateTab v-if="tab === 'text'" v-model:yaml="yaml" :detail="isNew ? null : detail" :editing="editing" :is-new="isNew" :readonly="readonly" @edit="(v) => (editing = v)" />
              <CheckTab v-else-if="tab === 'check' && detail" :detail="detail" :devices="devices" :yaml="yaml" :dirty="dirty" />
            </div>
          </template>
          <div v-else-if="detailLoading" class="empty">{{ $t('c.loading') }}</div>
          <div v-else-if="detailError" class="notice err" style="margin: 14px"><Icon name="err" /><div class="grow">{{ detailError }}</div><button class="btn btn-sm" type="button" @click="loadDetail(selId)">{{ $t('c.retry') }}</button></div>
          <div v-else class="empty"><Icon name="stencil" /><h3>{{ $t('templates.pick') }}</h3></div>
        </section>
      </div>
    </div>

    <div v-if="copyOpen && detail" class="modal-back" data-testid="tpl-copy-dialog" @click.self="copyOpen = false" @keydown.esc="copyOpen = false">
      <form class="modal" style="width: min(480px, 100%)" role="dialog" aria-modal="true" novalidate @submit.prevent="doCopy">
        <div class="modal-h"><h2>{{ $t('templates.copyTitle') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="copyOpen = false"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 12px">
          <p class="small muted">{{ $t('templates.copyNote', { id: detail.id }) }}</p>
          <div class="field">
            <label for="tplCopyId">{{ $t('templates.copyId') }}</label>
            <input id="tplCopyId" v-model="copyNew" class="input mono" spellcheck="false" data-testid="tpl-copy-id">
            <span v-if="copyNew && !validAssetId(copyNew)" class="hint" style="color: var(--red-ink)">{{ $t('templates.badId') }}</span>
          </div>
          <div v-if="copyErr" class="notice err"><Icon name="err" /><div class="grow small">{{ copyErr }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="copyOpen = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="submit" :disabled="copyBusy || !validAssetId(copyNew)" data-testid="tpl-copy-ok"><Icon name="copy" small />{{ $t('templates.copyMine') }}</button>
        </div>
      </form>
    </div>

    <div v-if="delOpen && detail" class="modal-back" data-testid="tpl-delete-dialog" @click.self="delOpen = false" @keydown.esc="delOpen = false">
      <div class="modal" style="width: min(440px, 100%)" role="dialog" aria-modal="true">
        <div class="modal-h"><h2>{{ $t('templates.deleteTitle') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="delOpen = false"><Icon name="x" /></button></div>
        <div class="modal-b">
          <p>{{ $t('templates.deleteNote') }}</p>
          <p class="mt8"><b class="mono">{{ detail.id }}</b></p>
          <div v-if="delErr" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ delErr }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="delOpen = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger-solid" type="button" :disabled="delBusy" data-testid="tpl-delete-ok" @click="doDelete"><Icon name="trash" small />{{ $t('templates.delete') }}</button>
        </div>
      </div>
    </div>

    <KbSuggest v-if="suggestOpen && detail" :target="`template:${detail.id}`" kind="other" @close="suggestOpen = false" @submitted="onSuggested" />
    <div v-if="toast" class="toast" role="status" data-testid="tpl-toast"><Icon name="check" small /><span>{{ toast }}</span></div>
  </main>
</template>

<style scoped>
.tp { display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 1100px) { .tp { grid-template-columns: minmax(0, 1fr); } }
.tlist .panel-b { padding: 8px; }
.scope-tabs { margin: 0; padding: 0 8px; }
.scope-tabs .count { font-size: 11px; color: var(--ink-3); }
.scope-hint { display: flex; align-items: center; gap: 4px; margin: 0 2px 8px; }
.ro-lock { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--ink-3); }
.ti-row { display: block; padding: 9px 10px; border-radius: 6px; cursor: pointer; border: 1px solid transparent; }
.ti-row + .ti-row { margin-top: 2px; }
.ti-row:hover { background: var(--surface-2); }
.ti-row.is-sel { background: var(--blue-soft); border-color: var(--sel-ring); }
.ti-row .nm { font-weight: 600; font-size: 12.5px; line-height: 1.4; }
.ti-row .id { font: 11.5px var(--font-mono); color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px; }
.ti-row .mt { display: flex; gap: 6px; align-items: center; margin-top: 6px; font-size: 11.5px; color: var(--ink-3); flex-wrap: wrap; }
.ti-row .vendor i { width: 16px; height: 16px; font-size: 9px; }
.td-h { display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.td-h h2 { font-size: 16px; }
.td-h .id { font: 12px var(--font-mono); color: var(--ink-3); margin-top: 3px; display: flex; gap: 10px; flex-wrap: wrap; }
.td .tabs { margin: 0; padding: 0 10px; }
.td-b { padding: 14px; }
.issues { margin: 6px 0 0; padding-left: 18px; }
</style>
