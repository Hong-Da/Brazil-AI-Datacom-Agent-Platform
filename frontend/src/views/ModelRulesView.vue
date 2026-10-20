<script setup lang="ts">
/**
 * 型号规则（REQ-044，预览 DevelopDocs/ui-preview/REQ-044/rules.html）：本项目 / 全局两个页签，按生效顺序列出条件、
 * 目标 Profile、命中设备数、启用开关；全局规则只有知识库维护员与管理员能改（普通用户只读）；编辑区可试匹配本项目设备，
 * 保存时可重新解析命中的设备。接口：GET|POST /model-rules、POST /model-rules/test、PUT|DELETE /model-rules/{id}。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { del, errorText, get, post, put } from '@/api'
import { useProject } from '@/stores/project'
import { condText, hasCondition, regexOk, type ModelRule, type RuleScope } from './devices/model'

const { t } = useI18n()
const project = useProject()
const tab = ref<RuleScope>('project')
const data = ref<{ project: ModelRule[]; global: ModelRule[]; can_global: boolean } | null>(null)
const profiles = ref<{ id: string; vendor: string; family: string }[]>([])
const loadError = ref('')
const okMsg = ref('')
const actError = ref('')

async function load(): Promise<void> {
  loadError.value = ''
  try {
    const [d, p] = await Promise.all([
      get<{ project: ModelRule[]; global: ModelRule[]; can_global: boolean }>('/model-rules'),
      profiles.value.length ? Promise.resolve(null) : get<{ profiles: { id: string; vendor: string; family: string }[] }>('/kb/profiles'),
    ])
    data.value = { project: d.project ?? [], global: d.global ?? [], can_global: d.can_global }
    if (p) profiles.value = p.profiles
  } catch (e) {
    loadError.value = errorText(e)
  }
}
onMounted(load)

const rows = computed(() => (data.value ? data.value[tab.value] : []))
const canEdit = computed(() => project.canWrite && (tab.value === 'project' || !!data.value?.can_global))

// ---- 编辑区
interface Form { id: number | null; vendor: string; name_pattern: string; version: string; feature: string; profile: string; note: string; enabled: boolean; reparse: boolean }
const form = reactive<Form>({ id: null, vendor: '', name_pattern: '', version: '', feature: '', profile: '', note: '', enabled: true, reparse: true })
const editing = ref(false)
const saving = ref(false)
const formError = ref('')
const test = ref<{ count: number; devices: { id: number; name: string; taken_by: number | null }[] } | null>(null)

const vendorProfiles = computed(() => profiles.value.filter((p) => !form.vendor || p.vendor === form.vendor))
const vendors = computed(() => [...new Set(profiles.value.map((p) => p.vendor))].sort())
const formOk = computed(() => !!form.profile && hasCondition(form) && regexOk(form.version) && regexOk(form.feature))

function startNew(): void {
  Object.assign(form, { id: null, vendor: '', name_pattern: '', version: '', feature: '', profile: '', note: '', enabled: true, reparse: true })
  test.value = null
  formError.value = ''
  editing.value = true
}
function startEdit(r: ModelRule): void {
  Object.assign(form, { id: r.id, vendor: r.vendor, name_pattern: r.name_pattern, version: r.version, feature: r.feature, profile: r.profile, note: r.note, enabled: r.enabled, reparse: true })
  test.value = null
  formError.value = ''
  editing.value = true
}
function body(): Record<string, unknown> {
  return { vendor: form.vendor, name_pattern: form.name_pattern.trim(), version: form.version.trim(), feature: form.feature.trim(), profile: form.profile, note: form.note.trim() }
}
async function runTest(): Promise<void> {
  formError.value = ''
  try {
    test.value = await post('/model-rules/test', { ...body(), id: form.id })
  } catch (e) {
    formError.value = errorText(e)
  }
}
async function save(): Promise<void> {
  saving.value = true
  formError.value = ''
  try {
    const r = form.id
      ? await put<ModelRule & { reparsed?: number }>(`/model-rules/${form.id}`, { ...body(), enabled: form.enabled, reparse: form.reparse })
      : await post<ModelRule & { reparsed?: number }>('/model-rules', { ...body(), scope: tab.value, enabled: form.enabled, reparse: form.reparse })
    okMsg.value = form.reparse ? t('model.rules.savedReparse', { id: r.id, n: r.reparsed ?? 0 }) : t('model.rules.saved', { id: r.id })
    editing.value = false
    await load()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}
async function toggle(r: ModelRule, on: boolean): Promise<void> {
  actError.value = ''
  try {
    await put(`/model-rules/${r.id}`, { enabled: on })
    await load()
  } catch (e) {
    actError.value = errorText(e)
  }
}
async function remove(r: ModelRule): Promise<void> {
  if (!window.confirm(t('model.rules.confirmDelete', { id: r.id }))) return
  actError.value = ''
  try {
    await del(`/model-rules/${r.id}`)
    okMsg.value = t('model.rules.deleted', { id: r.id })
    if (form.id === r.id) editing.value = false
    await load()
  } catch (e) {
    actError.value = errorText(e)
  }
}
function setTab(v: RuleScope): void {
  tab.value = v
  editing.value = false
}
</script>

<template>
  <main class="main">
    <div class="page" data-testid="model-rules-page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('model.rules.title') }}</h1>
          <p class="ph-sub">{{ $t('model.rules.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-primary" type="button" :disabled="!canEdit" data-testid="rule-new" @click="startNew"><Icon name="plus" small /><span>{{ $t('model.rules.add') }}</span></button>
        </div>
      </div>

      <div class="tabs" role="tablist" data-testid="rule-tabs">
        <button role="tab" type="button" :aria-selected="tab === 'project'" data-testid="rule-tab-project" @click="setTab('project')">{{ $t('model.rules.tabProject') }} <span class="mono faint">{{ project.ref }}</span> <span class="count">{{ data?.project.length ?? 0 }}</span></button>
        <button role="tab" type="button" :aria-selected="tab === 'global'" data-testid="rule-tab-global" @click="setTab('global')">{{ $t('model.rules.tabGlobal') }} <span class="count">{{ data?.global.length ?? 0 }}</span></button>
      </div>
      <div v-if="tab === 'global' && data && !data.can_global" class="notice info mb12" data-testid="rule-global-ro"><Icon name="lock" /><div class="grow small">{{ $t('model.rules.globalRO') }}</div></div>
      <div v-if="okMsg" class="notice ok mb12" data-testid="rule-ok"><Icon name="ok" /><div class="grow">{{ okMsg }}</div><button class="btn btn-xs" type="button" @click="okMsg = ''">{{ $t('c.close') }}</button></div>
      <div v-if="actError" class="notice err mb12"><Icon name="err" /><div class="grow">{{ actError }}</div><button class="btn btn-xs" type="button" @click="actError = ''">{{ $t('c.close') }}</button></div>

      <div v-if="loadError" class="notice err"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <section v-else class="panel">
        <p v-if="!data" class="faint" style="padding: 14px 16px">{{ $t('c.loading') }}</p>
        <div v-else-if="!rows.length" class="empty" data-testid="rule-empty"><p>{{ $t('model.rules.empty') }}</p></div>
        <div v-else class="tbl-wrap">
          <table class="tbl" data-testid="rule-table">
            <thead>
              <tr>
                <th>{{ $t('model.rules.colOrder') }}</th>
                <th>{{ $t('model.rules.colCond') }}</th>
                <th>→ Profile</th>
                <th class="num">{{ $t('model.rules.colDevices') }}</th>
                <th>{{ $t('model.rules.colNote') }}</th>
                <th>{{ $t('model.rules.colBy') }}</th>
                <th>{{ $t('model.rules.colOn') }}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in rows" :key="r.id" :class="{ off: !r.enabled }" :data-testid="`rule-row-${r.id}`">
                <td class="prio">{{ r.enabled ? i + 1 : '—' }} <span class="faint">#{{ r.id }}</span></td>
                <td>
                  <div class="cond">
                    <span v-if="r.vendor"><span class="k">{{ $t('model.fVendor') }}</span> <code>{{ r.vendor }}</code></span>
                    <span v-if="r.name_pattern"><span class="k">{{ $t('model.k.name') }}</span> <code>{{ r.name_pattern }}</code></span>
                    <span v-if="r.version"><span class="k">{{ $t('model.k.version') }}</span> <code>{{ r.version }}</code></span>
                    <span v-if="r.feature"><span class="k">{{ $t('model.k.feature') }}</span> <code>{{ r.feature }}</code></span>
                  </div>
                </td>
                <td class="mono">{{ r.profile }}</td>
                <td class="num">{{ r.devices ?? 0 }}</td>
                <td class="small">{{ r.note }}</td>
                <td class="small">{{ r.created_by }}</td>
                <td><label class="switch"><input type="checkbox" :checked="r.enabled" :disabled="!canEdit" :aria-label="`#${r.id}`" :data-testid="`rule-on-${r.id}`" @change="toggle(r, ($event.target as HTMLInputElement).checked)"><span /></label></td>
                <td class="right nowrap">
                  <template v-if="canEdit">
                    <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('model.rules.editTitle', { id: r.id })" :data-testid="`rule-edit-${r.id}`" @click="startEdit(r)"><Icon name="pencil" small /></button>
                    <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('c.delete')" :data-testid="`rule-del-${r.id}`" @click="remove(r)"><Icon name="trash" small /></button>
                  </template>
                  <span v-else class="faint small">{{ $t('model.rules.readonly') }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="editing" class="panel mt16" data-testid="rule-editor">
        <div class="panel-h"><h2>{{ form.id ? $t('model.rules.editTitle', { id: form.id }) : $t('model.rules.newTitle') }} · {{ $t(`model.scope.${tab}`) }}</h2></div>
        <div class="panel-b">
          <div class="fgrid">
            <label class="f">{{ $t('model.fName') }}<input v-model="form.name_pattern" class="input mono" placeholder="NE8000-*" data-testid="rule-f-name"></label>
            <label class="f">{{ $t('model.fVersion') }}<input v-model="form.version" class="input mono" :class="{ bad: !regexOk(form.version) }" placeholder="V800R022" data-testid="rule-f-version"></label>
            <label class="f">{{ $t('model.fFeature') }}<input v-model="form.feature" class="input mono" :class="{ bad: !regexOk(form.feature) }" placeholder="^set neid" data-testid="rule-f-feature"></label>
            <label class="f">{{ $t('model.fVendor') }}
              <select v-model="form.vendor" class="select" data-testid="rule-f-vendor">
                <option value="">{{ $t('model.anyVendor') }}</option>
                <option v-for="v in vendors" :key="v" :value="v">{{ v }}</option>
              </select>
            </label>
            <label class="f">Profile
              <select v-model="form.profile" class="select mono" data-testid="rule-f-profile">
                <option value="" disabled>{{ $t('model.pickProfile') }}</option>
                <option v-for="p in vendorProfiles" :key="p.id" :value="p.id">{{ p.id }}</option>
              </select>
            </label>
            <label class="f">{{ $t('model.fNote') }}<input v-model="form.note" class="input" maxlength="2000"></label>
          </div>
          <div v-if="!hasCondition(form)" class="small mt8" style="color: var(--amber-ink)">{{ $t('model.needCond') }}</div>
          <div v-else-if="!regexOk(form.version) || !regexOk(form.feature)" class="small mt8" style="color: var(--amber-ink)">{{ $t('model.badRegex') }}</div>
          <div v-if="test" class="notice mt12" :class="test.count ? 'ok' : 'info'" data-testid="rule-test-result">
            <Icon :name="test.count ? 'check' : 'info'" />
            <div class="grow small">{{ $t('model.rules.testHits', { n: test.count, d: test.count ? `：${test.devices.map((d) => d.name + (d.taken_by ? ` (${t('model.rules.takenBy', { id: d.taken_by })})` : '')).join(', ')}` : '' }) }}</div>
          </div>
          <div v-if="formError" class="notice err mt12" data-testid="rule-error"><Icon name="err" /><div class="grow">{{ formError }}</div></div>
          <div class="row mt12" style="gap: 8px; justify-content: flex-end; flex-wrap: wrap">
            <label class="row small" style="gap: 6px; margin-right: auto"><input v-model="form.reparse" type="checkbox" data-testid="rule-f-reparse">{{ $t('model.rules.reparse') }}</label>
            <button class="btn" type="button" :disabled="!formOk" data-testid="rule-test" @click="runTest"><Icon name="search" small />{{ $t('model.rules.test') }}</button>
            <button class="btn" type="button" @click="editing = false">{{ $t('c.cancel') }}</button>
            <button class="btn btn-primary" type="button" :disabled="!formOk || saving" data-testid="rule-save" @click="save">{{ $t('c.save') }}</button>
          </div>
          <p class="small faint mt8">{{ condText(form) }}</p>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.mb12 { margin-bottom: 12px; }
.prio { font: 600 12px var(--font-mono); color: var(--ink-3); white-space: nowrap; }
.cond { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 12px; }
.cond .k { color: var(--ink-3); }
.cond code { font: 11.5px var(--font-mono); background: var(--surface-3); padding: 0 4px; border-radius: 3px; }
tr.off td { opacity: .6; }
.fgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 14px; }
.fgrid label.f { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-2); }
.input.bad { border-color: var(--red-line); }
@media (max-width: 1000px) { .fgrid { grid-template-columns: 1fr; } }
</style>
