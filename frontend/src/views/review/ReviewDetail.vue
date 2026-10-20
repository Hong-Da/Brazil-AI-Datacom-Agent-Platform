<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { get, post, errorText } from '@/api'
import Icon from '@/components/Icon.vue'
import { useAuth } from '@/stores/auth'
import {
  APPROVABLE, EDIT_FIELDS, KIND_TONE, changedFields, isAi, previewComplete, rejectNote, splitTitle,
  unknownCardEmpty, unknownCardReady, type EditField, type ReviewItem, type UnknownCard,
} from './logic'
import { AI_KB_KINDS } from './logic'
import KbReviewItem from '@/components/ai-kb/KbReviewItem.vue'
import CardReviewAid from '@/components/ai-kb/CardReviewAid.vue'

const props = defineProps<{ itemId: number | null }>()
const emit = defineEmits<{ decided: [id: number, approved: boolean] }>()
const { t } = useI18n()
const auth = useAuth()

const item = ref<ReviewItem | null>(null)
const loading = ref(false)
const loadError = ref('')
const actError = ref('')
const busy = ref(false)
const mode = ref<'view' | 'edit' | 'reject'>('view')
const note = ref('')
const reason = ref('wrong')
const rejectExtra = ref('')
const form = reactive<Record<EditField, string>>({ syntax: '', view: '', enters_view: '', undo: '', default: '' })
const ucard = reactive<UnknownCard>({ id: '', syntax: '', view: '', family: '', domain: '' })
const conflictText = ref('')
const kbItem = ref<InstanceType<typeof KbReviewItem> | null>(null) // M8-5 AI 草稿（rule / unknown_card / card_maps）

const REASONS = ['wrong', 'mapping', 'duplicate', 'scope', 'other'] as const
const DOMAINS = ['interface', 'vrf', 'static-route', 'bgp', 'routing-policy']

async function load(): Promise<void> {
  item.value = null
  mode.value = 'view'
  actError.value = ''
  loadError.value = ''
  if (props.itemId == null) return
  loading.value = true
  const id = props.itemId
  try {
    const it = await get<ReviewItem>(`/review/${id}`)
    if (props.itemId === id) item.value = it
  } catch (e) {
    if (props.itemId === id) loadError.value = errorText(e)
  } finally {
    if (props.itemId === id) loading.value = false
  }
}
watch(() => props.itemId, load, { immediate: true })

const payload = computed(() => (item.value?.payload ?? {}) as Record<string, unknown>)
const card = computed(() => (payload.value.card ?? null) as Record<string, unknown> | null)
const parts = computed(() => (item.value ? splitTitle(item.value.title, item.value.target) : { id: '', text: '' }))
const heading = computed(() => (item.value?.kind === 'card' ? parts.value.text : item.value?.title ?? ''))
const approvable = computed(() => !!item.value && APPROVABLE.has(item.value.kind))
const examples = computed(() => (payload.value.examples ?? []) as { text: string; view?: string; device?: string }[])
const preview = computed(() => String(payload.value.theirs_preview ?? ''))
const canEdit = computed(() => {
  const k = item.value?.kind
  if (k === 'card' || k === 'unknown_line' || AI_KB_KINDS.has(k ?? '')) return true
  return k === 'conflict' && previewComplete(preview.value)
})

