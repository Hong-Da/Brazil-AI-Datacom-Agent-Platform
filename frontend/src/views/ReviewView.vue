<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { get, errorText } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import ReviewDetail from './review/ReviewDetail.vue'
import BatchDialog from './review/BatchDialog.vue'
import {
  KIND_TONE, age, isAi, nextId, offsetAfterRemoval, pageRange, sortedKinds, sourceLine, splitTitle, totalCount,
  type ReviewList,
} from './review/logic'

const LIMIT = 50
const { t, te } = useI18n()
const route = useRoute()
const router = useRouter()
const status = useStatus()

const kind = ref(typeof route.query.kind === 'string' ? route.query.kind : '')
const offset = ref(0)
const data = ref<ReviewList | null>(null)
const loading = ref(true)
const error = ref('')
const selected = ref<number | null>(null)
const showBatch = ref(false)
const toast = ref('')
const done = ref<{ approved: number; rejected: number } | null>(null)
const detail = ref<InstanceType<typeof ReviewDetail> | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | undefined

const counts = computed(() => data.value?.counts ?? {})
const kinds = computed(() => sortedKinds(counts.value))
const allTotal = computed(() => totalCount(counts.value))
const items = computed(() => data.value?.items ?? [])
const range = computed(() => pageRange(offset.value, items.value.length, data.value?.total ?? 0))
const isEmpty = computed(() => !!data.value && allTotal.value === 0)

function kindName(k: string): string { return te(`review.kind_${k}`) ? t(`review.kind_${k}`) : k }
function ageText(iso: string | null): string {
  const a = age(iso)
  return a ? t(`review.age_${a[1]}`, { n: a[0] }) : ''
}
function rowTitle(it: { kind: string; title: string; target: string }): string {
  return it.kind === 'card' ? splitTitle(it.title, it.target).text : it.title
}

async function load(keepSelection = true): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const q = new URLSearchParams({ status: 'pending', limit: String(LIMIT), offset: String(offset.value) })
    if (kind.value) q.set('kind', kind.value)
    const d = await get<ReviewList>(`/review?${q}`)
    data.value = d
    if (!d.items.length && offset.value > 0 && d.total > 0) {
      offset.value = Math.max(0, Math.floor((d.total - 1) / LIMIT) * LIMIT)
      return load(keepSelection)
    }
    const ids = d.items.map((i) => i.id)
    if (!keepSelection || selected.value == null || !ids.includes(selected.value)) selected.value = ids[0] ?? null
    if (totalCount(d.counts) === 0) void loadDone()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

/** 队列为空时显示已经处理过多少（通过 / 驳回）。 */
async function loadDone(): Promise<void> {
  try {
    const [a, r] = await Promise.all([
      get<ReviewList>('/review?status=approved&limit=1'),
      get<ReviewList>('/review?status=rejected&limit=1'),
    ])
    done.value = { approved: a.total, rejected: r.total }
  } catch { done.value = null }
}

function setKind(k: string): void {
  kind.value = k
  offset.value = 0
  void router.replace({ query: { ...route.query, kind: k || undefined } })
  void load(false)
}
function page(dir: 1 | -1): void {
  offset.value = Math.max(0, offset.value + dir * LIMIT)
  void load(false)
}

function showToast(msg: string): void {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 2600)
}

async function onDecided(id: number, approved: boolean): Promise<void> {
  showToast(approved ? t('review.approvedToast') : t('review.rejectedToast'))
  const ids = items.value.map((i) => i.id)
  const nx = nextId(ids, id)
  selected.value = nx === id ? null : nx
  offset.value = offsetAfterRemoval(offset.value, ids.length - 1, LIMIT)
  await load(true)
  void status.refresh()
}
function onBatchDone(n: number): void {
  if (n) showToast(t('review.batchToast', { n }))
  void load(false)
  void status.refresh()
}

function move(step: 1 | -1): void {
  const ids = items.value.map((i) => i.id)
  const i = selected.value == null ? -1 : ids.indexOf(selected.value)
  const n = ids[i + step]
  if (n != null) {
    selected.value = n
    document.querySelector(`[data-rid="${n}"]`)?.scrollIntoView({ block: 'nearest' })
  }
}
function onKey(e: KeyboardEvent): void {
  const el = e.target as HTMLElement | null
  if (showBatch.value || e.ctrlKey || e.metaKey || e.altKey) return
  if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return
  const k = e.key.toLowerCase()
  if (k === 'j') move(1)
  else if (k === 'k') move(-1)
  else if (k === 'a') detail.value?.approve()
  else if (k === 'e') detail.value?.edit()
  else if (k === 'r') detail.value?.reject()
}

