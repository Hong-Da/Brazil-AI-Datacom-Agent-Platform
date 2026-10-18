<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError, get, post, download, errorText } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import { useAuth } from '@/stores/auth'
import RegressionPanel from './releases/RegressionPanel.vue'
import DiffTables from './releases/DiffTables.vue'
import {
  SEMVER, bumpCounts, changeRows, changelog, diffCounts, fmtTime, fmtValue, regressionStale, releaseFailure,
  samplePassed, suggestVersion, type DraftData, type KbDiff, type Regression, type ReleaseFailure, type ReleasesData,
} from './releases/logic'

type Tab = 'draft' | 'diff' | 'log'
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const status = useStatus()
const auth = useAuth() // 发布、回滚只有管理员可以做（REQ-030）

const tab = ref<Tab>((['draft', 'diff', 'log'] as const).find((x) => x === route.query.tab) ?? 'draft')
const rel = ref<ReleasesData | null>(null)
const draft = ref<DraftData | null>(null)
const reg = ref<Regression | null>(null)
const loading = ref(true)
const error = ref('')
const regRunning = ref(false)
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined

// 发布
const version = ref('')
const message = ref('')
const publishing = ref(false)
const pubError = ref('')
const pubFail = ref<ReleaseFailure | null>(null)
const published = ref<string | null>(null)

// 回滚
const rbVer = ref<string | null>(null)
const rbRebuild = ref(true)
const rbBusy = ref(false)
const rbError = ref('')

// 版本对比
const cmpFrom = ref('')
const cmpTo = ref('')
const cmp = ref<KbDiff | null>(null)
const cmpLoading = ref(false)
const cmpError = ref('')

const exporting = ref(false)

const changes = computed(() => draft.value?.changes ?? null)
const counts = computed(() => diffCounts(changes.value))
const rows = computed(() => changeRows(changes.value))
const bumps = computed(() => bumpCounts(changes.value))
const bump = computed(() => changes.value?.suggested_bump ?? 'minor')
const firstRelease = computed(() => !!rel.value && rel.value.releases.length === 0)
const suggested = computed(() => suggestVersion(draft.value?.base ?? null, rel.value?.kb_version ?? '0.0.0', bump.value))
const hasChanges = computed(() => firstRelease.value || counts.value.total > 0)
const stale = computed(() => regressionStale(reg.value, draft.value?.commits ?? []))
const regOk = computed(() => !!reg.value && !reg.value.failed && !stale.value)
const versionInvalid = computed(() => version.value.trim() !== '' && !SEMVER.test(version.value.trim()))
const log = computed(() => (rel.value ? changelog(rel.value.releases, rel.value.history) : []))
const failedSamples = computed(() => (pubFail.value?.type === 'regression' ? pubFail.value.regression.results.filter((r) => !samplePassed(r)) : []))

function showToast(msg: string): void {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 2800)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    // 两个接口都要读知识库的 Git 仓库，依次请求，避免并发读写同一个仓库
    const gp = get<Regression | null>('/regression/last')
    const r = await get<ReleasesData>('/kb/releases')
    const d = await get<DraftData>('/kb/draft')
    const g = await gp
    rel.value = r
    draft.value = d
    reg.value = g
    const vs = r.releases.map((x) => x.version)
    if (!vs.includes(cmpFrom.value)) cmpFrom.value = vs[1] ?? vs[0] ?? ''
    if (cmpTo.value && !vs.includes(cmpTo.value)) cmpTo.value = ''
    if (!cmpTo.value && vs.length > 1 && cmpFrom.value === vs[1]) cmpTo.value = vs[0]
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function loadDiff(): Promise<void> {
  if (!cmpFrom.value) { cmp.value = null; return }
  cmpLoading.value = true
  cmpError.value = ''
  try {
    const q = new URLSearchParams({ from: cmpFrom.value })
    if (cmpTo.value) q.set('to', cmpTo.value)
    cmp.value = await get<KbDiff>(`/kb/diff?${q}`)
  } catch (e) {
    cmpError.value = errorText(e)
    cmp.value = null
  } finally {
    cmpLoading.value = false
  }
}