/** 命令卡完整字段（“文档有变化”类条目才带）按 key: value 显示。 */
const cardText = computed(() => {
  if (!card.value) return ''
  return Object.entries(card.value)
    .filter(([, v]) => v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join('\n')
})
const maps = computed(() => {
  const m = card.value?.maps
  if (!m) return [] as string[]
  if (Array.isArray(m)) return m.map((x) => (typeof x === 'string' ? x : JSON.stringify(x)))
  if (typeof m === 'object') return Object.keys(m as object)
  return [String(m)]
})

function cardOriginal(): Partial<Record<EditField, unknown>> {
  const c = card.value ?? {}
  return { syntax: c.syntax ?? parts.value.text, view: c.view, enters_view: c.enters_view, undo: c.undo, default: c.default }
}

function startEdit(): void {
  if (!item.value || !canEdit.value) return
  actError.value = ''
  if (item.value.kind === 'card') {
    const o = cardOriginal()
    for (const k of EDIT_FIELDS) form[k] = o[k] == null ? '' : typeof o[k] === 'object' ? JSON.stringify(o[k]) : String(o[k])
  } else if (item.value.kind === 'unknown_line') {
    Object.assign(ucard, { id: '', syntax: String(payload.value.pattern ?? item.value.target).trim(), view: examples.value[0]?.view ?? '', family: '', domain: '' })
  } else if (item.value.kind === 'conflict') {
    conflictText.value = preview.value
  }
  mode.value = 'edit'
}
function startReject(): void {
  if (!item.value) return
  actError.value = ''
  mode.value = 'reject'
}

async function decide(approve: boolean): Promise<void> {
  if (!auth.isKbEditor) return
  const it = item.value
  if (!it || busy.value) return
  if (approve && !approvable.value) return
  let edited: Record<string, unknown> | null = null
  if (approve && mode.value === 'edit') {
    if (it.kind === 'card') edited = changedFields(cardOriginal(), form)
    else if (it.kind === 'unknown_line') {
      if (!unknownCardEmpty(ucard)) {
        if (!unknownCardReady(ucard)) { actError.value = t('review.cardIncomplete'); return }
        edited = { card: { ...ucard } }
      }
    } else if (it.kind === 'conflict' && conflictText.value !== preview.value) edited = { text: conflictText.value }
    else if (AI_KB_KINDS.has(it.kind)) {
      const r = kbItem.value?.edited() ?? null
      if (r && 'error' in r) { actError.value = String(r.error); return }
      edited = r
    }
  }
  const n = approve ? note.value.trim() : rejectNote(t(`review.reason_${reason.value}`), rejectExtra.value)
  busy.value = true
  actError.value = ''
  try {
    await post(`/review/${it.id}`, { action: approve ? 'approve' : 'reject', note: n, edited })
    note.value = ''
    rejectExtra.value = ''
    emit('decided', it.id, approve)
  } catch (e) {
    actError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

defineExpose({
  approve: () => { if (mode.value !== 'reject') void decide(true) },
  edit: startEdit,
  reject: startReject,
})
</script>

<template>
  <section class="panel rv-detail" data-testid="review-detail">
    <div v-if="itemId == null" class="empty" style="margin: auto"><p>{{ $t('review.pick') }}</p></div>
    <div v-else-if="loading" class="empty" style="margin: auto"><p>{{ $t('c.loading') }}</p></div>
    <div v-else-if="loadError" class="d-body">
      <div class="notice err"><Icon name="err" /><div class="grow small">{{ loadError }}</div>
        <button class="btn btn-xs" type="button" @click="load">{{ $t('c.retry') }}</button></div>
    </div>
    <template v-else-if="item">
      <div class="d-body">
        <div class="d-head">
          <div style="min-width: 0; flex: 1">
            <div class="row" style="gap: 6px; margin-bottom: 6px; flex-wrap: wrap">
              <span :class="['typ', KIND_TONE[item.kind] ?? 'card']">{{ $te(`review.kind_${item.kind}`) ? $t(`review.kind_${item.kind}`) : item.kind }}</span>
              <span v-if="item.kind === 'card'" :class="['srcb', { ai: isAi(item.source) }]">
                <Icon v-if="isAi(item.source)" name="spark" small />{{ isAi(item.source) ? 'AI' : $t('review.rule') }}
              </span>
              <span :class="['tag', item.status]">{{ $te(`review.status_${item.status}`) ? $t(`review.status_${item.status}`) : item.status }}</span>
              <span class="faint small mono">#{{ item.id }}</span>
            </div>
            <h2>{{ heading }}</h2>
          </div>
        </div>

        <!-- 来源 -->
        <div v-if="item.source && Object.keys(item.source).length" class="srcref" data-testid="review-source">
          <span class="ico"><Icon :name="item.kind === 'conflict' ? 'zip' : 'book'" /></span>
          <div style="min-width: 0; flex: 1">
            <template v-if="item.kind === 'conflict'">
              <div><b>{{ $t('review.fromPackage') }}</b><span v-if="item.source.kb_version" class="mono small"> · KB {{ item.source.kb_version }}</span></div>
              <div class="p">{{ item.target }}</div>
            </template>
            <template v-else-if="item.kind === 'unknown_line'">
              <div><b>{{ $t('review.fromUnknown') }}</b></div>
            </template>
            <template v-else-if="item.source.method === 'ai'">
              <div><b>{{ $t('kb-ai.rv.fromAi') }}</b><span v-if="item.source.skill" class="mono small faint"> · {{ item.source.skill }}</span></div>
            </template>
            <template v-else>
              <div><b>{{ item.source.title || item.source.file || item.source.doc }}</b><span v-if="item.source.version" class="mono small faint"> · {{ item.source.version }}</span></div>
              <div v-if="item.source.file" class="p">{{ item.source.doc ? item.source.doc + ' / ' : '' }}{{ item.source.file }}<span v-if="item.source.line">:{{ item.source.line }}</span></div>
              <div v-if="item.source.rules" class="small faint mt8">{{ $t('review.rules') }}<span class="mono">{{ item.source.rules }}</span></div>
            </template>
          </div>
        </div>

        <div v-if="!approvable" class="notice warn mt12"><Icon name="warn" /><div class="grow small">{{ $t('review.noAction') }}</div></div>

        <!-- 命令卡 -->
        <template v-if="item.kind === 'card'">
          <div class="section-t" style="margin-top: 18px">{{ isAi(item.source) ? $t('review.aiResult') : $t('review.extracted') }}</div>
          <div v-if="mode === 'edit'" class="form-grid" data-testid="review-edit-card">
            <div v-for="k in EDIT_FIELDS" :key="k" :class="['field', { span2: k === 'syntax' }]">
              <label>{{ $t(`review.f_${k}`) }}</label>
              <input v-model="form[k]" class="input mono" spellcheck="false" />
            </div>
            <p class="small faint span2">{{ $t('review.editHint') }}</p>
          </div>
          <template v-else>
            <dl class="kv">
              <dt>{{ $t('review.cardId') }}</dt><dd class="mono">{{ item.target }}</dd>
              <dt>{{ $t('review.f_syntax') }}</dt><dd class="mono">{{ card?.syntax ?? parts.text }}</dd>
              <template v-if="card?.view"><dt>{{ $t('review.f_view') }}</dt><dd class="mono">{{ card.view }}</dd></template>
              <dt>{{ $t('review.action') }}</dt><dd>{{ payload.action === 'update' ? $t('review.actionUpdate') : $t('review.actionNew') }}</dd>
              <template v-if="payload.file"><dt>{{ $t('review.file') }}</dt><dd class="mono small">{{ payload.file }}</dd></template>
            </dl>
            <pre v-if="cardText" class="block yaml mt12">{{ cardText }}</pre>
            <p v-else class="small faint mt12">{{ $t('review.cardInFile') }}</p>
          </template>
          <template v-if="maps.length">
            <div class="section-t" style="margin-top: 18px">{{ $t('review.related') }}</div>
            <div class="rel"><span v-for="m in maps" :key="m" class="tag mono">{{ m }}</span></div>
          </template>
          <CardReviewAid :key="item.target" :card-id="item.target" />
        </template>

        <!-- M8-5 AI 建议采纳后的知识库草稿 -->
        <KbReviewItem v-else-if="AI_KB_KINDS.has(item.kind)" ref="kbItem" :item="item" :editing="mode === 'edit'" />

        <!-- 未识别行 -->
        <template v-else-if="item.kind === 'unknown_line'">
          <div class="section-t" style="margin-top: 18px">{{ $t('review.pattern') }}</div>
          <div class="code" style="border: 1px solid var(--line); border-radius: 6px">
            <div class="l unknown"><span class="g"><span class="gmark unk">?</span></span><span class="t">{{ payload.pattern ?? item.target }}</span></div>
          </div>
          <dl class="kv mt12">
            <dt>{{ $t('review.occurrences') }}</dt><dd>{{ $t('review.times', { n: payload.count ?? '—' }) }}</dd>
          </dl>
          <table v-if="examples.length" class="tbl compact mt12">
            <thead><tr><th>{{ $t('review.device') }}</th><th>{{ $t('review.f_view') }}</th><th>{{ $t('review.line') }}</th></tr></thead>
            <tbody><tr v-for="(x, i) in examples" :key="i"><td class="mono small">{{ x.device }}</td><td class="mono small">{{ x.view || '—' }}</td><td class="mono small ws">{{ x.text }}</td></tr></tbody>
          </table>
          <p class="small muted mt12">{{ $t('review.unknownHint') }}</p>
          <div v-if="mode === 'edit'" class="form-grid mt12" data-testid="review-edit-unknown">
            <div class="field"><label>{{ $t('review.cardId') }}</label><input v-model="ucard.id" class="input mono" placeholder="huawei-vrp8.port-mode" /></div>
            <div class="field"><label>{{ $t('review.f_view') }}</label><input v-model="ucard.view" class="input mono" placeholder="interface" /></div>
            <div class="field span2"><label>{{ $t('review.f_syntax') }}</label><input v-model="ucard.syntax" class="input mono" spellcheck="false" /></div>
            <div class="field"><label>{{ $t('review.family') }}</label><input v-model="ucard.family" class="input mono" placeholder="huawei-vrp8 / cisco-iosxe" /></div>
            <div class="field"><label>{{ $t('review.domain') }}</label>
              <select v-model="ucard.domain" class="select mono"><option value="" />
                <option v-for="d in DOMAINS" :key="d" :value="d">{{ d }}</option></select></div>
            <p class="small faint span2">{{ $t('review.unknownEditHint') }}</p>
          </div>
          <p class="small mt12"><router-link :to="{ name: 'unknown-lines' }">{{ $t('review.seeUnknown') }}</router-link></p>
        </template>

        <!-- 导入冲突 -->
        <template v-else-if="item.kind === 'conflict'">
          <div class="section-t" style="margin-top: 18px">{{ $t('review.conflictTitle') }}</div>
          <dl class="kv small">
            <dt>{{ $t('review.file') }}</dt><dd class="mono">{{ item.target }}</dd>
            <dt>{{ $t('review.oursSha') }}</dt><dd class="mono faint">{{ payload.ours_sha256 }}</dd>
            <dt>{{ $t('review.theirsSha') }}</dt><dd class="mono faint">{{ payload.theirs_sha256 }}</dd>
          </dl>
          <div class="conf-side mt12">
            <div class="h">{{ $t('review.incoming') }}<span v-if="!previewComplete(preview)" class="tag" style="margin-left: auto">{{ $t('review.truncated') }}</span></div>
            <textarea v-if="mode === 'edit'" v-model="conflictText" class="textarea mono yaml" spellcheck="false" data-testid="review-edit-conflict" />
            <pre v-else>{{ preview }}</pre>
          </div>
          <p class="small muted mt12">{{ $t('review.conflictHint') }}</p>
        </template>

        <!-- 其他类型 -->
        <template v-else>
          <dl class="kv mt12"><dt>{{ $t('review.target') }}</dt><dd class="mono">{{ item.target }}</dd></dl>
          <pre v-if="item.payload" class="block mt12">{{ JSON.stringify(item.payload, null, 2) }}</pre>
        </template>

        <div v-if="item.note" class="notice info mt12"><Icon name="info" /><div class="grow small">{{ item.note }}</div></div>
        <div v-if="actError" class="notice err mt12" data-testid="review-error"><Icon name="err" /><div class="grow small">{{ actError }}</div></div>
      </div>

      <div v-if="item.status !== 'pending'" class="actbar"><span class="hint">{{ $t('review.decided') }}</span></div>
      <div v-else-if="!auth.isKbEditor" class="actbar" data-testid="review-ro"><span class="hint"><Icon name="lock" small /> {{ $t('review.roNote') }}</span></div>
      <div v-else-if="mode === 'reject'" class="reject-box" data-testid="review-reject-box">
        <span class="small" style="color: var(--red-ink); font-weight: 600">{{ $t('review.reason') }}</span>
        <select v-model="reason" class="select" data-testid="review-reason">
          <option v-for="r in REASONS" :key="r" :value="r">{{ $t(`review.reason_${r}`) }}</option>
        </select>
        <input v-model="rejectExtra" class="input" :placeholder="$t('review.noteOptional')" @keydown.enter="decide(false)" />
        <button class="btn btn-sm" type="button" @click="mode = 'view'">{{ $t('c.cancel') }}</button>
        <button class="btn btn-sm btn-danger-solid" type="button" :disabled="busy" data-testid="review-confirm-reject" @click="decide(false)">
          {{ item.kind === 'conflict' ? $t('review.keepCurrent') : $t('review.confirmReject') }}
        </button>
      </div>
      <div v-else class="actbar">
        <span class="hint">
          <span><span class="kbd">A</span> {{ $t('review.k_approve') }}</span>
          <span><span class="kbd">E</span> {{ $t('review.k_edit') }}</span>
          <span><span class="kbd">R</span> {{ $t('review.k_reject') }}</span>
          <span><span class="kbd">J</span>/<span class="kbd">K</span> {{ $t('review.k_nav') }}</span>
        </span>
        <input v-model="note" class="input note-in" :placeholder="$t('review.noteOptional')" data-testid="review-note" />
        <template v-if="mode === 'edit'">
          <button class="btn" type="button" @click="mode = 'view'">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="busy" data-testid="review-save-approve" @click="decide(true)">
            <Icon name="check" small />{{ $t('review.saveApprove') }}
          </button>
        </template>
        <template v-else>
          <button class="btn btn-danger" type="button" :disabled="busy" data-testid="review-reject" @click="startReject">
            <Icon name="x" small />{{ item.kind === 'conflict' ? $t('review.keepCurrent') : $t('c.reject') }}
          </button>
          <button v-if="canEdit && approvable" class="btn" type="button" :disabled="busy" data-testid="review-edit" @click="startEdit">
            <Icon name="sliders" small />{{ item.kind === 'unknown_line' ? $t('review.attachCard') : $t('review.editApprove') }}
          </button>
          <button class="btn btn-primary" type="button" :disabled="busy || !approvable" data-testid="review-approve" @click="decide(true)">
            <Icon name="check" small />{{ item.kind === 'conflict' ? $t('review.takeIncoming') : item.kind === 'unknown_line' ? $t('review.approveRaw') : $t('c.approve') }}
          </button>
        </template>
      </div>
    </template>
  </section>
</template>

<style scoped>
.rv-detail { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.d-body { flex: 1; overflow: auto; padding: 16px 18px; }
.d-head { display: flex; gap: 10px; align-items: flex-start; }
.d-head h2 { font: 600 15px var(--font-mono); overflow-wrap: anywhere; }
.typ { font-size: 11px; font-weight: 600; padding: 0 6px; height: 18px; border-radius: 3px; display: inline-flex; align-items: center; white-space: nowrap; }
.typ.card { background: var(--blue-soft); color: var(--blue-ink); }
.typ.node { background: var(--teal-soft); color: var(--teal-ink); }
.typ.unknown { background: var(--red-soft); color: var(--red-ink); }
.typ.conflict { background: var(--amber-soft); color: var(--amber-ink); }
.srcb { font-size: 11px; color: var(--ink-2); border: 1px solid var(--line); border-radius: 3px; padding: 0 5px; height: 18px; display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.srcb.ai { color: var(--violet); border-color: color-mix(in srgb, var(--violet) 40%, transparent); }
.srcb :deep(.ico) { width: 11px; height: 11px; }
.srcref { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); margin-top: 12px; }
.srcref .ico { color: var(--ink-3); margin-top: 2px; }
.srcref .p { font: 11.5px var(--font-mono); color: var(--ink-2); overflow-wrap: anywhere; margin-top: 2px; }
.yaml { min-height: 160px; }
textarea.yaml { width: 100%; min-height: 260px; border: 0; border-radius: 0; }
.rel { display: flex; flex-wrap: wrap; gap: 6px; }
.conf-side { border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.conf-side .h { padding: 7px 10px; font-size: 12px; font-weight: 600; background: var(--surface-2); border-bottom: 1px solid var(--line); display: flex; gap: 6px; align-items: center; }
.conf-side pre { margin: 0; padding: 10px; font: 12px/1.6 var(--font-mono); white-space: pre-wrap; max-height: 420px; overflow: auto; color: var(--ink); }
.actbar { display: flex; gap: 8px; align-items: center; padding: 10px 18px; border-top: 1px solid var(--line); background: var(--surface); flex-wrap: wrap; }
.actbar .hint { font-size: 11.5px; color: var(--ink-3); margin-right: auto; display: flex; gap: 10px; }
.actbar .note-in { width: 180px; }
.reject-box { display: flex; gap: 8px; align-items: center; padding: 10px 18px; border-top: 1px solid var(--red-line); background: var(--red-soft); flex-wrap: wrap; }
.reject-box .select { width: auto; }
.reject-box .input { flex: 1; min-width: 160px; }
.ws { white-space: pre; }
@media (max-width: 1100px) { .actbar .hint { display: none; } }
</style>