watch(() => route.query.kind, (k) => {
  const v = typeof k === 'string' ? k : ''
  if (v !== kind.value) { kind.value = v; offset.value = 0; void load(false) }
})
onMounted(() => { void load(false); window.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { window.removeEventListener('keydown', onKey); clearTimeout(toastTimer) })
</script>

<template>
  <main class="main">
    <div class="page fill">
      <div class="ph" style="margin-bottom: 10px">
        <div class="ph-text">
          <h1>{{ $t('review.title') }}</h1>
          <p class="ph-sub">{{ $t('review.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-sm" type="button" :disabled="loading" data-testid="review-refresh" @click="load(true)"><Icon name="refresh" small />{{ $t('c.refresh') }}</button>
          <button v-if="!isEmpty && data" class="btn btn-sm btn-primary" type="button" data-testid="review-batch-open" @click="showBatch = true">
            <Icon name="check" small />{{ $t('review.batchOpen') }}
          </button>
        </div>
      </div>

      <div v-if="error && !data" class="panel" style="flex: 1">
        <div class="empty" data-testid="review-error-state"><p>{{ error }}</p><button class="btn btn-sm" type="button" @click="load(false)">{{ $t('c.retry') }}</button></div>
      </div>
      <div v-else-if="!data" class="panel" style="flex: 1"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>

      <!-- 队列为空 -->
      <div v-else-if="isEmpty" class="panel" style="flex: 1" data-testid="review-empty">
        <div class="empty" style="padding: 70px 24px">
          <svg class="art" viewBox="0 0 120 84" aria-hidden="true">
            <path d="M60 6 L104 24 L60 42 L16 24 Z" fill="var(--amber-soft)" stroke="var(--amber-line)" />
            <path d="M16 38 L60 56 L104 38" fill="none" stroke="var(--teal-line)" stroke-width="2" />
            <path d="M16 52 L60 70 L104 52" fill="none" stroke="var(--blue-line)" stroke-width="2" />
            <path d="M46 24 l9 7 l18 -14" fill="none" stroke="var(--teal)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <h3>{{ $t('review.emptyTitle') }}</h3>
          <p>
            <template v-if="done && (done.approved || done.rejected)">{{ $t('review.emptyDone', { ok: done.approved, no: done.rejected }) }}</template>
            {{ $t('review.emptyHint') }}
          </p>
          <div class="row">
            <router-link class="btn btn-primary" :to="{ name: 'ingest' }"><Icon name="book" small /><span>{{ $t('review.goIngest') }}</span></router-link>
            <router-link class="btn" :to="{ name: 'unknown-lines' }">{{ $t('review.goUnknown') }}</router-link>
            <router-link class="btn btn-ghost" :to="{ name: 'releases' }">{{ $t('review.goReleases') }}</router-link>
          </div>
        </div>
      </div>

      <template v-else>
        <div class="toolbar" style="margin-bottom: 10px">
          <select class="select" :value="kind" data-testid="review-kind" @change="setKind(($event.target as HTMLSelectElement).value)">
            <option value="">{{ $t('review.allTypes') }}（{{ allTotal }}）</option>
            <option v-for="k in kinds" :key="k" :value="k">{{ kindName(k) }}（{{ counts[k] }}）</option>
            <option v-if="kind && !kinds.includes(kind)" :value="kind">{{ kindName(kind) }}（0）</option>
          </select>
          <span class="grow" />
          <span class="sumline" data-testid="review-counts">
            <span>{{ $t('review.total') }} <b>{{ allTotal }}</b></span>
            <span v-for="k in kinds" :key="k">{{ kindName(k) }} <b>{{ counts[k] }}</b></span>
          </span>
        </div>

        <div class="rv">
          <section class="panel rv-list">
            <div class="batch">
              <span data-testid="review-range">{{ range.total ? $t('review.range', range) : $t('review.noneOfKind') }}</span>
              <span class="grow" />
              <span class="faint">{{ $t('review.oldestFirst') }}</span>
              <button class="btn btn-xs btn-icon" type="button" :disabled="loading || offset === 0" :aria-label="$t('review.prev')" data-testid="review-prev" @click="page(-1)">‹</button>
              <button class="btn btn-xs btn-icon" type="button" :disabled="loading || range.to >= range.total" :aria-label="$t('review.next')" data-testid="review-next" @click="page(1)">›</button>
            </div>
            <div v-if="error" class="notice err" style="margin: 8px"><Icon name="err" /><div class="grow small">{{ error }}</div></div>
            <div :class="['items', { dim: loading }]" data-testid="review-list">
              <div
                v-for="it in items" :key="it.id" :data-rid="it.id" :class="['it', { 'is-sel': it.id === selected }]"
                role="button" tabindex="0" @click="selected = it.id" @keydown.enter="selected = it.id"
              >
                <div style="min-width: 0">
                  <div class="t1">
                    <span :class="['typ', KIND_TONE[it.kind] ?? 'card']">{{ kindName(it.kind) }}</span>
                    <span v-if="it.kind === 'card'" :class="['srcb', { ai: isAi(it.source) }]">{{ isAi(it.source) ? 'AI' : $t('review.rule') }}</span>
                    <span v-if="it.source?.rules" class="mono faint" style="font-size: 11px">{{ it.source.rules }}</span>
                    <span class="age">{{ ageText(it.created_at) }}</span>
                  </div>
                  <div class="ttl">{{ rowTitle(it) }}</div>
                  <div class="t3">{{ it.kind === 'card' ? it.target : '' }}{{ it.kind === 'card' && sourceLine(it.source) ? ' · ' : '' }}{{ sourceLine(it.source) }}</div>
                </div>
              </div>
              <div v-if="!items.length && !loading" class="empty">
                <p>{{ $t('review.noneOfKind') }}</p>
                <button class="btn btn-sm" type="button" @click="setKind('')">{{ $t('review.clearFilter') }}</button>
              </div>
            </div>
          </section>
          <ReviewDetail ref="detail" :item-id="selected" @decided="onDecided" />
        </div>
      </template>
    </div>

    <BatchDialog v-if="showBatch" :counts="counts" :initial-kind="kind || 'card'" @close="showBatch = false" @done="onBatchDone" />
    <div v-if="toast" class="toast" role="status" data-testid="review-toast"><Icon name="check" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
.rv { flex: 1; min-height: 0; display: grid; grid-template-columns: 420px minmax(0, 1fr); gap: 12px; }
@media (max-width: 1300px) { .rv { grid-template-columns: 360px minmax(0, 1fr); } }
@media (max-width: 1100px) { .rv { grid-template-columns: 310px minmax(0, 1fr); } .it .t1 .mono { display: none; } }
.rv-list { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.batch { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--surface-2); font-size: 12px; min-height: 42px; }
.items { flex: 1; overflow: auto; }
.items.dim { opacity: .6; }
.it { padding: 9px 12px; border-bottom: 1px solid var(--line); cursor: pointer; }
.it:hover { background: var(--surface-2); }
.it:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.it.is-sel { background: var(--blue-soft); box-shadow: inset 3px 0 0 var(--blue); }
.it .t1 { display: flex; gap: 6px; align-items: center; min-width: 0; }
.it .t1 .mono { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.it .ttl { font: 12px var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 3px; color: var(--ink); }
.it .t3 { font-size: 11.5px; color: var(--ink-3); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.it .age { margin-left: auto; font-size: 11px; color: var(--ink-3); white-space: nowrap; }
.typ { font-size: 11px; font-weight: 600; padding: 0 6px; height: 18px; border-radius: 3px; display: inline-flex; align-items: center; white-space: nowrap; }
.typ.card { background: var(--blue-soft); color: var(--blue-ink); }
.typ.node { background: var(--teal-soft); color: var(--teal-ink); }
.typ.unknown { background: var(--red-soft); color: var(--red-ink); }
.typ.conflict { background: var(--amber-soft); color: var(--amber-ink); }
.srcb { font-size: 11px; color: var(--ink-2); border: 1px solid var(--line); border-radius: 3px; padding: 0 5px; height: 18px; display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.srcb.ai { color: var(--violet); border-color: color-mix(in srgb, var(--violet) 40%, transparent); }
.sumline { display: flex; gap: 16px; font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
.sumline b { color: var(--ink); }
</style>