async function publish(): Promise<void> {
  if (publishing.value || versionInvalid.value) return
  publishing.value = true
  pubError.value = ''
  pubFail.value = null
  published.value = null
  try {
    const res = await post<{ version: string; regression: Regression }>('/kb/releases', {
      version: version.value.trim() || null,
      message: message.value.trim(),
    })
    published.value = res.version
    if (res.regression && 'results' in res.regression) reg.value = res.regression
    version.value = ''
    message.value = ''
    showToast(t('releases.publishedToast', { v: res.version }))
    await load()
    void status.refresh()
  } catch (e) {
    pubError.value = errorText(e)
    if (e instanceof ApiError && e.status === 409) pubFail.value = releaseFailure(e.data)
  } finally {
    publishing.value = false
  }
}

async function rollback(): Promise<void> {
  if (!rbVer.value) return
  rbBusy.value = true
  rbError.value = ''
  const v = rbVer.value
  try {
    await post('/kb/rollback', { ref: v })
    let rebuilt = false
    if (rbRebuild.value) {
      try { await post('/devices/rebuild'); rebuilt = true } catch { /* 重新计算失败不影响回滚结果 */ }
    }
    rbVer.value = null
    showToast(rebuilt ? t('releases.rolledBackRebuild', { v }) : t('releases.rolledBack', { v }))
    await load()
    void status.refresh()
  } catch (e) {
    rbError.value = errorText(e)
  } finally {
    rbBusy.value = false
  }
}

async function exportPkg(): Promise<void> {
  exporting.value = true
  try {
    await download('/kb/export', `lmesh-kb-${rel.value?.kb_version ?? 'draft'}.zip`)
  } catch (e) {
    showToast(errorText(e))
  } finally {
    exporting.value = false
  }
}

function onRegUpdated(r: Regression): void {
  reg.value = r
  void status.refresh()
}

function setTab(x: Tab): void {
  tab.value = x
  void router.replace({ query: { ...route.query, tab: x === 'draft' ? undefined : x } })
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && rbVer.value && !rbBusy.value) rbVer.value = null
}

