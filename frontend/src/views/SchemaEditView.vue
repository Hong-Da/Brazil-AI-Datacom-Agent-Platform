<script setup lang="ts">
/** Schema 管理：节点树、节点表单（保存到草稿区）、新建子节点、删除前检查与删除、标记 / 取消废弃、已废弃节点列表。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, del, errorText, get, put } from '@/api'
import { pickLang } from '@/i18n'
import { noteText } from '@/i18n/note'
import { useStatus } from '@/stores/status'
import Icon from '@/components/Icon.vue'
import { allDeps, allNodes, buildTree, depStyle, edgesOf, filterTree, nodeDomain, type SchemaData, type SchemaNode } from './schema/model'
import StyleForms from './schema/StyleForms.vue'
import { styleForm } from './schema/styles'
import { useTerms } from '@/stores/terms'
import { useAuth } from '@/stores/auth'
import KbRoRibbon from '@/components/kb-ro-ribbon.vue'
import TypeParams from './schema/TypeParams.vue'
import {
  errorDetails, formToBody, isDirty, newForm, nodeToForm, SEM_LANGS, STATUSES, usageGroups, validateForm,
  descendants, type NodeForm, type NodeUsage,
} from './schema/form'

interface Draft {
  base: string | null
  changes: (Record<string, unknown> & { suggested_bump?: string }) | null
  commits: { commit: string; time: number; message: string }[]
}
const DRAFT_KEYS = ['nodes_added', 'nodes_removed', 'nodes_semantic', 'nodes_deprecated'] as const
const USAGE_SHOW = 8

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const status = useStatus()
const terms = useTerms()
// 知识库只有管理员与维护员可以修改（REQ-036）；普通用户只读查看
const auth = useAuth()

const loading = ref(true)
const loadError = ref('')
const schema = ref<SchemaData | null>(null)
const draft = ref<Draft | null>(null)
const tq = ref('')
const sel = ref<string | null>(null)
const creating = ref(false)
const form = ref<NodeForm | null>(null)
const saving = ref(false)
const saveError = ref<{ msg: string; details: string[] } | null>(null)
const usage = ref<NodeUsage | null>(null)
const usageError = ref('')
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined

const domains = computed(() => schema.value?.domains ?? [])
const nodes = computed(() => allNodes(domains.value))
const deps = computed(() => allDeps(domains.value))
const byId = computed(() => new Map(nodes.value.map((n) => [n.id, n])))
const domOf = computed(() => nodeDomain(domains.value))
const types = computed(() => schema.value?.node_types ?? [])
const tree = computed(() => filterTree(buildTree(domains.value), tq.value))
const current = computed<SchemaNode | null>(() => (sel.value ? byId.value.get(sel.value) ?? null : null))
const deprecatedNodes = computed(() => nodes.value.filter((n) => n.deprecated))
const lang = computed(() => String(locale.value))

const draftNodes = computed(() => {
  const s = new Set<string>()
  const c = draft.value?.changes
  if (c) for (const k of DRAFT_KEYS) for (const id of (c[k] as string[] | undefined) ?? []) s.add(id)
  return s
})
const draftGroups = computed(() =>
  DRAFT_KEYS.map((k) => ({ key: k, items: ((draft.value?.changes?.[k] as string[] | undefined) ?? []) })).filter((g) => g.items.length),
)

const errors = computed(() => (form.value ? validateForm(form.value, nodes.value, types.value, creating.value) : {}))
const dirty = computed(() => !!form.value && (creating.value || isDirty(form.value, current.value)))
const canSave = computed(() => dirty.value && !saving.value && Object.keys(errors.value).length === 0)

const parentOptions = computed(() => {
  const banned = !creating.value && sel.value ? descendants(nodes.value, sel.value) : new Set<string>()
  return nodes.value.filter((n) => !banned.has(n.id)).map((n) => n.id).sort()
})
const refOptions = computed(() => {
  const ids = nodes.value.filter((n) => n.type === 'object').map((n) => n.id)
  const cur = form.value?.ref
  if (cur && !ids.includes(cur)) ids.push(cur)
  return ids.sort()
})
const replacementOptions = computed(() =>
  nodes.value.filter((n) => !n.deprecated && n.id !== (form.value?.id ?? sel.value)).map((n) => n.id).sort(),
)
const typeOptions = computed(() => {
  const list = [...types.value]
  const cur = form.value?.type
  if (cur && !list.includes(cur)) list.push(cur)
  return list
})
const formDomain = computed(() => {
  if (!form.value) return ''
  if (!creating.value && sel.value) return domOf.value.get(sel.value) ?? ''
  return form.value.parent ? domOf.value.get(form.value.parent) ?? '' : form.value.id.split('.')[0] ?? ''
})
const nodeEdges = computed(() => (sel.value && !creating.value ? edgesOf(deps.value, sel.value) : []))
const usageList = computed(() => usageGroups(usage.value))

function semText(n: SchemaNode): string {
  return pickLang(n.semantic, lang.value)
}
function showToast(msg: string): void {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 3200)
}
onBeforeUnmount(() => clearTimeout(toastTimer))

/* ---------------- 加载 ---------------- */
async function loadSchema(): Promise<void> {
  schema.value = await get<SchemaData>('/kb/schema')
}
async function loadDraft(): Promise<void> {
  try { draft.value = await get<Draft>('/kb/draft') } catch { draft.value = null }
}
async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([loadSchema(), loadDraft()])
    const q = typeof route.query.node === 'string' ? route.query.node : ''
    const first = q && byId.value.has(q) ? q : sel.value && byId.value.has(sel.value) ? sel.value : null
    if (first) select(first, true)
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

