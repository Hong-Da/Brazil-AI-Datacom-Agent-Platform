<script setup lang="ts">
/**
 * 我的项目（REQ-035，预览 DevelopDocs/ui-preview/M6/projects.html）：我的项目 / 共享给我的（管理员另有其他人的），
 * 卡片或列表，计数、成员、最近活动；卡片菜单：打开、设置与成员、复制、转交、删除或退出。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { errorText } from '@/api'
import { useAuth } from '@/stores/auth'
import { useProject, type ProjectRow } from '@/stores/project'
import { rememberedChoice } from '@/stores/prefs'
import { useStatus } from '@/stores/status'
import { shortTime } from '@/views/account/account'
import { activity, ambiguousCandidates, avatars, matchProject, projectAbilities, sortProjects, type SortKey } from './projects/logic'
import NewProjectDialog from './projects/NewProjectDialog.vue'
import CopyProjectDialog from './projects/CopyProjectDialog.vue'
import TransferDialog from './projects/TransferDialog.vue'
import DeleteProjectDialog from './projects/DeleteProjectDialog.vue'
import LeaveDialog from './projects/LeaveDialog.vue'

type Tab = 'mine' | 'shared' | 'others'
type Dlg = { kind: 'new' } | { kind: 'copy' | 'transfer' | 'delete' | 'leave'; p: ProjectRow }

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const project = useProject()
const status = useStatus()

const loading = ref(true)
const loadError = ref('')
const tab = ref<Tab>('mine')
const q = ref('')
const sort = ref<SortKey>('act')
const view = rememberedChoice<'cards' | 'list'>('projects-view', 'cards')
const menu = ref<string | null>(null)
const dlg = ref<Dlg | null>(null)
const toast = ref('')

const lists = computed(() => project.lists)
const missing = computed(() => (typeof route.query.missing === 'string' ? route.query.missing : ''))
/** 网址里只写了标识、而能访问的同名项目有多个（标识按属主唯一）：列出候选让用户选 */
const ambiguous = computed(() => (typeof route.query.ambiguous === 'string' ? route.query.ambiguous : ''))
const candidates = computed(() => ambiguousCandidates(ambiguous.value, project.candidates, lists.value))
const tabs = computed<Tab[]>(() => (auth.isAdmin && lists.value?.others.length ? ['mine', 'shared', 'others'] : ['mine', 'shared']))
const rows = computed(() => sortProjects((lists.value?.[tab.value] ?? []).filter((p) => matchProject(p, q.value)), sort.value))
const total = computed(() => (lists.value ? lists.value.mine.length + lists.value.shared.length : 0))
const ro = computed(() => !!auth.me?.read_only)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const l = await project.loadLists()
    if (tab.value === 'mine' && !l.mine.length && l.shared.length) tab.value = 'shared'
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function flash(msg: string): void {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 3200)
}

function actText(p: ProjectRow): string {
  const a = activity(p.last_activity)
  if (!a) return t('proj.act.none')
  const what = a.key ? t(`proj.act.${a.key}`) : a.raw
  return `${a.actor ? t('proj.act.by', { u: a.actor, a: what }) : what} · ${shortTime(a.at)}`
}
const abil = (p: ProjectRow) => projectAbilities(p.role, ro.value)

function open(p: ProjectRow): void { void router.push({ name: 'devices', params: { project: p.ref } }) }
function settings(p: ProjectRow): void { void router.push({ name: 'project-settings', params: { project: p.ref } }) }
function act(kind: 'copy' | 'transfer' | 'delete' | 'leave', p: ProjectRow): void { menu.value = null; dlg.value = { kind, p } }

async function afterGone(slug: string, msg: string): Promise<void> {
  dlg.value = null
  if (project.ref === slug) { project.forget(); void status.refresh() }
  flash(msg)
  await load()
}
async function onCreated(p: ProjectRow): Promise<void> {
  dlg.value = null
  try { await project.enter(p.ref) } catch { /* 进不去时留在列表 */ }
  flash(t('projects.created', { p: p.name }))
  void router.push({ name: 'add-device', params: { project: p.ref } })
}
async function onCopied(p: ProjectRow & { copied?: { devices: number; scripts: number } }): Promise<void> {
  dlg.value = null
  flash(t('projects.copied', { p: p.name, d: p.copied?.devices ?? 0, s: p.copied?.scripts ?? 0 }))
  tab.value = 'mine'
  await load()
}
async function onTransferred(r: { owner: string; kept_as: string | null; rule_set_copied: unknown; full_ref?: string }, p: ProjectRow | null): Promise<void> {
  dlg.value = null
  if (!p) return
  if (project.ref === p.ref) {
    // 转交后规范引用变成“新属主/标识”
    project.forget()
    if (r.kept_as && r.full_ref) { try { await project.enter(r.full_ref) } catch { /* 进不去时下次用默认项目 */ } }
  }
  flash(t('projects.transferred', { p: p.name, u: r.owner }) + (r.rule_set_copied ? t('projects.ruleSetCopied') : ''))
  await load()
}