watch([tab, cmpFrom, cmpTo], () => { if (tab.value === 'diff') void loadDiff() })
onMounted(async () => {
  window.addEventListener('keydown', onKey)
  await load()
  if (tab.value === 'diff') void loadDiff()
})
onBeforeUnmount(() => { window.removeEventListener('keydown', onKey); clearTimeout(toastTimer) })
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.releases') }}</h1>
          <p class="ph-sub">{{ $t('releases.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-sm" type="button" :disabled="loading" data-testid="releases-refresh" @click="load"><Icon name="refresh" small />{{ $t('c.refresh') }}</button>
          <button class="btn btn-sm" type="button" :disabled="exporting || !rel" data-testid="releases-export" @click="exportPkg"><Icon name="download" small />{{ $t('releases.export') }}</button>
        </div>
      </div>

      <div v-if="error && !rel" class="panel"><div class="empty" data-testid="releases-error"><p>{{ error }}</p><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div></div>
      <div v-else-if="!rel || !draft" class="panel"><div class="empty"><p>{{ $t('c.loading') }}</p></div></div>

      <template v-else>
        <div class="tabs" role="tablist">
          <button role="tab" type="button" :aria-selected="tab === 'draft'" data-testid="tab-draft" @click="setTab('draft')">
            <span>{{ $t('releases.tabDraft') }}</span><span class="count">{{ counts.total }}</span>
          </button>
          <button role="tab" type="button" :aria-selected="tab === 'diff'" data-testid="tab-diff" @click="setTab('diff')"><span>{{ $t('releases.tabDiff') }}</span></button>
          <button role="tab" type="button" :aria-selected="tab === 'log'" data-testid="tab-log" @click="setTab('log')"><span>{{ $t('releases.tabLog') }}</span></button>
        </div>

        <!-- ============ 草稿与发布 ============ -->
        <section v-if="tab === 'draft'">
          <div class="panel flow mt8" style="margin-bottom: 14px" data-testid="release-steps">
            <div class="steps">
              <div :class="['st', hasChanges ? 'done' : 'cur']">
                <span class="no"><Icon v-if="hasChanges" name="check" small /><template v-else>1</template></span>
                <span>{{ firstRelease ? $t('releases.stepFirst') : $t('releases.stepDraft', { n: counts.total }) }}</span>
              </div>
              <div :class="['st', regOk ? 'done' : hasChanges ? 'cur' : '']">
                <span class="no"><Icon v-if="regOk" name="check" small /><template v-else>2</template></span><span>{{ $t('releases.stepReg') }}</span>
              </div>
              <div :class="['st', regOk && hasChanges ? 'cur' : '']"><span class="no">3</span><span>{{ $t('releases.stepPub') }}</span></div>
            </div>
            <span class="faint small">{{ draft.base ? $t('releases.basedOn', { v: draft.base }) : $t('releases.noRelease') }}</span>
          </div>

          <div class="grid g-side collapse">
            <div class="stack">
              <RegressionPanel :regression="reg" :stale="stale" :loading="loading" @updated="onRegUpdated" @running="regRunning = $event" />

              <div class="panel" data-testid="draft-changes">
                <div class="panel-h">
                  <h2>{{ $t('releases.draftTitle') }}</h2>
                  <span class="meta">{{ draft.base ? $t('releases.draftMeta', { v: draft.base }) : $t('releases.draftMetaFirst') }}</span>
                  <button v-if="draft.base && counts.total && auth.isAdmin" class="btn btn-sm btn-ghost" type="button" data-testid="draft-discard" @click="rbVer = draft.base; rbError = ''">
                    <Icon name="trash" small />{{ $t('releases.discardAll') }}
                  </button>
                </div>
                <div v-if="firstRelease" class="panel-b"><p class="small muted">{{ $t('releases.firstHint') }}</p></div>
                <div v-else-if="!rows.length" class="empty"><p>{{ $t('releases.noChanges') }}</p></div>
                <div v-else class="tbl-wrap" style="max-height: 420px">
                  <table class="tbl" data-testid="draft-table">
                    <thead><tr><th class="chg-type">{{ $t('releases.type') }}</th><th>{{ $t('releases.item') }}</th><th>Profile</th><th>{{ $t('releases.changeCol') }}</th><th>{{ $t('releases.bumpCol') }}</th></tr></thead>
                    <tbody>
                      <tr v-for="(r, i) in rows" :key="i">
                        <td><span :class="['tag', r.bump === 'major' ? 't-red' : r.bump === 'minor' ? 't-teal' : r.kind === 'defaultChanged' ? 't-amber' : 't-blue']">{{ $t(`releases.k_${r.kind}`) }}</span></td>
                        <td class="mono">{{ r.id }}</td>
                        <td class="mono small">{{ r.profile ?? '' }}<span v-if="!r.profile" class="faint">—</span></td>
                        <td class="small"><template v-if="r.kind === 'defaultChanged'"><span class="mono old">{{ fmtValue(r.old) }}</span> → <span class="mono">{{ fmtValue(r.new) }}</span></template></td>
                        <td><span :class="['bump', r.bump]">{{ r.bump }}</span></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="draft.commits.length" class="panel-b commits">
                  <div class="section-t">{{ $t('releases.commits', { n: draft.commits.length }) }}</div>
                  <ul class="clist">
                    <li v-for="c in draft.commits" :key="c.commit"><span class="mono faint">{{ c.commit.slice(0, 8) }}</span><span class="faint small">{{ fmtTime(c.time) }}</span><span>{{ c.message }}</span></li>
                  </ul>
                </div>
              </div>
            </div>

            <!-- 右栏 -->
            <div class="stack">
              <div class="panel" data-testid="publish-panel">
                <div class="panel-h"><h2>{{ $t('releases.publish') }}</h2></div>
                <div class="panel-b">
                  <div class="row" style="align-items: baseline; gap: 10px">
                    <span class="ver-from">{{ draft.base ?? rel.kb_version }}</span><span class="faint">{{ $t('releases.to') }}</span>
                    <span class="ver-big">{{ version.trim() || suggested }}</span>
                    <span :class="['tag', bump === 'major' ? 't-red' : bump === 'minor' ? 't-teal' : '']">{{ $t(`releases.bump_${bump}`) }}</span>
                  </div>
                  <div class="rule">
                    <span :class="{ on: bump === 'major' }"><b>major</b></span><span :class="{ on: bump === 'major' }">{{ $t('releases.ruleMajor', { n: bumps.major }) }}</span>
                    <span :class="{ on: bump === 'minor' }"><b>minor</b></span><span :class="{ on: bump === 'minor' }">{{ $t('releases.ruleMinor', { n: bumps.minor }) }}</span>
                    <span :class="{ on: bump === 'patch' }"><b>patch</b></span><span :class="{ on: bump === 'patch' }">{{ $t('releases.rulePatch', { n: bumps.patch }) }}</span>
                  </div>
                  <div class="field mt16">
                    <label>{{ $t('releases.version') }}</label>
                    <input v-model="version" class="input mono" :placeholder="$t('releases.versionPh', { v: suggested })" data-testid="publish-version" />
                    <span v-if="versionInvalid" class="small" style="color: var(--red-ink)">{{ $t('releases.versionBad') }}</span>
                  </div>
                  <div class="field mt12">
                    <label>{{ $t('releases.notes') }}</label>
                    <textarea v-model="message" class="textarea" rows="3" :placeholder="$t('releases.notesPh')" data-testid="publish-message" />
                  </div>
                  <div class="mt12">
                    <button class="btn btn-primary" style="width: 100%" type="button" :disabled="publishing || regRunning || !hasChanges || versionInvalid || !auth.isAdmin" data-testid="publish-btn" @click="publish">
                      <Icon name="upload" small />{{ publishing ? $t('releases.publishing') : $t('releases.publishBtn', { v: version.trim() || suggested }) }}
                    </button>
                    <p v-if="!auth.isAdmin" class="small faint mt8" data-testid="publish-admin-only">{{ $t('releases.adminOnly') }}</p>
                    <p v-else-if="publishing" class="small faint mt8">{{ $t('releases.publishingHint') }}</p>
                    <p v-else-if="!hasChanges" class="small faint mt8">{{ $t('releases.noChanges') }}</p>
                    <p v-else-if="regRunning" class="small faint mt8">{{ $t('releases.regBusy') }}</p>
                    <p v-else-if="reg?.failed" class="small faint mt8">{{ $t('releases.lastFailedHint') }}</p>
                    <p v-else class="small faint mt8">{{ $t('releases.publishHint') }}</p>
                  </div>

                  <div v-if="published" class="notice ok mt12" data-testid="publish-ok">
                    <Icon name="ok" /><div class="grow small"><b>{{ $t('releases.publishedTitle', { v: published }) }}</b>
                      <div>{{ $t('releases.publishedHint') }} <router-link :to="{ name: 'devices' }">{{ $t('releases.goDevices') }}</router-link></div></div>
                  </div>
                  <div v-if="pubError" class="notice err mt12" data-testid="publish-error">
                    <Icon name="err" />
                    <div class="grow small">
                      <b>{{ pubError }}</b>
                      <template v-if="pubFail?.type === 'invalid'">
                        <ul class="issues">
                          <li v-for="(x, i) in pubFail.issues.slice(0, 30)" :key="i"><span class="mono">{{ x.code }}</span> {{ x.message }}<span v-if="x.file" class="mono faint"> · {{ x.file }}</span></li>
                        </ul>
                        <p v-if="pubFail.issues.length > 30" class="faint">{{ $t('releases.moreIssues', { n: pubFail.issues.length - 30 }) }}</p>
                      </template>
                      <template v-else-if="pubFail?.type === 'regression'">
                        <div>{{ $t('releases.regFailed', { n: pubFail.regression.failed, total: pubFail.regression.samples }) }}</div>
                        <ul class="issues">
                          <li v-for="r in failedSamples" :key="r.file"><span class="mono">{{ r.file }}</span>
                            — {{ r.error || (r.ok ? $t('releases.unknownN', { n: r.unknown ?? 0 }) : $t('releases.differs', { n: r.diffs?.length ?? 0 })) }}</li>
                        </ul>
                        <button class="btn btn-xs mt8" type="button" @click="reg = pubFail.regression">{{ $t('releases.showInTable') }}</button>
                      </template>
                    </div>
                  </div>
                </div>
              </div>

              <div class="panel" data-testid="release-list">
                <div class="panel-h"><h2>{{ $t('releases.published') }}</h2><span class="meta">{{ rel.releases.length }}</span></div>
                <div v-if="!rel.releases.length" class="empty"><p>{{ $t('releases.noRelease') }}</p></div>
                <div v-else class="vlist">
                  <div v-for="(v, i) in rel.releases" :key="v.tag" :class="['vi', { cur: i === 0 }]">
                    <div><div class="v">{{ v.version }}</div><div class="d">{{ fmtTime(v.time).slice(0, 10) }}</div></div>
                    <div class="s" :title="v.message">{{ v.message || '—' }}</div>
                    <span v-if="i === 0" class="tag t-teal">{{ $t('releases.latest') }}</span>
                    <button v-else-if="auth.isAdmin" class="btn btn-xs" type="button" :data-testid="`rollback-${v.version}`" @click="rbVer = v.version; rbError = ''">
                      <Icon name="rollback" small />{{ $t('releases.rollback') }}
                    </button>
                  </div>
                </div>
              </div>

              <div class="panel" data-testid="package-panel">
                <div class="panel-h"><h2>{{ $t('releases.package') }}</h2></div>
                <div class="panel-b">
                  <p class="small muted">{{ $t('releases.packageHint') }}</p>
                  <div class="row mt12">
                    <button class="btn btn-sm" type="button" :disabled="exporting" @click="exportPkg"><Icon name="download" small />{{ $t('releases.exportVer', { v: rel.kb_version }) }}</button>
                    <router-link class="btn btn-sm btn-ghost" :to="{ name: 'ingest' }"><Icon name="upload" small />{{ $t('releases.importGo') }}</router-link>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ============ 版本对比 ============ -->
        <section v-else-if="tab === 'diff'">
          <div class="panel">
            <div class="panel-h">
              <div class="vsel">
                <select v-model="cmpFrom" class="select" data-testid="diff-from">
                  <option v-for="v in rel.releases" :key="v.tag" :value="v.version">{{ v.version }}</option>
                </select>
                <span class="faint">{{ $t('releases.vs') }}</span>
                <select v-model="cmpTo" class="select" data-testid="diff-to">
                  <option value="">{{ $t('releases.workspace') }}</option>
                  <option v-for="v in rel.releases" :key="v.tag" :value="v.version">{{ v.version }}</option>
                </select>
              </div>
              <span v-if="cmpLoading" class="meta">{{ $t('c.loading') }}</span>
            </div>
            <div class="panel-b">
              <div v-if="!rel.releases.length" class="empty"><p>{{ $t('releases.noRelease') }}</p></div>
              <div v-else-if="cmpError" class="notice err"><Icon name="err" /><div class="grow small">{{ cmpError }}</div><button class="btn btn-xs" type="button" @click="loadDiff">{{ $t('c.retry') }}</button></div>
              <DiffTables v-else-if="cmp" :diff="cmp" :class="{ dim: cmpLoading }" />
            </div>
          </div>
        </section>

        <!-- ============ 变更日志 ============ -->
        <section v-else>
          <div class="panel" data-testid="changelog">
            <div v-if="!log.length" class="empty"><p>{{ $t('c.empty') }}</p></div>
            <div v-for="e in log" :key="e.version ?? 'draft'" class="cl-rel">
              <div>
                <h3>{{ e.version ?? $t('releases.unreleased') }}</h3>
                <div v-if="e.release" class="small faint">{{ fmtTime(e.release.time) }}</div>
                <div v-if="e.release" class="small faint mono">{{ e.release.tag }}</div>
              </div>
              <div>
                <p v-if="e.release?.message" style="margin-bottom: 6px">{{ e.release.message }}</p>
                <ul v-if="e.commits.length">
                  <li v-for="c in e.commits" :key="c.commit"><span class="mono faint small">{{ c.commit.slice(0, 8) }}</span> {{ c.message }} <span class="faint small">{{ fmtTime(c.time) }}</span></li>
                </ul>
                <p v-else class="small faint">{{ $t('releases.olderHistory') }}</p>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>

    <!-- 回滚确认 -->
    <div v-if="rbVer" class="modal-back" data-testid="rollback-dialog" @click.self="!rbBusy && (rbVer = null)">
      <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true">
        <div class="modal-h"><h2>{{ $t('releases.rollbackTo', { v: rbVer }) }}</h2>
          <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('c.close')" :disabled="rbBusy" @click="rbVer = null"><Icon name="x" small /></button></div>
        <div class="modal-b">
          <div class="notice warn"><Icon name="warn" /><div class="grow small">{{ $t('releases.rollbackWarn', { v: rbVer }) }}</div></div>
          <div v-if="counts.total" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ $t('releases.rollbackDraft', { n: counts.total }) }}</div></div>
          <label class="check mt12"><input v-model="rbRebuild" type="checkbox" /><span>{{ $t('releases.rollbackRebuild') }}</span></label>
          <div v-if="rbError" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ rbError }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" :disabled="rbBusy" @click="rbVer = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger-solid" type="button" :disabled="rbBusy" data-testid="rollback-confirm" @click="rollback">{{ $t('releases.rollbackTo', { v: rbVer }) }}</button>
        </div>
      </div>
    </div>
    <div v-if="toast" class="toast" role="status" data-testid="releases-toast"><Icon name="check" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