let usageSeq = 0
async function loadUsage(id: string): Promise<NodeUsage | null> {
  const seq = ++usageSeq
  usageError.value = ''
  try {
    const u = await get<NodeUsage>(`/kb/schema/nodes/${encodeURIComponent(id)}/usage`)
    if (seq === usageSeq) usage.value = u
    return u
  } catch (e) {
    if (seq === usageSeq) { usage.value = null; usageError.value = errorText(e) }
    return null
  }
}
watch(sel, (id) => { usage.value = null; if (id) void loadUsage(id) })

/* ---------------- 选择与新建 ---------------- */
/** 有未保存的修改时先在页面内确认（不用 window.confirm，避免阻塞页面）；确认后放弃修改再执行。 */
const pendingLeave = ref<(() => void) | null>(null)
function guard(action: () => void): boolean {
  if (!dirty.value) return true
  pendingLeave.value = action
  return false
}
function leaveConfirmed(): void {
  const act = pendingLeave.value
  pendingLeave.value = null
  discard()
  act?.()
}
function select(id: string, force = false): void {
  const n = byId.value.get(id)
  if (!n || (!force && !guard(() => select(id, true)))) return
  creating.value = false
  sel.value = id
  form.value = nodeToForm(n)
  saveError.value = null
  if (route.query.node !== id) void router.replace({ query: { ...route.query, node: id } })
  void nextTick(() => document.querySelector(`.tree .ti[title="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' }))
}
function startCreate(parent: SchemaNode | null, force = false): void {
  if (!force && !guard(() => startCreate(parent, true))) return
  creating.value = true
  sel.value = null
  form.value = newForm(parent)
  saveError.value = null
  const rest = { ...route.query }
  delete rest.node
  void router.replace({ query: rest })
}
function discard(): void {
  saveError.value = null
  if (creating.value) { creating.value = false; form.value = null; return }
  if (current.value) form.value = nodeToForm(current.value)
}

/* ---------------- 写入 ---------------- */
function apiFailure(e: unknown): { msg: string; details: string[] } {
  return { msg: errorText(e), details: e instanceof ApiError ? errorDetails(e.data) : [] }
}
async function afterWrite(selectId: string | null): Promise<void> {
  await Promise.all([loadSchema(), loadDraft()])
  void status.refresh()
  if (selectId && byId.value.has(selectId)) select(selectId, true)
  else { sel.value = null; form.value = null; creating.value = false }
  if (sel.value) void loadUsage(sel.value)
}
async function putNode(id: string, body: ReturnType<typeof formToBody>): Promise<void> {
  await put(`/kb/schema/nodes/${encodeURIComponent(id)}`, body)
}

async function save(): Promise<void> {
  if (!form.value || !canSave.value) return
  saving.value = true
  saveError.value = null
  const id = creating.value ? form.value.id.trim() : sel.value!
  const wasCreating = creating.value
  try {
    await putNode(id, formToBody(form.value))
    creating.value = false
    await afterWrite(id)
    showToast(t(wasCreating ? 'schema-edit.created' : 'schema-edit.saved', { id }))
  } catch (e) {
    saveError.value = apiFailure(e)
  } finally {
    saving.value = false
  }
}

async function restore(): Promise<void> {
  if (!current.value) return
  const f = nodeToForm(current.value)
  f.deprecated = false
  f.replaced_by = ''
  saving.value = true
  saveError.value = null
  try {
    await putNode(current.value.id, formToBody(f))
    const id = current.value.id
    await afterWrite(id)
    showToast(t('schema-edit.restored', { id }))
  } catch (e) {
    saveError.value = apiFailure(e)
  } finally {
    saving.value = false
  }
}

/* ---------------- 删除 / 废弃对话框 ---------------- */
const modal = ref<'delete' | 'deprecate' | null>(null)
const modalNode = ref<SchemaNode | null>(null)
const modalUsage = ref<NodeUsage | null>(null)
const modalChecking = ref(false)
const modalBusy = ref(false)
const modalError = ref<{ msg: string; details: string[] } | null>(null)
const replacement = ref('')
const modalGroups = computed(() => usageGroups(modalUsage.value))

async function openDelete(): Promise<void> {
  if (!current.value || !guard(() => void openDelete())) return
  modal.value = 'delete'
  modalNode.value = current.value
  modalUsage.value = null
  modalError.value = null
  replacement.value = ''
  modalChecking.value = true
  try {
    modalUsage.value = await get<NodeUsage>(`/kb/schema/nodes/${encodeURIComponent(current.value.id)}/usage`)
  } catch (e) {
    modalError.value = apiFailure(e)
  } finally {
    modalChecking.value = false
  }
}
function openDeprecate(): void {
  if (!current.value || !guard(openDeprecate)) return
  modal.value = 'deprecate'
  modalNode.value = current.value
  modalUsage.value = null
  modalError.value = null
  replacement.value = current.value.replaced_by ?? ''
}
function closeModal(): void {
  if (!modalBusy.value) modal.value = null
}
async function doDelete(): Promise<void> {
  const n = modalNode.value
  if (!n) return
  modalBusy.value = true
  modalError.value = null
  try {
    await del(`/kb/schema/nodes/${encodeURIComponent(n.id)}`)
    await afterWrite(n.parent)
    modal.value = null
    showToast(t('schema-edit.deleted', { id: n.id }))
  } catch (e) {
    // 409：仍被使用，data 是最新的使用情况
    if (e instanceof ApiError && e.status === 409 && e.data && typeof e.data === 'object') modalUsage.value = e.data as NodeUsage
    modalError.value = { msg: errorText(e), details: [] }
  } finally {
    modalBusy.value = false
  }
}
async function doDeprecate(): Promise<void> {
  const n = modalNode.value
  if (!n) return
  const f = nodeToForm(n)
  f.deprecated = true
  f.replaced_by = replacement.value
  modalBusy.value = true
  modalError.value = null
  try {
    await putNode(n.id, formToBody(f))
    await afterWrite(n.id)
    modal.value = null
    showToast(t('schema-edit.deprecatedOk', { id: n.id }))
  } catch (e) {
    modalError.value = apiFailure(e)
  } finally {
    modalBusy.value = false
  }
}
function onKey(e: KeyboardEvent): void {
  if (e.key !== 'Escape') return
  if (pendingLeave.value) pendingLeave.value = null
  else if (modal.value) closeModal()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

function err(field: string): string {
  const k = errors.value[field]
  return k ? t(`schema-edit.${k}`) : ''
}
function semLabel(l: string): string {
  return l === 'zh-CN' ? '中文' : l === 'en' ? 'English' : 'Português (Brasil)'
}
</script>

<template>
  <main class="main">
    <div class="page fill">
      <div class="ph" style="margin-bottom: 10px">
        <div class="ph-text">
          <div class="crumbs"><span>{{ $t('schema-edit.crumbKb') }}</span><span class="sep">/</span><span>{{ $t('schema-edit.crumbDraft') }}</span></div>
          <h1>{{ $t('nav.schema-edit') }}</h1>
        </div>
        <div class="ph-actions">
          <router-link class="btn" :to="{ name: 'schema-view', query: sel ? { node: sel } : {} }" data-testid="se-to-view"><Icon name="layers" small />{{ $t('nav.schema-view') }}</router-link>
        </div>
      </div>

      <KbRoRibbon />
      <div v-if="loading" class="panel"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>
      <div v-else-if="loadError" class="notice err" data-testid="se-error">
        <Icon name="err" />
        <div class="grow"><b>{{ $t('c.error') }}</b><div class="small mt8">{{ loadError }}</div></div>
        <button class="btn btn-sm" data-testid="se-retry" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
      </div>

      <div v-else class="se">
        <!-- 节点树 -->
        <aside class="panel p-tree">
          <div class="tsearch">
            <label class="input-wrap" style="flex: 1"><Icon name="search" small /><input v-model="tq" class="input" type="search" :placeholder="$t('schema-edit.filter')" data-testid="se-filter" /></label>
            <button v-if="auth.isKbEditor" class="btn btn-icon" :title="$t('schema-edit.newRoot')" data-testid="se-new-root" @click="startCreate(null)"><Icon name="plus" small /></button>
          </div>
          <div class="scroll tree" data-testid="se-tree">
            <template v-for="g in tree" :key="g.domain">
              <div class="dom"><i class="stratum s-kb"></i>{{ g.domain }}<span class="cnt">{{ g.items.length }}</span></div>
              <div
                v-for="it in g.items" :key="it.node.id"
                :class="['ti', { 'is-sel': sel === it.node.id, dep: it.node.deprecated }]"
                :style="{ paddingLeft: 8 + Math.min(it.depth, 8) * 14 + 'px' }" :title="it.node.id" data-testid="se-tree-item"
                @click="select(it.node.id)"
              >
                <span class="tw"><Icon v-if="it.node.type === 'object'" name="chevD" small /></span>
                <span class="nm">{{ it.name }}</span>
                <span v-if="styleForm(terms, it.node.id, it.node.type, terms.style)" class="sf-mini" data-testid="se-tree-form">{{ styleForm(terms, it.node.id, it.node.type, terms.style) }}</span>
                <span v-if="draftNodes.has(it.node.id)" class="dirty" :title="$t('schema-edit.draftDot')"></span>
                <span v-else-if="it.node.deprecated" class="tag tg deprecated">deprecated</span>
                <span v-else-if="it.node.status === 'draft'" class="tag tg draft">draft</span>
              </div>
            </template>
            <div v-if="!tree.length" class="empty small"><p>{{ $t('schema-edit.noMatch') }}</p></div>
          </div>
        </aside>

        <!-- 编辑 -->
        <section class="edit-col" data-testid="se-editor">
          <div v-if="!form" class="panel"><div class="empty"><p>{{ $t('schema-edit.pickNode') }}</p></div></div>
          <template v-else>
            <div class="panel">
              <div class="panel-b">
                <div class="nh">
                  <span class="nid">{{ creating ? form.id || $t('schema-edit.creating') : form.id }}</span>
                  <span v-if="creating" class="tag t-blue">{{ $t('schema-edit.creating') }}</span>
                  <span v-else-if="current?.deprecated" class="tag deprecated" style="text-decoration: none">deprecated</span>
                  <span v-else class="tag t-teal">{{ $t('schema-edit.active') }}</span>
                  <span v-if="sel && draftNodes.has(sel)" class="tag warn">{{ $t('schema-edit.modifiedInDraft') }}</span>
                  <span v-if="dirty && !creating" class="tag t-amber">{{ $t('schema-edit.unsaved') }}</span>
                  <span v-if="!creating && current && auth.isKbEditor" class="ml-auto row">
                    <button class="btn btn-sm" data-testid="se-new-child" @click="startCreate(current)"><Icon name="plus" small />{{ $t('schema-edit.newChild') }}</button>
                    <button v-if="current.deprecated" class="btn btn-sm" :disabled="saving" data-testid="se-restore" @click="restore"><Icon name="rollback" small />{{ $t('schema-edit.restore') }}</button>
                    <button v-else class="btn btn-sm" data-testid="se-deprecate" @click="openDeprecate">{{ $t('schema-edit.markDeprecated') }}</button>
                    <button class="btn btn-sm btn-danger" data-testid="se-delete" @click="openDelete"><Icon name="trash" small />{{ $t('c.delete') }}</button>
                  </span>
                </div>
                <StyleForms v-if="current && !creating" :id="current.id" :type="current.type" />
                <div v-if="current?.deprecated && !creating" class="notice warn mt12">
                  <Icon name="warn" />
                  <div class="grow">
                    <b>{{ $t('schema-edit.depNoticeTitle') }}</b>
                    <div class="small mt8">{{ $t('schema-edit.depNoticeBody') }}</div>
                    <div class="row mt8 small">
                      <span class="mono">{{ current.id }}</span>
                      <template v-if="current.replaced_by">
                        <span class="faint">{{ $t('schema-edit.mapsTo') }}</span>
                        <button class="link-btn mono" @click="select(current.replaced_by)">{{ current.replaced_by }}</button>
                      </template>
                      <span v-else class="faint">{{ $t('schema-edit.noReplacement') }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 节点定义 -->
            <div class="panel" data-testid="se-form">
              <div class="panel-h">
                <h3>{{ $t('schema-edit.definition') }}</h3>
                <span v-if="formDomain" class="meta mono">schema/{{ formDomain }}.yaml</span>
              </div>
              <div class="panel-b">
                <fieldset class="ro-fs" :disabled="!auth.isKbEditor">
                <div class="form-grid">
                  <div class="field">
                    <label>{{ $t('schema-edit.id') }}</label>
                    <input v-if="creating" v-model.trim="form.id" :class="['input', 'mono', { 'is-error': errors.id }]" data-testid="se-f-id" />
                    <input v-else class="input mono" :value="form.id" disabled />
                    <span v-if="err('id')" class="err">{{ err('id') }}</span>
                    <span v-else class="hint">{{ creating ? $t('schema-edit.idNewHint') : $t('schema-edit.idHint') }}</span>
                  </div>
                  <div class="field">
                    <label>{{ $t('schema-edit.parent') }}</label>
                    <select v-model="form.parent" class="select mono" data-testid="se-f-parent">
                      <option value="">{{ $t('schema-edit.root') }}</option>
                      <option v-for="id in parentOptions" :key="id" :value="id">{{ id }}</option>
                    </select>
                    <span v-if="err('parent')" class="err">{{ err('parent') }}</span>
                  </div>
                  <div v-for="l in SEM_LANGS" :key="l" class="field span2">
                    <label>{{ $t('schema-edit.semantic') }} · {{ semLabel(l) }}</label>
                    <textarea v-model="form.semantic[l]" :class="['textarea', { 'is-error': errors.semantic }]" rows="2" :data-testid="`se-f-sem-${l}`"></textarea>
                  </div>
                  <div class="field span2 semhint">
                    <span v-if="err('semantic')" class="err">{{ err('semantic') }}</span>
                    <span v-else class="hint">{{ $t('schema-edit.semanticHint') }}</span>
                  </div>
                  <div class="field">
                    <label>{{ $t('schema-edit.type') }}</label>
                    <select v-model="form.type" class="select mono" data-testid="se-f-type">
                      <option v-for="ty in typeOptions" :key="ty" :value="ty">{{ ty }}</option>
                    </select>
                    <span v-if="err('type')" class="err">{{ err('type') }}</span>
                    <span v-else class="hint">{{ $t('schema-edit.typeHint') }}</span>
                  </div>
                  <div class="field">
                    <label>{{ $t('schema-edit.domain') }}</label>
                    <input class="input mono" :value="creating && !form.parent ? $t('schema-edit.domainNew') : formDomain" disabled />
                  </div>
                  <!-- 随数据类型变化的设置项（M6-9） -->
                  <TypeParams v-model:form="form" class="span2" :errors="errors" :ref-options="refOptions"
                    :orig-type="creating ? null : current?.type ?? null" @undo="form.type = current?.type ?? form.type" />
                  <div class="field">
                    <label>{{ $t('schema-edit.status') }}</label>
                    <select v-model="form.status" class="select mono" data-testid="se-f-status">
                      <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
                      <option v-if="!(STATUSES as readonly string[]).includes(form.status)" :value="form.status">{{ form.status }}</option>
                    </select>
                  </div>
                  <div class="field span2">
                    <div class="row" style="gap: 24px; flex-wrap: wrap">
                      <label class="check"><span class="switch"><input v-model="form.deprecated" type="checkbox" data-testid="se-f-deprecated" /><span></span></span>{{ $t('schema-edit.deprecated') }}</label>
                    </div>
                  </div>
                  <div v-if="form.deprecated" class="field">
                    <label>{{ $t('schema-edit.replacedBy') }}</label>
                    <select v-model="form.replaced_by" class="select mono" data-testid="se-f-replaced-by">
                      <option value="">{{ $t('schema-edit.replacementOpt') }}</option>
                      <option v-for="id in replacementOptions" :key="id" :value="id">{{ id }}</option>
                      <option v-if="form.replaced_by && !replacementOptions.includes(form.replaced_by)" :value="form.replaced_by">{{ form.replaced_by }}</option>
                    </select>
                    <span v-if="err('replaced_by')" class="err">{{ err('replaced_by') }}</span>
                  </div>
                </div>

                </fieldset>
                <div v-if="saveError" class="notice err mt12" data-testid="se-save-error">
                  <Icon name="err" />
                  <div class="grow">
                    <b>{{ $t('schema-edit.saveFailed') }}</b>
                    <div class="small mt8">{{ saveError.msg }}</div>
                    <ul v-if="saveError.details.length" class="small mt8 errlist"><li v-for="(d, i) in saveError.details" :key="i" class="mono">{{ d }}</li></ul>
                  </div>
                </div>
                <div v-if="auth.isKbEditor" class="row mt16">
                  <button class="btn btn-primary" :disabled="!canSave" data-testid="se-save" @click="save">{{ saving ? $t('schema-edit.saving') : $t('schema-edit.save') }}</button>
                  <button class="btn btn-ghost" :disabled="saving || (!dirty && !creating)" data-testid="se-discard" @click="discard">{{ $t('schema-edit.discard') }}</button>
                </div>
                <p v-if="auth.isKbEditor" class="small faint mt8">{{ $t('schema-edit.saveHint') }}</p>
              </div>
            </div>

            <!-- 依赖（只读） -->
            <div v-if="!creating" class="panel" data-testid="se-deps">
              <div class="panel-h"><h3>{{ $t('schema-edit.deps') }} <span class="pill-count">{{ nodeEdges.length }}</span></h3></div>
              <div v-if="nodeEdges.length" class="tbl-wrap">
                <table class="tbl etbl">
                  <thead><tr><th>{{ $t('schema-edit.colType') }}</th><th>{{ $t('schema-edit.colDir') }}</th><th>{{ $t('schema-edit.colOther') }}</th><th>{{ $t('schema-edit.colNote') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(e, i) in nodeEdges" :key="i">
                      <td><span class="etype"><i :style="{ background: `var(--e-${depStyle(e.kind)})` }"></i>{{ $t('e.' + e.style) }}</span></td>
                      <td class="small">{{ e.dir === 'in' ? $t('schema-edit.dirIn') : $t('schema-edit.dirOut') }}</td>
                      <td class="mono"><button v-if="byId.has(e.other)" class="link-btn mono" @click="select(e.other)">{{ e.other }}</button><span v-else>{{ e.other }}</span></td>
                      <td class="small muted">{{ noteText(e.note, lang) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="panel-b small faint">{{ $t('schema-edit.depsNone') }}</div>
              <div class="panel-b small faint" style="border-top: 1px solid var(--line)">{{ $t('schema-edit.depsHint') }}</div>
            </div>
          </template>
        </section>

        <!-- 侧栏 -->
        <aside class="side-col">
          <div class="panel" data-testid="se-usage">
            <div class="panel-h"><h3>{{ $t('schema-edit.usage') }}</h3></div>
            <div class="panel-b">
              <p v-if="!form" class="small faint">{{ $t('schema-edit.pickNode') }}</p>
              <p v-else-if="creating" class="small faint">{{ $t('schema-edit.usageNew') }}</p>
              <div v-else-if="usageError" class="notice err"><Icon name="err" /><div class="grow small">{{ usageError }}</div></div>
              <p v-else-if="!usage" class="small faint">{{ $t('c.loading') }}</p>
              <template v-else-if="usage.blocking">
                <p class="small muted" style="margin-bottom: 8px">{{ $t('schema-edit.usageHint') }}</p>
                <details v-for="g in usageList" :key="g.key" class="ug">
                  <summary><span>{{ $t('schema-edit.u.' + g.key) }}</span><span class="n">{{ g.items.length }}</span></summary>
                  <div class="ug-items">
                    <template v-for="x in g.items.slice(0, USAGE_SHOW)" :key="x">
                      <button v-if="byId.has(x)" class="link-btn mono" @click="select(x)">{{ x }}</button>
                      <span v-else class="mono">{{ x }}</span>
                    </template>
                    <span v-if="g.items.length > USAGE_SHOW" class="faint small">{{ $t('schema-edit.more', { n: g.items.length - USAGE_SHOW }) }}</span>
                  </div>
                </details>
              </template>
              <div v-else class="notice ok"><Icon name="ok" /><div class="grow small">{{ $t('schema-edit.usageFree') }}</div></div>
            </div>
          </div>

          <div class="panel" data-testid="se-draft">
            <div class="panel-h">
              <h3>{{ $t('schema-edit.draft') }}</h3>
              <span v-if="draft?.base" class="meta">{{ $t('schema-edit.draftBase', { v: draft.base }) }}</span>
            </div>
            <div class="panel-b">
              <p v-if="!draft" class="small faint">{{ $t('c.empty') }}</p>
              <template v-else>
                <p v-if="!draft.base" class="small faint" data-testid="se-draft-first">{{ $t('schema-edit.draftFirst') }}</p>
                <p v-else-if="!draftGroups.length" class="small faint">{{ $t('schema-edit.draftNone') }}</p>
                <div v-for="g in draftGroups" :key="g.key" class="dg">
                  <div class="field-label">{{ $t('schema-edit.d.' + g.key) }} <span class="pill-count">{{ g.items.length }}</span></div>
                  <div class="ug-items">
                    <template v-for="x in g.items" :key="x">
                      <button v-if="byId.has(x)" class="link-btn mono" @click="select(x)">{{ x }}</button>
                      <span v-else class="mono faint">{{ x }}</span>
                    </template>
                  </div>
                </div>
                <div class="row mt12 small muted" style="flex-wrap: wrap">
                  <span v-if="draft.commits.length">{{ $t('schema-edit.draftCommits', { n: draft.commits.length }) }}</span>
                  <span v-if="draft.commits.length && draft.changes?.suggested_bump">{{ $t('schema-edit.draftBump', { b: draft.changes.suggested_bump }) }}</span>
                  <router-link v-if="draft.commits.length" class="btn btn-sm ml-auto" :to="{ name: 'releases' }">{{ $t('schema-edit.toReleases') }}</router-link>
                </div>
              </template>
            </div>
          </div>

          <div class="panel" data-testid="se-deprecated">
            <div class="panel-h"><h3>{{ $t('schema-edit.deprecatedList') }} <span class="pill-count">{{ deprecatedNodes.length }}</span></h3></div>
            <div class="panel-b">
              <p v-if="!deprecatedNodes.length" class="small faint">{{ $t('schema-edit.deprecatedNone') }}</p>
              <div v-else class="refs">
                <div v-for="n in deprecatedNodes" :key="n.id" class="r" :title="semText(n)">
                  <button class="link-btn mono" @click="select(n.id)">{{ n.id }}</button>
                  <span class="ml-auto small faint">→</span>
                  <button v-if="n.replaced_by" class="link-btn mono" @click="select(n.replaced_by)">{{ n.replaced_by }}</button>
                  <span v-else class="small faint">{{ $t('schema-edit.noReplacement') }}</span>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>

    <!-- 删除 / 废弃 -->
    <div v-if="modal && modalNode" class="modal-back" data-testid="se-modal" @click.self="closeModal">
      <div class="modal" style="width: min(680px, 100%)" role="dialog" aria-modal="true">
        <div class="modal-h">
          <Icon :name="modal === 'delete' ? 'trash' : 'warn'" />
          <h2>{{ modal === 'delete' ? $t('schema-edit.delTitle', { id: modalNode.id }) : $t('schema-edit.depTitle', { id: modalNode.id }) }}</h2>
          <button class="btn btn-ghost btn-icon" :title="$t('c.close')" @click="closeModal"><Icon name="x" small /></button>
        </div>
        <div class="modal-b">
          <p v-if="modalChecking" class="small faint">{{ $t('schema-edit.delChecking') }}</p>
          <template v-else-if="modal === 'delete' && modalUsage">
            <template v-if="modalUsage.blocking">
              <div class="notice err" data-testid="se-del-blocked">
                <Icon name="err" />
                <div class="grow"><b>{{ $t('schema-edit.delBlocked') }}</b><div class="small mt8">{{ $t('schema-edit.delBlockedHint') }}</div></div>
              </div>
              <div class="reflist mt12">
                <template v-for="g in modalGroups" :key="g.key">
                  <div class="g">{{ $t('schema-edit.u.' + g.key) }}<span class="pill-count">{{ g.items.length }}</span></div>
                  <div v-for="x in g.items.slice(0, USAGE_SHOW)" :key="x" class="it"><span>{{ x }}</span></div>
                  <div v-if="g.items.length > USAGE_SHOW" class="it"><span class="faint">{{ $t('schema-edit.more', { n: g.items.length - USAGE_SHOW }) }}</span></div>
                </template>
              </div>
            </template>
            <div v-else class="notice ok" data-testid="se-del-free"><Icon name="ok" /><div class="grow">{{ $t('schema-edit.delFree') }}</div></div>
          </template>
          <p v-if="modal === 'deprecate'" class="small muted">{{ $t('schema-edit.depHint') }}</p>
          <div v-if="modal === 'deprecate' || modalUsage?.blocking" class="field mt12">
            <label>{{ $t('schema-edit.replacedBy') }}</label>
            <select v-model="replacement" class="select mono" data-testid="se-replacement">
              <option value="">{{ $t('schema-edit.replacementOpt') }}</option>
              <option v-for="id in nodes.filter((n) => !n.deprecated && n.id !== modalNode!.id).map((n) => n.id).sort()" :key="id" :value="id">{{ id }}</option>
            </select>
          </div>
          <div v-if="modalError" class="notice err mt12">
            <Icon name="err" />
            <div class="grow small">{{ modalError.msg }}<ul v-if="modalError.details.length" class="errlist mt8"><li v-for="(d, i) in modalError.details" :key="i" class="mono">{{ d }}</li></ul></div>
          </div>
        </div>
        <div class="modal-f">
          <button class="btn" :disabled="modalBusy" @click="closeModal">{{ $t('c.cancel') }}</button>
          <template v-if="modal === 'delete'">
            <button
              v-if="!modalUsage || modalUsage.blocking" class="btn btn-danger" disabled
              :title="modalUsage ? $t('schema-edit.delStill') : ''"
            >{{ $t('c.delete') }}</button>
            <button v-else class="btn btn-danger-solid" :disabled="modalBusy" data-testid="se-del-confirm" @click="doDelete">{{ $t('schema-edit.delNode') }}</button>
            <button v-if="modalUsage?.blocking && !modalNode.deprecated" class="btn btn-primary" :disabled="modalBusy" data-testid="se-del-deprecate" @click="doDeprecate">{{ $t('schema-edit.markDeprecated') }}</button>
          </template>
          <button v-else class="btn btn-primary" :disabled="modalBusy" data-testid="se-dep-confirm" @click="doDeprecate">{{ $t('schema-edit.markDeprecated') }}</button>
        </div>
      </div>
    </div>

    <!-- 未保存修改的确认 -->
    <div v-if="pendingLeave" class="modal-back" data-testid="se-leave" @click.self="pendingLeave = null">
      <div class="modal" style="width: min(460px, 100%)" role="alertdialog" aria-modal="true">
        <div class="modal-h"><Icon name="warn" /><h2>{{ $t('schema-edit.unsaved') }}</h2></div>
        <div class="modal-b">{{ $t('schema-edit.confirmLeave') }}</div>
        <div class="modal-f">
          <button class="btn" data-testid="se-leave-cancel" @click="pendingLeave = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger" data-testid="se-leave-discard" @click="leaveConfirmed">{{ $t('schema-edit.discard') }}</button>
        </div>
      </div>
    </div>

    <div v-if="toast" class="toast" role="status" data-testid="se-toast"><Icon name="ok" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
.ro-fs { border: 0; padding: 0; margin: 0; min-width: 0; }
.se { flex: 1; min-height: 0; display: grid; gap: 10px; grid-template-columns: 290px minmax(0, 1fr) 360px; grid-template-areas: "tree edit side"; }
.p-tree { grid-area: tree; display: flex; flex-direction: column; overflow: hidden; }
.p-tree .tsearch { padding: 8px; border-bottom: 1px solid var(--line); display: flex; gap: 6px; }
.p-tree .scroll { flex: 1; padding: 6px; }
.tree .dom { font: 600 12px var(--font-ui); color: var(--ink-2); padding: 10px 8px 4px; display: flex; gap: 6px; align-items: center; }
.tree .dom .cnt { margin-left: auto; font-weight: 400; color: var(--ink-3); font-size: 11px; }
.tree .ti .dirty { width: 6px; height: 6px; border-radius: 50%; background: var(--amber); flex: none; margin-left: auto; }
.tree .ti .tg { margin-left: auto; height: 16px; font-size: 10.5px; padding: 0 5px; }
.tree .ti .tg.deprecated { text-decoration: none; }
.tree .ti .sf-mini { font: 10.5px var(--font-mono); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 0 1 auto; }
.tree .ti.is-sel .sf-mini { color: var(--blue-ink); opacity: .75; }
.edit-col { grid-area: edit; overflow: auto; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
.side-col { grid-area: side; overflow: auto; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
.nh { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.nh .nid { font: 600 16px var(--font-mono); overflow-wrap: anywhere; }
.semhint { margin-top: -6px; }
.etbl td, .etbl th { font-size: 12px; }
.etype { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; font-weight: 600; }
.etype i { width: 18px; height: 3px; border-radius: 2px; display: inline-block; }
.refs { display: flex; flex-direction: column; gap: 2px; }
.refs .r { display: flex; align-items: center; gap: 8px; padding: 5px 2px; border-bottom: 1px solid var(--line); font-size: 12.5px; flex-wrap: wrap; }
.refs .r:last-child { border-bottom: 0; }
.ug { border-bottom: 1px solid var(--line); }
.ug:last-child { border-bottom: 0; }
.ug summary { display: flex; align-items: center; gap: 8px; padding: 6px 2px; font-size: 12.5px; cursor: pointer; list-style: none; }
.ug summary::-webkit-details-marker { display: none; }
.ug summary::before { content: "›"; color: var(--ink-3); width: 10px; transition: transform .15s; }
.ug[open] summary::before { transform: rotate(90deg); }
.ug summary .n { margin-left: auto; font-weight: 600; }
.ug-items { display: flex; flex-direction: column; gap: 3px; padding: 0 0 8px 18px; font-size: 12px; align-items: flex-start; }
.ug-items .mono { overflow-wrap: anywhere; text-align: left; }
.dg + .dg { margin-top: 10px; }
.dg .ug-items { padding-left: 0; padding-top: 4px; }
.errlist { margin: 0; padding-left: 18px; }
.reflist { max-height: 340px; overflow: auto; border: 1px solid var(--line); border-radius: 6px; }
.reflist .g { font: 600 12px var(--font-ui); padding: 7px 10px; background: var(--surface-2); border-bottom: 1px solid var(--line); display: flex; gap: 8px; align-items: center; position: sticky; top: 0; }
.reflist .g .pill-count { margin-left: auto; }
.reflist .it { padding: 5px 10px 5px 30px; font: 12px var(--font-mono); border-bottom: 1px solid var(--line); display: flex; gap: 8px; overflow-wrap: anywhere; }
@media (max-width: 1240px) {
  .page.fill { height: auto; }
  .se { grid-template-columns: 250px minmax(0, 1fr); grid-template-areas: "tree edit" "tree side"; grid-template-rows: auto auto; flex: none; overflow: visible; align-items: start; }
  .edit-col, .side-col { overflow: visible; }
  .p-tree { height: calc(100vh - 150px); position: sticky; top: 10px; }
}
</style>