function onDoc(e: MouseEvent): void { if (menu.value && !(e.target as HTMLElement).closest?.('.kebab')) menu.value = null }
onMounted(() => {
  document.addEventListener('click', onDoc)
  void load()
  if (route.query.new === '1') dlg.value = { kind: 'new' }
})
onBeforeUnmount(() => document.removeEventListener('click', onDoc))
watch(() => route.query.new, (v) => { if (v === '1') dlg.value = { kind: 'new' } })
function closeNew(): void {
  dlg.value = null
  if (route.query.new) void router.replace({ query: { ...route.query, new: undefined } })
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.home') }}</span><span class="sep">/</span><span>{{ $t('nav.projects') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.projects') }}</h1>
          <p class="ph-sub">{{ $t('projects.sub') }}</p>
        </div>
        <div class="ph-actions">
          <router-link class="btn" :to="{ name: 'templates' }" data-testid="projects-my-templates"><Icon name="stencil" small />{{ $t('projects.myTemplates') }}</router-link>
          <router-link class="btn" :to="{ name: 'translate-rules' }" data-testid="projects-my-rulesets"><Icon name="rules" small />{{ $t('projects.myRuleSets') }}</router-link>
          <button v-if="!ro" class="btn btn-primary" type="button" data-testid="projects-new" @click="dlg = { kind: 'new' }"><Icon name="plus" small />{{ $t('projects.new') }}</button>
        </div>
      </div>

      <div v-if="missing" class="notice warn mb12" data-testid="projects-missing"><Icon name="warn" /><div>{{ $t('projects.missing', { p: missing }) }}</div></div>
      <div v-if="ambiguous" class="notice warn mb12" data-testid="projects-ambiguous">
        <Icon name="warn" />
        <div>
          {{ $t('projects.ambiguous', { p: ambiguous }) }}
          <span v-for="c in candidates" :key="c" class="amb-c"><router-link class="mono" :to="{ name: 'devices', params: { project: c } }" :data-testid="`projects-ambiguous-${c}`">{{ c }}</router-link></span>
        </div>
      </div>

      <div v-if="loadError" class="notice err" data-testid="projects-error"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <p v-else-if="loading && !lists" class="faint">{{ $t('c.loading') }}</p>

      <section v-else-if="lists && !total && !lists.others.length" class="panel" data-testid="projects-empty">
        <div class="empty">
          <svg class="art" viewBox="0 0 150 96" aria-hidden="true">
            <rect x="18" y="22" width="70" height="56" rx="6" fill="var(--blue-soft)" stroke="var(--blue-line)" />
            <path d="M18 30a6 6 0 0 1 6-6h18l6 6" fill="none" stroke="var(--blue-line)" />
            <rect x="28" y="40" width="22" height="9" rx="2" fill="var(--blue)" /><rect x="54" y="40" width="22" height="9" rx="2" fill="none" stroke="var(--teal)" stroke-dasharray="3 2" />
            <rect x="28" y="55" width="48" height="4" rx="2" fill="var(--line-strong)" /><rect x="28" y="63" width="34" height="4" rx="2" fill="var(--line-strong)" />
            <circle cx="112" cy="40" r="11" fill="var(--surface-3)" /><circle cx="124" cy="56" r="11" fill="var(--teal-soft)" stroke="var(--teal-line)" />
            <path d="M100 74c4-8 20-8 24 0" stroke="var(--line-strong)" fill="none" stroke-width="2" />
          </svg>
          <h3>{{ $t('projects.emptyTitle') }}</h3>
          <p>{{ $t('projects.emptyText') }}</p>
          <button v-if="!ro" class="btn btn-primary" type="button" @click="dlg = { kind: 'new' }"><Icon name="plus" small />{{ $t('projects.new') }}</button>
        </div>
      </section>

      <template v-else-if="lists">
        <div class="toolbar" style="margin-bottom: 12px">
          <div class="seg" role="group" data-testid="projects-tabs">
            <button v-for="tb in tabs" :key="tb" type="button" :aria-pressed="tab === tb" :data-testid="`projects-tab-${tb}`" @click="tab = tb">
              {{ $t(tb === 'mine' ? 'projects.tabMine' : tb === 'shared' ? 'projects.tabShared' : 'projects.tabOthers') }} <span class="faint">{{ lists[tb].length }}</span>
            </button>
          </div>
          <label class="input-wrap" style="width: 240px"><Icon name="search" small /><input v-model="q" class="input" type="search" :placeholder="$t('projects.filter')" data-testid="projects-filter"></label>
          <select v-model="sort" class="select" style="width: auto" data-testid="projects-sort">
            <option value="act">{{ $t('projects.sortAct') }}</option>
            <option value="name">{{ $t('projects.sortName') }}</option>
          </select>
          <span class="grow" />
          <div class="seg" role="group" data-testid="projects-view">
            <button type="button" :aria-pressed="view === 'cards'" @click="view = 'cards'"><Icon name="matrix" small />{{ $t('projects.cards') }}</button>
            <button type="button" :aria-pressed="view === 'list'" @click="view = 'list'"><Icon name="rows" small />{{ $t('projects.list') }}</button>
          </div>
        </div>

        <div v-if="!rows.length" class="panel"><div class="empty"><h3>{{ q ? $t('projects.noMatch') : tab === 'shared' ? $t('projects.emptyShared') : $t('projects.noMatch') }}</h3></div></div>

        <div v-else-if="view === 'cards'" class="pcards" data-testid="projects-cards">
          <article v-for="p in rows" :key="p.ref" :class="['pcard', { 'is-cur': p.ref === project.ref }]" :data-testid="`project-card-${p.ref}`">
            <div class="pc-h">
              <div class="ttl">
                <router-link :to="{ name: 'devices', params: { project: p.ref } }">{{ p.name }}</router-link>
                <span class="slug">{{ p.ref }}<template v-if="p.ref === project.ref"> · {{ $t('projects.current') }}</template><template v-if="p.default"> · {{ $t('projects.default') }}</template></span>
              </div>
              <ProjRole v-if="p.role !== 'owner'" :role="p.role" />
              <span class="kebab">
                <button class="btn btn-sm btn-icon btn-ghost" type="button" :aria-label="$t('projects.more')" :aria-expanded="menu === p.ref" :data-testid="`project-menu-${p.ref}`" @click.stop="menu = menu === p.ref ? null : p.ref"><Icon name="more" /></button>
                <div v-if="menu === p.ref" class="kebab-pop" role="menu">
                  <button type="button" role="menuitem" @click="open(p)"><Icon name="enter" small />{{ $t('projects.open') }}</button>
                  <button type="button" role="menuitem" data-testid="pm-settings" @click="settings(p)"><Icon name="gear" small />{{ $t(abil(p).manage ? 'projects.settings' : 'projects.viewSettings') }}</button>
                  <button v-if="!ro" type="button" role="menuitem" data-testid="pm-copy" @click="act('copy', p)"><Icon name="copy" small />{{ $t('projects.copy') }}</button>
                  <button v-if="abil(p).manage" type="button" role="menuitem" data-testid="pm-transfer" @click="act('transfer', p)"><Icon name="transfer" small />{{ $t('projects.transfer') }}</button>
                  <template v-if="abil(p).manage || abil(p).leave"><hr></template>
                  <button v-if="abil(p).manage" type="button" role="menuitem" class="danger" data-testid="pm-delete" @click="act('delete', p)"><Icon name="trash" small />{{ $t('projects.delete') }}</button>
                  <button v-else-if="abil(p).leave" type="button" role="menuitem" class="danger" data-testid="pm-leave" @click="act('leave', p)"><Icon name="logout" small />{{ $t('projects.leave') }}</button>
                </div>
              </span>
            </div>
            <div class="pc-d">{{ p.description || '—' }}</div>
            <div class="pc-n">
              <div><div class="v">{{ p.counts.devices }}</div><div class="k">{{ $t('projects.devices') }} · {{ $t('projects.privRef', { p: p.counts.private, r: p.counts.refs }) }}</div></div>
              <div>
                <div class="v">{{ p.counts.scripts }}<small v-if="p.counts.scripts_with_errors" class="errs"> {{ $t('projects.scriptErrors', { n: p.counts.scripts_with_errors }) }}</small></div>
                <div class="k">{{ $t('projects.scripts') }}</div>
              </div>
              <div>
                <div class="v"><span class="avs"><span v-for="u in avatars(p.owner, p.member_names)" :key="u" class="m6av" :title="u">{{ u.charAt(0).toUpperCase() }}</span></span></div>
                <div class="k">{{ p.members > 1 ? $t('projects.members', { n: p.members }) : $t('projects.onlyMe') }}</div>
              </div>
            </div>
            <div class="pc-f">
              <Icon name="clock" small />
              <span class="pc-act" :title="p.last_activity?.action">{{ actText(p) }}</span>
              <span v-if="p.role !== 'owner'" class="small faint nowrap">{{ $t('projects.owner', { u: p.owner ?? '—' }) }}</span>
            </div>
          </article>
        </div>

        <section v-else class="panel" data-testid="projects-table">
          <div class="tbl-wrap">
            <table class="tbl">
              <thead>
                <tr>
                  <th>{{ $t('projects.colProject') }}</th><th>{{ $t('projects.colRole') }}</th><th class="num">{{ $t('projects.devices') }}</th><th />
                  <th class="num">{{ $t('projects.scripts') }}</th><th>{{ $t('projects.colMembers') }}</th><th>{{ $t('projects.colActivity') }}</th><th />
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in rows" :key="p.ref" :class="{ 'is-cur-row': p.ref === project.ref }" :data-testid="`project-row-${p.ref}`">
                  <td><router-link class="pname" :to="{ name: 'devices', params: { project: p.ref } }">{{ p.name }}</router-link><div class="small faint mono">{{ p.ref }}</div></td>
                  <td><ProjRole :role="p.role" /></td>
                  <td class="num">{{ p.counts.devices }}</td>
                  <td class="small muted">{{ $t('projects.privRef', { p: p.counts.private, r: p.counts.refs }) }}</td>
                  <td class="num">{{ p.counts.scripts }}</td>
                  <td><span class="avs"><span v-for="u in avatars(p.owner, p.member_names)" :key="u" class="m6av" :title="u">{{ u.charAt(0).toUpperCase() }}</span></span></td>
                  <td class="small muted" style="max-width: 360px">{{ actText(p) }}</td>
                  <td class="right">
                    <span class="kebab">
                      <button class="btn btn-sm btn-icon btn-ghost" type="button" :aria-label="$t('projects.more')" @click.stop="menu = menu === p.ref ? null : p.ref"><Icon name="more" /></button>
                      <div v-if="menu === p.ref" class="kebab-pop" role="menu">
                        <button type="button" role="menuitem" @click="open(p)"><Icon name="enter" small />{{ $t('projects.open') }}</button>
                        <button type="button" role="menuitem" @click="settings(p)"><Icon name="gear" small />{{ $t(abil(p).manage ? 'projects.settings' : 'projects.viewSettings') }}</button>
                        <button v-if="!ro" type="button" role="menuitem" @click="act('copy', p)"><Icon name="copy" small />{{ $t('projects.copy') }}</button>
                        <button v-if="abil(p).manage" type="button" role="menuitem" @click="act('transfer', p)"><Icon name="transfer" small />{{ $t('projects.transfer') }}</button>
                        <template v-if="abil(p).manage || abil(p).leave"><hr></template>
                        <button v-if="abil(p).manage" type="button" role="menuitem" class="danger" @click="act('delete', p)"><Icon name="trash" small />{{ $t('projects.delete') }}</button>
                        <button v-else-if="abil(p).leave" type="button" role="menuitem" class="danger" @click="act('leave', p)"><Icon name="logout" small />{{ $t('projects.leave') }}</button>
                      </div>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>

    <NewProjectDialog v-if="dlg?.kind === 'new'" @close="closeNew" @created="onCreated" />
    <CopyProjectDialog v-else-if="dlg?.kind === 'copy'" :project="dlg.p" @close="dlg = null" @copied="onCopied" />
    <TransferDialog v-else-if="dlg?.kind === 'transfer'" :project="dlg.p" @close="dlg = null" @transferred="(r) => onTransferred(r, dlg?.kind === 'transfer' ? dlg.p : null)" />
    <DeleteProjectDialog v-else-if="dlg?.kind === 'delete'" :project="dlg.p" @close="dlg = null" @deleted="afterGone(dlg.p.ref, $t('projects.deleted', { p: dlg.p.name }))" />
    <LeaveDialog v-else-if="dlg?.kind === 'leave'" :project="dlg.p" @close="dlg = null" @left="afterGone(dlg.p.ref, $t('projects.left', { p: dlg.p.name }))" />
    <div v-if="toast" class="toast" role="status" data-testid="projects-toast"><Icon name="check" small /><span>{{ toast }}</span></div>
  </main>
</template>

<style scoped>
.mb12 { margin-bottom: 12px; }
.amb-c { margin-left: 8px; }
.errs { font: 600 11.5px var(--font-ui); color: var(--red-ink); }
.pname { font-weight: 600; color: var(--ink); }
.is-cur-row td:first-child { box-shadow: inset 3px 0 0 var(--blue); }
</style>