.flow { padding: 12px 16px; display: flex; align-items: center; gap: 18px; }
.flow .steps { flex: 1; }
.ver-big { font: 600 22px/1.2 var(--font-mono); letter-spacing: -.01em; }
.ver-from { color: var(--ink-3); font: 13px var(--font-mono); }
.rule { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 10px; font-size: 12px; color: var(--ink-2); margin-top: 10px; }
.rule b { font-family: var(--font-mono); font-weight: 600; color: var(--ink); }
.rule .on b { color: var(--teal-ink); }
.rule .on { color: var(--ink); }
.vlist .vi { display: grid; grid-template-columns: 70px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 9px 14px; border-bottom: 1px solid var(--line); }
.vlist .vi:last-child { border-bottom: 0; }
.vlist .vi .v { font: 600 13px var(--font-mono); }
.vlist .vi .d { font-size: 12px; color: var(--ink-3); }
.vlist .vi .s { font-size: 12px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vlist .vi.cur { background: var(--teal-soft); }
.chg-type { width: 110px; }
.bump { font: 600 11px var(--font-mono); }
.bump.major { color: var(--red-ink); }
.bump.minor { color: var(--teal-ink); }
.bump.patch { color: var(--ink-3); }
.old { text-decoration: line-through; color: var(--ink-3); }
.commits { border-top: 1px solid var(--line); }
.clist { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
.clist li { display: flex; gap: 10px; align-items: baseline; min-width: 0; }
.issues { margin: 6px 0 0; padding-left: 18px; max-height: 220px; overflow: auto; }
.cl-rel { padding: 14px 16px; border-bottom: 1px solid var(--line); display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 16px; }
.cl-rel:last-child { border-bottom: 0; }
.cl-rel h3 { font-family: var(--font-mono); font-size: 14px; }
.cl-rel ul { margin: 0; padding-left: 18px; color: var(--ink); }
.cl-rel li { margin: 2px 0; }
.vsel { display: flex; gap: 10px; align-items: center; }
.vsel .select { width: 150px; font-family: var(--font-mono); font-size: 12px; }
.dim { opacity: .6; }
.tbl td.mono, .tbl td.small.mono { white-space: nowrap; }
@media (max-width: 1300px) { .g-side { grid-template-columns: minmax(0, 1fr) 320px; } }
@media (max-width: 1100px) { .g-side.collapse { grid-template-columns: minmax(0, 1fr); } .flow { flex-wrap: wrap; } }
</style>
