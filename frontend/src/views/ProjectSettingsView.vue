<script setup lang="ts">
/**
 * 项目设置与成员（REQ-035 / REQ-036，预览 DevelopDocs/ui-preview/M6/project-settings.html）：
 * 常规、默认设置、检查规则调整（只影响本项目）、成员、转交与删除。
 * 权限以后端为准：属主与管理员全部；“管理”成员另可管理成员、加入申请、邀请链接与“可被搜索”（M9-8，不能转交、删除、
 * 改标识）；可编辑成员改设置与规则；只读成员只能查看（D-0198）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { del, errorText, get, put } from '@/api'
import { pickLang } from '@/i18n'
import { useAuth } from '@/stores/auth'
import { usePrefs } from '@/stores/prefs'
import { useProject, type Member } from '@/stores/project'
import { useStatus } from '@/stores/status'
import { useTerms } from '@/stores/terms'
import { shortTime } from '@/views/account/account'
import { draftOf, isDirty, isShared, overrideBody, overrideMark, SEVERITIES, settingsPatch, type RuleDraft, type RuleRow, type SettingsForm } from './project-settings/logic'
import { validSlug } from './projects/logic'
import CopyProjectDialog from './projects/CopyProjectDialog.vue'
import TransferDialog from './projects/TransferDialog.vue'
import DeleteProjectDialog from './projects/DeleteProjectDialog.vue'
import LeaveDialog from './projects/LeaveDialog.vue'
import JoinRequestsPanel from './project-settings/JoinRequestsPanel.vue'
import InvitesPanel from './project-settings/InvitesPanel.vue'

const { t, te } = useI18n()
const router = useRouter()
const auth = useAuth()
const prefs = usePrefs()
const project = useProject()
const status = useStatus()
const terms = useTerms()

const info = computed(() => project.info)
const canEdit = computed(() => project.canWrite)
const canManage = computed(() => project.canManage)
const canOwn = computed(() => project.canOwn)
const styleLabel = (s: string) => (te(`style.${s}`) ? t(`style.${s}`) : s)
const toast = ref('')
function flash(msg: string): void {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 3000)
}

/* ---------------- 常规与默认设置 ---------------- */
const empty = (): SettingsForm => ({ name: '', slug: '', description: '', style: '', rule_set: '', baseline: '' })
const orig = ref<SettingsForm>(empty())
const form = reactive<SettingsForm>(empty())
const saving = ref(false)
const saveError = ref('')
const ruleSets = ref<{ id: string; title: Record<string, string> | null }[]>([])
const baselines = ref<{ id: string; title: Record<string, string> | null }[]>([])
const patch = computed(() => settingsPatch(orig.value, form))
const slugErr = computed(() => form.slug.trim() !== orig.value.slug && !validSlug(form.slug.trim()))

function fillForm(): void {
  const p = info.value
  if (!p) return
  const f: SettingsForm = {
    name: p.name, slug: p.slug, description: p.description ?? '',
    style: p.settings.style ?? '', rule_set: p.settings.rule_set ?? '', baseline: p.settings.baseline ?? '',
  }
  orig.value = { ...f }
  Object.assign(form, f)
}

