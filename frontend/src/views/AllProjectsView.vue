<script setup lang="ts">
/**
 * 所有项目（管理员，REQ-035，预览 DevelopDocs/ui-preview/M6/all-projects.html）：
 * 按属主分组（可折叠）、属主已停用标记、筛选（属主已停用 / 90 天无活动）、进入他人项目先确认（记入审计）、
 * 转交（复用我的项目页的转交对话框）、导出清单（CSV），下方是最近的管理员访问记录（GET /admin/audit）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import TransferDialog from './projects/TransferDialog.vue'
import { errorText, get } from '@/api'
import { useAuth } from '@/stores/auth'
import type { ProjectRow } from '@/stores/project'
import { fmtTime } from './devices/logic'
import { activity, avatars } from './projects/logic'
import { auditAction, auditDetail, groupByOwner, isIdle, projectsCsv, type AllFilter, type AuditEvent } from './all-projects/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`all-projects.${k}`, p ?? {})
const router = useRouter()
const auth = useAuth()

const rows = ref<ProjectRow[]>([])
const stats = ref({ owners: 0, with_members: 0, owner_disabled: 0 })
const loading = ref(true)
const loadErr = ref('')
const q = ref('')
const f = ref<AllFilter>('')
const closed = reactive<Record<string, boolean>>({})
const audit = ref<AuditEvent[]>([])
const auditErr = ref('')
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined
function showToast(m: string): void {
  toast.value = m
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3500)
}
onBeforeUnmount(() => clearTimeout(toastTimer))

async function load(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    const d = await get<{ projects: ProjectRow[]; owners: number; with_members: number; owner_disabled: number }>('/admin/projects')
    rows.value = d.projects
    stats.value = { owners: d.owners, with_members: d.with_members, owner_disabled: d.owner_disabled }
  } catch (e) { loadErr.value = errorText(e) } finally { loading.value = false }
}
async function loadAudit(): Promise<void> {
  auditErr.value = ''
  try { audit.value = (await get<{ events: AuditEvent[] }>('/admin/audit?limit=50')).events } catch (e) { auditErr.value = errorText(e) }
}
onMounted(() => { void load(); void loadAudit() })

const me = computed(() => auth.me?.username ?? null)
const groups = computed(() => groupByOwner(rows.value, me.value, q.value, f.value))
const idle = computed(() => rows.value.filter((p) => isIdle(p)).length)
// 审计事件按项目编号找属主（标识按属主唯一，不同人的项目可以同名）
const ownerOf = (id: number | null) => (id == null ? '' : rows.value.find((p) => p.id === id)?.owner ?? '')
function toggleAll(): void {
  const any = groups.value.some((g) => closed[g.owner])
  for (const g of groups.value) closed[g.owner] = !any
}

// 进入：自己参与的项目直接打开；他人的项目先确认（访问记入审计日志）
const confirmFor = ref<ProjectRow | null>(null)
function enter(p: ProjectRow, confirmed = false): void {
  if (p.role === 'admin' && !confirmed) { confirmFor.value = p; return }
  confirmFor.value = null
  void router.push({ name: 'devices', params: { project: p.ref } })
}

const transferFor = ref<ProjectRow | null>(null)
function transferred(r: { owner: string }): void {
  showToast(T('transferred', { p: transferFor.value?.name ?? '', u: r.owner }))
  transferFor.value = null
  void load()
  void loadAudit()
}

function exportCsv(): void {
  const head = ['project', 'slug', 'owner', 'owner_disabled', 'members', 'devices', 'private', 'refs', 'scripts', 'last_activity']
  const blob = new Blob([projectsCsv(rows.value, head)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'lmesh-projects.csv'
  a.click()
  URL.revokeObjectURL(url)
}

function actText(p: ProjectRow): string {
  const a = activity(p.last_activity)
  if (!a) return T('noActivity')
  const what = a.key ? t(`proj.act.${a.key}`) : a.raw
  return `${a.actor ? a.actor + ' · ' : ''}${what}`
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.sys') }}</span><span class="sep">/</span><span>{{ $t('nav.all-projects') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.all-projects') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn" type="button" :disabled="!rows.length" data-testid="allp-export" @click="exportCsv"><Icon name="download" small /><span>{{ T('export') }}</span></button>
        </div>
      </div>

      <div class="m6-strip" data-testid="allp-stats">
        <div><div class="k">{{ T('stProjects') }}</div><div class="v">{{ rows.length }}</div></div>
        <div><div class="k">{{ T('stOwners') }}</div><div class="v">{{ stats.owners }}</div></div>
        <div><div class="k">{{ T('stShared') }}</div><div class="v">{{ stats.with_members }}</div></div>
        <div><div class="k">{{ T('fDisabled') }}</div><div class="v" :style="stats.owner_disabled ? 'color: var(--amber-ink)' : ''">{{ stats.owner_disabled }}<small v-if="stats.owner_disabled">{{ T('suggestTransfer') }}</small></div></div>
      </div>

      <section class="panel">
        <div class="panel-h toolbar" style="padding: 8px 12px">
          <label class="input-wrap" style="width: 240px"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="T('filter')" data-testid="allp-q"></label>
          <div class="seg" role="group" data-testid="allp-filter">
            <button type="button" :aria-pressed="f === ''" @click="f = ''">{{ T('fAll') }}</button>
            <button type="button" :aria-pressed="f === 'disabled'" data-testid="allp-f-disabled" @click="f = 'disabled'">{{ T('fDisabled') }}</button>
            <button type="button" :aria-pressed="f === 'idle'" data-testid="allp-f-idle" @click="f = 'idle'">{{ T('fIdle') }}<template v-if="idle"> · {{ idle }}</template></button>
          </div>
          <span class="grow" />
          <button class="btn btn-sm btn-ghost" type="button" :disabled="!groups.length" @click="toggleAll">{{ T('fold') }}</button>
        </div>
        <div v-if="loadErr" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
        <div v-else-if="loading && !rows.length" class="empty">{{ $t('c.loading') }}</div>
        <div v-else-if="!groups.length" class="empty" data-testid="allp-empty"><h3>{{ T('noMatch') }}</h3></div>
        <div v-else data-testid="allp-groups">
          <div v-for="g in groups" :key="g.owner" :class="['owner-g', { 'is-closed': closed[g.owner] }]" :data-testid="`allp-owner-${g.owner || 'none'}`">
            <div class="og-h" role="button" tabindex="0" :aria-expanded="!closed[g.owner]" @click="closed[g.owner] = !closed[g.owner]" @keydown.enter="closed[g.owner] = !closed[g.owner]">
              <Icon name="chevD" small class="tw" />
              <span :class="['m6av', { admin: g.owner === me }]">{{ (g.owner || '?').charAt(0).toUpperCase() }}</span>
              <b>{{ g.owner || T('noOwner') }}</b>
              <span v-if="g.owner === me" class="tag t-teal">{{ T('me') }}</span>
              <span v-if="g.disabled" class="tag t-amber">{{ T('ownerDisabled') }}</span>
              <span class="meta">{{ T('nProjects', { n: g.projects.length }) }}</span>
            </div>
            <div class="og-b tbl-wrap">
              <table class="tbl">
                <thead><tr><th>{{ T('colProject') }}</th><th class="num">{{ T('colDevices') }}</th><th class="num">{{ T('colScripts') }}</th><th>{{ T('colMembers') }}</th><th>{{ T('colActivity') }}</th><th /></tr></thead>
                <tbody>
                  <tr v-for="p in g.projects" :key="p.ref" :data-testid="`allp-row-${p.ref}`">
                    <td><b>{{ p.name }}</b><div class="small faint mono">{{ p.ref }}</div></td>
                    <td class="num">{{ p.counts.devices }}<div class="small faint">{{ T('private', { n: p.counts.private }) }}</div></td>
                    <td class="num">{{ p.counts.scripts }}</td>
                    <td>
                      <span v-if="p.members > 1" class="avs" :title="(p.member_names ?? []).join('、')">
                        <span v-for="m in avatars(p.owner, p.member_names)" :key="m" class="m6av">{{ m.charAt(0).toUpperCase() }}</span>
                      </span>
                      <span v-else class="small faint">—</span>
                    </td>
                    <td class="small muted">
                      {{ actText(p) }}
                      <div v-if="p.last_activity" class="faint">{{ fmtTime(p.last_activity.at, true) }}</div>
                    </td>
                    <td class="right nowrap">
                      <button v-if="p.role === 'admin'" class="btn btn-sm" type="button" :data-testid="`allp-enter-${p.ref}`" @click="enter(p)"><Icon name="enter" small />{{ T('enter') }}</button>
                      <button v-else class="btn btn-sm" type="button" :data-testid="`allp-open-${p.ref}`" @click="enter(p)">{{ T('open') }}</button>
                      <button class="btn btn-sm btn-ghost" type="button" :data-testid="`allp-transfer-${p.ref}`" @click="transferFor = p"><Icon name="transfer" small />{{ T('transfer') }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section class="panel mt16" data-testid="allp-audit">
        <div class="panel-h"><h2>{{ T('auditTitle') }}</h2><span class="meta">logs/audit.log · lmesh.audit</span></div>
        <div v-if="auditErr" class="notice err" style="margin: 12px"><Icon name="err" /><div class="grow">{{ auditErr }}</div><button class="btn btn-sm" type="button" @click="loadAudit">{{ $t('c.retry') }}</button></div>
        <div v-else-if="!audit.length" class="empty small">{{ T('auditEmpty') }}</div>
        <div v-else class="tbl-wrap">
          <table class="tbl audit">
            <thead><tr><th>{{ T('colTime') }}</th><th>{{ T('colAdmin') }}</th><th>{{ T('colProject') }}</th><th>{{ T('colOwner') }}</th><th>{{ T('colAction') }}</th></tr></thead>
            <tbody>
              <tr v-for="a in audit" :key="a.id">
                <td class="nowrap">{{ fmtTime(a.at, true) }}</td>
                <td>{{ a.actor }}</td>
                <td class="mono">{{ a.project ?? '—' }}</td>
                <td>{{ ownerOf(a.project_id) || '—' }}</td>
                <td>
                  {{ auditAction(a.action) ? T(`act.${a.action}`) : a.action }}
                  <span v-if="auditDetail(a.detail)" class="small faint mono"> · {{ auditDetail(a.detail) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div v-if="confirmFor" class="modal-back" data-testid="allp-enter-confirm" @click.self="confirmFor = null">
      <div class="modal" style="width: min(480px, 100%)" role="dialog" aria-modal="true" aria-labelledby="apT">
        <div class="modal-h">
          <h2 id="apT">{{ $t('proj.enterTitle') }}</h2>
          <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="confirmFor = null"><Icon name="x" /></button>
        </div>
        <div class="modal-b stack">
          <div class="fo-who">
            <span class="m6av">{{ (confirmFor.owner ?? '?').charAt(0).toUpperCase() }}</span>
            <div><b>{{ confirmFor.name }}</b><small>{{ $t('proj.ownerIs', { u: confirmFor.owner ?? '—' }) }}{{ confirmFor.owner_disabled ? $t('proj.ownerDisabled') : '' }}</small></div>
          </div>
          <div class="notice warn"><Icon name="shield" /><div>{{ $t('proj.enterNote') }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="confirmFor = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" data-testid="allp-enter-ok" @click="enter(confirmFor, true)"><Icon name="enter" small />{{ $t('proj.enter') }}</button>
        </div>
      </div>
    </div>

    <TransferDialog v-if="transferFor" :project="transferFor" @close="transferFor = null" @transferred="transferred" />

    <div v-if="toast" class="toast" role="status" data-testid="allp-toast"><Icon name="ok" small />{{ toast }}</div>
  </main>
</template>

<style scoped>
/* 每个属主一张表：固定列宽，让各组的列对齐 */
.og-b .tbl { table-layout: fixed; }
.og-b .tbl th:nth-child(1) { width: 30%; }
.og-b .tbl th:nth-child(2) { width: 9%; }
.og-b .tbl th:nth-child(3) { width: 8%; }
.og-b .tbl th:nth-child(4) { width: 14%; }
.og-b .tbl th:nth-child(6) { width: 190px; }
.og-b .tbl td { overflow: hidden; text-overflow: ellipsis; }
</style>
