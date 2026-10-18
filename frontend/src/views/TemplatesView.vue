<script setup lang="ts">
/**
 * 配置模板（预览 DevelopDocs/ui-preview/M3/templates.html）：模板列表（GET /templates）、模板详情（GET /templates/{id}）、
 * 编辑模板文件并保存（PUT /templates/{id}，有问题时 409 与问题清单）、校验配置（POST /templates/check）、从设备生成草稿（POST /templates/draft）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { ApiError, errorText, get, put } from '@/api'
import { pickLang } from '@/i18n'
import type { Device } from '@/views/devices/logic'
import { msg } from '@/views/m3/texts'
import TemplateTab from './templates/TemplateTab.vue'
import CheckTab from './templates/CheckTab.vue'
import DraftTab from './templates/DraftTab.vue'
import { skeleton } from './templates/logic'
import type { TemplateDetail, TemplateInfo, TemplateIssue } from './templates/types'

type Tab = 'text' | 'check' | 'draft'
interface ProfileLite { id: string; family: string; vendor: string }

const route = useRoute()
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
const tab = ref<Tab>(['text', 'check', 'draft'].includes(String(route.query.tab)) ? (route.query.tab as Tab) : 'text')

async function loadList(): Promise<void> {
  listLoading.value = true
  listError.value = ''
  try {
    list.value = (await get<{ templates: TemplateInfo[] }>('/templates')).templates
    if (!selId.value && list.value.length && tab.value !== 'draft') selId.value = list.value[0].id
  } catch (e) {
    listError.value = errorText(e)
  } finally {
    listLoading.value = false
  }
}
const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return list.value
  return list.value.filter((x) => x.id.toLowerCase().includes(s) || Object.values(x.title ?? {}).some((v) => v.toLowerCase().includes(s)) || x.profile.includes(s))
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
    await put(`/templates/${encodeURIComponent(id)}`, { source: yaml.value })
    isNew.value = false
    await loadList()
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
          <div class="panel-b">
            <label class="input-wrap" style="margin-bottom: 8px"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('templates.search')"></label>
            <div v-if="listLoading" class="empty small">{{ $t('c.loading') }}</div>
            <div v-else-if="listError" class="notice err"><Icon name="err" /><div class="grow">{{ listError }}</div><button class="btn btn-sm" type="button" @click="loadList">{{ $t('c.retry') }}</button></div>
            <div v-else-if="!list.length" class="empty small">{{ $t('templates.noTemplates') }}</div>
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
                  <span class="vendor"><i :class="x.family.startsWith('huawei') ? 'hw' : 'cs'">{{ x.family.startsWith('huawei') ? 'HW' : 'CS' }}</i></span>
                  <span>{{ $t('templates.varsN', { n: x.vars }) }}</span>
                  <span v-if="x.blocks">{{ $t('templates.blocksN', { n: x.blocks }) }}</span>
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
            <div class="td-b"><DraftTab :devices="devices" :profiles="profiles" @saved="onDraftSaved" /></div>
          </template>
          <template v-else-if="isNew || detail">
            <div class="td-h">
              <div style="flex: 1; min-width: 0">
                <h2>{{ isNew ? $t('templates.newRow') : title(detail?.title) || detail?.id }}</h2>
                <div v-if="detail && !isNew" class="id"><span>templates/{{ detail.file }}</span><span>v{{ detail.version }}</span><span>Profile {{ detail.profile }}</span><span v-if="detail.profiles.length">{{ $t('templates.applies') }} {{ detail.profiles.join(', ') }}</span></div>
                <p v-if="detail?.description && !isNew" class="small muted mt8">{{ title(detail.description) }}</p>
              </div>
              <div class="row wrap">
                <template v-if="editing || isNew">
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
              <TemplateTab v-if="tab === 'text'" v-model:yaml="yaml" :detail="isNew ? null : detail" :editing="editing" :is-new="isNew" @edit="(v) => (editing = v)" />
              <CheckTab v-else-if="tab === 'check' && detail" :detail="detail" :devices="devices" :yaml="yaml" :dirty="dirty" />
            </div>
          </template>
          <div v-else-if="detailLoading" class="empty">{{ $t('c.loading') }}</div>
          <div v-else-if="detailError" class="notice err" style="margin: 14px"><Icon name="err" /><div class="grow">{{ detailError }}</div><button class="btn btn-sm" type="button" @click="loadDetail(selId)">{{ $t('c.retry') }}</button></div>
          <div v-else class="empty"><Icon name="stencil" /><h3>{{ $t('templates.pick') }}</h3></div>
        </section>
      </div>
    </div>
  </main>
</template>

<style scoped>
.tp { display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 1100px) { .tp { grid-template-columns: minmax(0, 1fr); } }
.tlist .panel-b { padding: 8px; }
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