async function save(): Promise<void> {
  if (!Object.keys(patch.value).length) { flash(t('project-settings.noChange')); return }
  if (slugErr.value || !form.name.trim()) return
  saving.value = true
  saveError.value = ''
  const oldSlug = orig.value.slug
  try {
    const r = await put<{ slug: string; ref: string }>(`/projects/${encodeURIComponent(project.ref ?? '')}`, patch.value)
    flash(t('project-settings.saved'))
    if (r.slug !== oldSlug) {
      project.forget()
      await router.replace({ name: 'project-settings', params: { project: r.ref } })
    } else {
      await project.reload()
      fillForm()
    }
  } catch (e) {
    saveError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

/* ---------------- 规则调整 ---------------- */
const rules = ref<RuleRow[]>([])
const drafts = reactive<Record<string, RuleDraft>>({})
const rulesError = ref('')
const rulesLoading = ref(false)
const ruleFilter = ref<'all' | 'adj'>('all')
const ruleBusy = ref('')
const ruleErr = reactive<Record<string, string>>({})
const shownRules = computed(() => rules.value.filter((r) => ruleFilter.value === 'all' || r.override))
const adjusted = computed(() => rules.value.filter((r) => r.override).length)
const ruleTitle = (r: RuleRow) => (typeof r.title === 'string' ? r.title : pickLang(r.title, prefs.lang)) || r.id

async function loadRules(): Promise<void> {
  if (!info.value) return
  rulesLoading.value = true
  rulesError.value = ''
  try {
    rules.value = (await get<{ rules: RuleRow[] }>(`/projects/${encodeURIComponent(project.ref ?? '')}/rules`)).rules
    for (const r of rules.value) drafts[r.id] = draftOf(r)
  } catch (e) {
    rulesError.value = errorText(e)
  } finally {
    rulesLoading.value = false
  }
}

async function saveRule(r: RuleRow): Promise<void> {
  const d = drafts[r.id]
  ruleErr[r.id] = ''
  if (isShared(r, d) && r.override) { await resetRule(r); return }
  if (!d.reason.trim()) { ruleErr[r.id] = t('project-settings.reasonRequired'); return }
  ruleBusy.value = r.id
  try {
    await put(`/projects/${encodeURIComponent(project.ref ?? '')}/rules/${encodeURIComponent(r.id)}`, overrideBody(r, d))
    flash(t('project-settings.ruleSaved', { r: r.id }))
    await loadRules()
  } catch (e) {
    ruleErr[r.id] = errorText(e)
  } finally {
    ruleBusy.value = ''
  }
}
async function resetRule(r: RuleRow): Promise<void> {
  ruleBusy.value = r.id
  ruleErr[r.id] = ''
  try {
    await del(`/projects/${encodeURIComponent(project.ref ?? '')}/rules/${encodeURIComponent(r.id)}`)
    flash(t('project-settings.ruleReset', { r: r.id }))
    await loadRules()
  } catch (e) {
    ruleErr[r.id] = errorText(e)
  } finally {
    ruleBusy.value = ''
  }
}

/* ---------------- 成员 ---------------- */
const members = computed<Member[]>(() => info.value?.member_list ?? [])
const inviteName = ref('')
const inviteRole = ref<'manage' | 'edit' | 'read'>('edit')
const memBusy = ref('')
const memError = ref('')
const accounts = ref<string[]>([])
const confirmRemove = ref<string | null>(null)
const isMe = (u: string) => auth.me?.username === u

async function setMember(u: string, role: 'manage' | 'edit' | 'read', invite = false): Promise<void> {
  memBusy.value = u
  memError.value = ''
  try {
    await put(`/projects/${encodeURIComponent(project.ref ?? '')}/members/${encodeURIComponent(u)}`, { role })
    await project.reload()
    flash(invite ? t('project-settings.invited', { u }) : t('project-settings.roleChanged', { u, r: t(`proj.role.${role}`) }))
    if (invite) inviteName.value = ''
  } catch (e) {
    memError.value = errorText(e)
  } finally {
    memBusy.value = ''
  }
}
function invite(): void {
  const u = inviteName.value.trim()
  if (!u) return
  void setMember(u, inviteRole.value, true)
}
async function removeMember(u: string): Promise<void> {
  confirmRemove.value = null
  memBusy.value = u
  memError.value = ''
  try {
    await del(`/projects/${encodeURIComponent(project.ref ?? '')}/members/${encodeURIComponent(u)}`)
    await project.reload()
    flash(t('project-settings.removed', { u }))
  } catch (e) {
    memError.value = errorText(e)
  } finally {
    memBusy.value = ''
  }
}

/* ---------------- 可被搜索（M9-8） ---------------- */
const discBusy = ref(false)
const discError = ref('')
async function setDiscoverable(on: boolean): Promise<void> {
  discBusy.value = true
  discError.value = ''
  try {
    await put(`/projects/${encodeURIComponent(project.ref ?? '')}`, { discoverable: on })
    await project.reload()
    flash(t(on ? 'join.discOn' : 'join.discOff'))
  } catch (e) {
    discError.value = errorText(e)
  } finally {
    discBusy.value = false
  }
}
const pendingCount = ref(0)

/* ---------------- 转交、复制、删除、退出 ---------------- */
type Dlg = 'copy' | 'transfer' | 'delete' | 'leave'
const dlg = ref<Dlg | null>(null)
async function onTransferred(r: { owner: string; kept_as: string | null; full_ref?: string }): Promise<void> {
  dlg.value = null
  flash(t('project-settings.transferred', { u: r.owner }))
  // 转交后项目属于新属主：规范引用变成“新属主/标识”，换到新网址
  if ((r.kept_as || auth.isAdmin) && r.full_ref) {
    project.forget()
    await router.replace({ name: 'project-settings', params: { project: r.full_ref } })
  } else { project.forget(); await router.push({ name: 'projects' }) }
}
async function onGone(): Promise<void> {
  dlg.value = null
  project.forget()
  void status.refresh()
  await router.push({ name: 'projects' })
}
async function onCopied(p: { ref: string; name: string }): Promise<void> {
  dlg.value = null
  flash(t('project-settings.copied', { p: p.name }))
  await router.push({ name: 'project-settings', params: { project: p.ref } })
}

/* ---------------- 载入与目录 ---------------- */
async function init(): Promise<void> {
  fillForm()
  void loadRules()
}
onMounted(async () => {
  void init()
  try { ruleSets.value = (await get<{ items: { id: string; title: Record<string, string> | null }[] }>('/translate-rules')).items } catch { /* 只能选“不指定” */ }
  try { baselines.value = (await get<{ profiles: { id: string; title: Record<string, string> | null }[] }>('/baseline/rules')).profiles } catch { /* 同上 */ }
  if (auth.isAdmin) {
    try { accounts.value = (await get<{ users: { username: string; disabled: boolean }[] }>('/users')).users.filter((u) => !u.disabled).map((u) => u.username) } catch { /* 手动输入 */ }
  }
})
watch(() => project.ref, (v, old) => { if (v && v !== old) void init() })

const SECTIONS = computed(() => [
  { id: 's-general', icon: 'gear', key: 'project-settings.general' },
  { id: 's-defaults', icon: 'sliders', key: 'project-settings.defaults' },
  { id: 's-rules', icon: 'shield', key: 'project-settings.rules' },
  { id: 's-members', icon: 'users', key: 'project-settings.members' },
  ...(canManage.value ? [{ id: 's-requests', icon: 'inbox', key: 'join.requests' }, { id: 's-invites', icon: 'link', key: 'join.invites' }] : []),
  { id: 's-danger', icon: 'warn', key: 'project-settings.danger' },
])
const activeSec = ref('s-general')
function goSec(id: string): void {
  activeSec.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
let mainEl: HTMLElement | null = null
function onScroll(): void {
  let cur = 's-general'
  for (const s of SECTIONS.value) {
    const el = document.getElementById(s.id)
    if (el && el.getBoundingClientRect().top < 160) cur = s.id
  }
  activeSec.value = cur
}
onMounted(() => { mainEl = document.querySelector('.main'); mainEl?.addEventListener('scroll', onScroll) })
onBeforeUnmount(() => mainEl?.removeEventListener('scroll', onScroll))
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs">
        <router-link :to="{ name: 'projects' }">{{ $t('nav.projects') }}</router-link><span class="sep">/</span>
        <span>{{ info?.name }}</span><span class="sep">/</span><span>{{ $t('project-settings.crumb') }}</span>
      </div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.project-settings') }}</h1>
          <p v-if="info" class="ph-sub" data-testid="ps-sub">
            {{ info.name }} · {{ $t('project-settings.sub', { u: info.owner ?? '—' }) }} <ProjRole :role="info.role" /> · {{ $t('project-settings.created', { t: shortTime(info.created_at) }) }}
          </p>
        </div>
      </div>

      <p v-if="!info" class="faint">{{ $t('c.loading') }}</p>
      <div v-else class="ps-wrap">
        <nav class="ps-side" aria-label="Sections">
          <a v-for="s in SECTIONS" :key="s.id" :href="`#${s.id}`" :aria-current="activeSec === s.id ? 'true' : 'false'" @click.prevent="goSec(s.id)"><Icon :name="s.icon" small /><span>{{ $t(s.key) }}</span><span v-if="s.id === 's-requests' && pendingCount" class="ps-cnt" data-testid="ps-requests-count">{{ pendingCount }}</span></a>
        </nav>
        <div>
          <section id="s-general" class="panel ps-sec" data-testid="ps-general">
            <div class="panel-h"><h2>{{ $t('project-settings.general') }}</h2></div>
            <div class="panel-b form-grid">
              <div class="field">
                <label for="fName">{{ $t('project-settings.name') }}</label>
                <input id="fName" v-model="form.name" :class="['input', { 'is-error': !form.name.trim() }]" :disabled="!canEdit" maxlength="200" data-testid="ps-name">
              </div>
              <div class="field">
                <label for="fSlug">{{ $t('project-settings.slug') }}</label>
                <input id="fSlug" v-model="form.slug" :class="['input mono', { 'is-error': slugErr }]" :disabled="!canOwn" maxlength="64" data-testid="ps-slug">
                <div v-if="slugErr" class="err"><Icon name="warn" small /><span>{{ $t('projects.dlg.slugErr') }}</span></div>
                <div v-else class="hint">{{ canOwn ? $t('project-settings.slugHint') : $t('project-settings.slugOwnerOnly') }}</div>
              </div>
              <div class="field span2">
                <label for="fDesc">{{ $t('project-settings.desc') }}</label>
                <textarea id="fDesc" v-model="form.description" class="textarea" rows="2" :disabled="!canEdit" maxlength="4000" data-testid="ps-desc" />
              </div>
            </div>
            <div class="disc-switch" data-testid="ps-discoverable">
              <div>
                <b>{{ $t('join.discoverable') }}</b>
                <p>{{ $t('join.discoverableText') }}</p>
                <div v-if="info.discoverable" class="disc-preview"><Icon name="eye" small />{{ $t('join.othersSee') }} <b>{{ info.name }}</b> · {{ info.owner ?? '—' }} · {{ $t('join.nDevices', { n: info.counts.devices }) }}</div>
                <div v-if="discError" class="small err-text">{{ discError }}</div>
              </div>
              <label class="switch" :title="canManage ? '' : $t('join.discManagerOnly')"><input type="checkbox" :checked="!!info.discoverable" :disabled="!canManage || discBusy" data-testid="ps-discoverable-switch" @change="setDiscoverable(($event.target as HTMLInputElement).checked)"><span /></label>
            </div>
          </section>

          <section id="s-defaults" class="panel ps-sec" data-testid="ps-defaults">
            <div class="panel-h"><h2>{{ $t('project-settings.defaults') }}</h2><span class="meta">{{ $t('project-settings.defaultsMeta') }}</span></div>
            <div class="panel-b form-grid">
              <div class="field">
                <span class="field-label">{{ $t('project-settings.style') }}</span>
                <div class="seg" role="group" data-testid="ps-style">
                  <button type="button" :aria-pressed="form.style === ''" :disabled="!canEdit" @click="form.style = ''">{{ $t('project-settings.styleNone') }}</button>
                  <button v-for="s in terms.styles" :key="s" type="button" :aria-pressed="form.style === s" :disabled="!canEdit" :data-style="s" @click="form.style = s">{{ styleLabel(s) }}</button>
                </div>
                <div class="hint">{{ $t('project-settings.styleHint') }}</div>
              </div>
              <div class="field">
                <label for="fRs">{{ $t('project-settings.ruleSet') }}</label>
                <select id="fRs" v-model="form.rule_set" class="select" :disabled="!canEdit" data-testid="ps-ruleset">
                  <option value="">{{ $t('project-settings.ruleSetNone') }}</option>
                  <option v-if="form.rule_set && !ruleSets.some((r) => r.id === form.rule_set)" :value="form.rule_set">{{ form.rule_set }}</option>
                  <option v-for="r in ruleSets" :key="r.id" :value="r.id">{{ pickLang(r.title, prefs.lang) || r.id }}</option>
                </select>
                <div class="hint">{{ $t('project-settings.ruleSetHint') }}</div>
              </div>
              <div class="field">
                <label for="fBl">{{ $t('project-settings.baseline') }}</label>
                <select id="fBl" v-model="form.baseline" class="select" :disabled="!canEdit" data-testid="ps-baseline">
                  <option value="">{{ $t('project-settings.baselineNone') }}</option>
                  <option v-if="form.baseline && !baselines.some((b) => b.id === form.baseline)" :value="form.baseline">{{ form.baseline }}</option>
                  <option v-for="b in baselines" :key="b.id" :value="b.id">{{ pickLang(b.title, prefs.lang) || b.id }}</option>
                </select>
                <div class="hint">{{ $t('project-settings.baselineHint') }}</div>
              </div>
            </div>
          </section>

          <div class="row save-row">
            <span v-if="saveError" class="small err-text" data-testid="ps-save-error">{{ saveError }}</span>
            <span v-else-if="!canEdit" class="small faint">{{ $t('project-settings.readOnlySave') }}</span>
            <button v-if="canEdit" class="btn btn-primary" type="button" :disabled="saving || slugErr || !form.name.trim()" data-testid="ps-save" @click="save"><Icon name="check" small />{{ $t('project-settings.save') }}</button>
          </div>

          <section id="s-rules" class="panel ps-sec" data-testid="ps-rules">
            <div class="panel-h toolbar" style="padding: 8px 14px">
              <h2 style="flex: none">{{ $t('project-settings.rules') }}</h2>
              <div class="seg" role="group">
                <button type="button" :aria-pressed="ruleFilter === 'all'" @click="ruleFilter = 'all'">{{ $t('project-settings.rulesAll') }} <span class="faint">{{ rules.length }}</span></button>
                <button type="button" :aria-pressed="ruleFilter === 'adj'" data-testid="ps-rules-adjusted" @click="ruleFilter = 'adj'">{{ $t('project-settings.rulesAdjusted') }} <span class="faint">{{ adjusted }}</span></button>
              </div>
            </div>
            <div class="panel-b tight" style="padding: 10px 14px 0"><div class="notice info"><Icon name="info" /><div>{{ $t('project-settings.rulesNote') }}</div></div></div>
            <div v-if="rulesError" class="notice err" style="margin: 10px 14px"><Icon name="err" /><div class="grow">{{ rulesError }}</div><button class="btn btn-sm" type="button" @click="loadRules">{{ $t('c.retry') }}</button></div>
            <p v-else-if="rulesLoading && !rules.length" class="faint" style="padding: 10px 14px">{{ $t('c.loading') }}</p>
            <div v-else class="tbl-wrap">
              <table class="tbl">
                <thead><tr><th>{{ $t('project-settings.colRule') }}</th><th>{{ $t('project-settings.colDomain') }}</th><th>{{ $t('project-settings.colShared') }}</th><th>{{ $t('project-settings.colProject') }}</th><th>{{ $t('project-settings.colReason') }}</th><th /></tr></thead>
                <tbody>
                  <tr v-if="!shownRules.length"><td colspan="6" class="faint">{{ $t('project-settings.noRules') }}</td></tr>
                  <tr v-for="r in shownRules" :key="r.id" :class="{ 'rule-off': drafts[r.id] && !drafts[r.id].enabled }" :data-testid="`ps-rule-${r.id}`">
                    <td><div class="rname" style="font-weight: 600">{{ ruleTitle(r) }}</div><div class="mono small faint">{{ r.id }}</div></td>
                    <td class="small">{{ r.domain || '—' }}</td>
                    <td><span :class="['sev', r.severity]">{{ $t(`project-settings.sev.${r.severity}`) }}</span><div v-if="!r.enabled" class="small faint">{{ $t('project-settings.sharedOff') }}</div></td>
                    <td>
                      <div v-if="drafts[r.id]" class="row" style="gap: 8px">
                        <label class="switch" :title="$t('project-settings.enableTip')"><input v-model="drafts[r.id].enabled" type="checkbox" :disabled="!canEdit || !r.enabled" :data-testid="`ps-rule-on-${r.id}`"><span /></label>
                        <select v-model="drafts[r.id].severity" class="select sev-sel" :disabled="!canEdit || !drafts[r.id].enabled" :data-testid="`ps-rule-sev-${r.id}`">
                          <option v-for="s in SEVERITIES" :key="s" :value="s">{{ $t(`project-settings.sev.${s}`) }}</option>
                        </select>
                        <span v-if="overrideMark(r)" class="ovr">{{ overrideMark(r) === 'off' ? $t('project-settings.markOff') : $t('project-settings.markAdjusted') }}</span>
                      </div>
                    </td>
                    <td>
                      <input v-if="drafts[r.id]" v-model="drafts[r.id].reason" :class="['input', { 'is-error': !!ruleErr[r.id] }]" style="height: 26px; font-size: 12px" :disabled="!canEdit" :placeholder="$t('project-settings.reasonPh')" maxlength="2000" :data-testid="`ps-rule-reason-${r.id}`">
                      <div v-if="ruleErr[r.id]" class="small err-text">{{ ruleErr[r.id] }}</div>
                    </td>
                    <td class="right nowrap">
                      <button v-if="canEdit && drafts[r.id] && isDirty(r, drafts[r.id])" class="btn btn-sm btn-primary" type="button" :disabled="ruleBusy === r.id" :data-testid="`ps-rule-save-${r.id}`" @click="saveRule(r)">{{ $t('project-settings.apply') }}</button>
                      <button v-if="canEdit && r.override" class="btn btn-sm btn-ghost" type="button" :disabled="ruleBusy === r.id" :data-testid="`ps-rule-reset-${r.id}`" @click="resetRule(r)"><Icon name="rollback" small />{{ $t('project-settings.reset') }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section id="s-members" class="panel ps-sec" data-testid="ps-members">
            <div class="panel-h"><h2>{{ $t('project-settings.members') }}</h2><span class="meta">{{ $t('project-settings.memCount', { n: members.length }) }}</span></div>
            <div class="panel-b" style="padding-bottom: 6px">
              <div v-if="canManage" class="inv-row">
                <label class="input-wrap"><Icon name="userPlus" small /><input v-model="inviteName" class="input" :list="accounts.length ? 'psAcc' : undefined" autocomplete="off" :placeholder="$t('project-settings.invitePh')" data-testid="ps-invite-name" @keydown.enter="invite"></label>
                <datalist v-if="accounts.length" id="psAcc"><option v-for="a in accounts.filter((x) => !members.some((m) => m.username === x))" :key="a" :value="a" /></datalist>
                <select v-model="inviteRole" class="select" data-testid="ps-invite-role">
                  <option value="manage">{{ $t('proj.role.manage') }}</option>
                  <option value="edit">{{ $t('proj.role.edit') }}</option>
                  <option value="read">{{ $t('proj.role.read') }}</option>
                </select>
                <button class="btn btn-primary" type="button" :disabled="!inviteName.trim() || !!memBusy" data-testid="ps-invite" @click="invite"><Icon name="userPlus" small />{{ $t('project-settings.invite') }}</button>
              </div>
              <div v-if="memError" class="notice err mt8" data-testid="ps-member-error"><Icon name="err" /><div>{{ memError }}</div></div>
              <p class="small faint mt8">{{ $t('project-settings.inviteNote') }}</p>
            </div>
            <div class="tbl-wrap">
              <table class="tbl">
                <thead><tr><th>{{ $t('project-settings.colAccount') }}</th><th>{{ $t('project-settings.colRole') }}</th><th>{{ $t('project-settings.colSince') }}</th><th /></tr></thead>
                <tbody>
                  <tr v-for="m in members" :key="m.username" :data-testid="`ps-member-${m.username}`">
                    <td>
                      <div class="who"><span class="m6av">{{ m.username.charAt(0).toUpperCase() }}</span><b>{{ m.username }}</b><span v-if="isMe(m.username)" class="faint">{{ $t('project-settings.me') }}</span><span v-if="m.disabled" class="tag">{{ $t('project-settings.disabled') }}</span></div>
                    </td>
                    <td>
                      <ProjRole v-if="m.role === 'owner' || !canManage" :role="m.role" />
                      <select v-else class="select sev-sel" style="width: 120px" :value="m.role" :disabled="memBusy === m.username" :data-testid="`ps-member-role-${m.username}`" @change="setMember(m.username, ($event.target as HTMLSelectElement).value as 'manage' | 'edit' | 'read')">
                        <option value="manage">{{ $t('proj.role.manage') }}</option>
                        <option value="edit">{{ $t('proj.role.edit') }}</option>
                        <option value="read">{{ $t('proj.role.read') }}</option>
                      </select>
                    </td>
                    <td class="small muted">{{ shortTime(m.since) }}</td>
                    <td class="right">
                      <button v-if="m.role === 'owner' && canOwn" class="btn btn-sm" type="button" @click="dlg = 'transfer'"><Icon name="transfer" small />{{ $t('project-settings.transferOwner') }}</button>
                      <span v-else-if="m.role === 'owner' && canManage" class="why-locked"><Icon name="lock" small />{{ $t('join.ownerOnlyTransfer') }}</span>
                      <template v-else-if="m.role !== 'owner' && canManage && !isMe(m.username)">
                        <template v-if="confirmRemove === m.username">
                          <span class="small">{{ $t('project-settings.removeConfirm', { u: m.username }) }}</span>
                          <button class="btn btn-sm btn-danger" type="button" :data-testid="`ps-member-remove-ok-${m.username}`" @click="removeMember(m.username)">{{ $t('project-settings.remove') }}</button>
                          <button class="btn btn-sm btn-ghost" type="button" @click="confirmRemove = null">{{ $t('c.cancel') }}</button>
                        </template>
                        <button v-else class="btn btn-sm btn-danger" type="button" :disabled="memBusy === m.username" :data-testid="`ps-member-remove-${m.username}`" @click="confirmRemove = m.username">{{ $t('project-settings.remove') }}</button>
                      </template>
                      <button v-else-if="isMe(m.username) && m.role !== 'owner'" class="btn btn-sm" type="button" data-testid="ps-leave" @click="dlg = 'leave'">{{ $t('project-settings.leave') }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <JoinRequestsPanel v-if="canManage && project.ref" :project-ref="project.ref" @changed="(m) => { flash(m); void project.reload() }" @count="(n) => (pendingCount = n)" />
          <InvitesPanel v-if="canManage && project.ref" :project-ref="project.ref" @changed="flash" />

          <section id="s-danger" class="panel ps-sec danger-zone" data-testid="ps-danger">
            <div class="panel-h"><h2>{{ $t('project-settings.danger') }}</h2><span class="meta">{{ $t('project-settings.dangerMeta') }}</span></div>
            <div v-if="canManage && !canOwn" class="panel-b"><div class="notice info" data-testid="ps-manage-note"><Icon name="lock" /><div>{{ $t('join.manageDangerNote') }}</div></div></div>
            <div>
              <div class="dz-row"><div><b>{{ $t('project-settings.dzTransfer') }}</b><p>{{ $t('project-settings.dzTransferText') }}</p></div><button class="btn" type="button" :disabled="!canOwn" data-testid="ps-transfer" @click="dlg = 'transfer'"><Icon name="transfer" small />{{ $t('project-settings.transferBtn') }}</button></div>
              <div class="dz-row"><div><b>{{ $t('project-settings.dzCopy') }}</b><p>{{ $t('project-settings.dzCopyText') }}</p></div><button class="btn" type="button" :disabled="!!auth.me?.read_only" data-testid="ps-copy" @click="dlg = 'copy'"><Icon name="copy" small />{{ $t('project-settings.copyBtn') }}</button></div>
              <div class="dz-row"><div><b>{{ $t('project-settings.dzDelete') }}</b><p>{{ $t('project-settings.dzDeleteText') }}</p></div><button class="btn btn-danger" type="button" :disabled="!canOwn" data-testid="ps-delete" @click="dlg = 'delete'"><Icon name="trash" small />{{ $t('project-settings.deleteBtn') }}</button></div>
            </div>
          </section>
        </div>
      </div>
    </div>

    <template v-if="info">
      <CopyProjectDialog v-if="dlg === 'copy'" :project="info" @close="dlg = null" @copied="onCopied" />
      <TransferDialog v-else-if="dlg === 'transfer'" :project="info" @close="dlg = null" @transferred="onTransferred" />
      <DeleteProjectDialog v-else-if="dlg === 'delete'" :project="info" @close="dlg = null" @deleted="onGone()" />
      <LeaveDialog v-else-if="dlg === 'leave'" :project="info" @close="dlg = null" @left="onGone()" />
    </template>
    <div v-if="toast" class="toast" role="status" data-testid="ps-toast"><Icon name="check" small /><span>{{ toast }}</span></div>
  </main>
</template>

<style scoped>
.save-row { justify-content: flex-end; gap: 10px; align-items: center; margin: -4px 0 14px; }
.err-text { color: var(--red-ink); }
.who { display: flex; align-items: center; gap: 8px; }
.who .tag { height: 18px; font-size: 11px; }
.seg button:disabled { cursor: not-allowed; opacity: .6; }
</style>
