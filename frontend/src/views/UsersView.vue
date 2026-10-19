<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { del, errorText, get, post, put } from '@/api'
import { useAuth } from '@/stores/auth'
import Icon from '@/components/Icon.vue'
import {
  counts, deleteUserPath, isLastAdmin, passwordProblems, PERM_MATRIX, ROLES, shortTime, stateOf, transferTargets, validName,
  type AccountRole, type OwnedProject, type Perm, type UserRow,
} from './account/account'

type Dialog =
  | { kind: 'new' }
  | { kind: 'role'; user: UserRow }
  | { kind: 'reset'; user: UserRow }
  | { kind: 'disable'; user: UserRow }
  | { kind: 'delete'; user: UserRow }

const { t } = useI18n()
const auth = useAuth()
const rows = ref<UserRow[]>([])
const loading = ref(true)
const loadError = ref('')
const showOff = ref(true)
const busy = ref('') // 正在处理的账号名
const toast = ref('')
const dialog = ref<Dialog | null>(null)
const dlgError = ref('')
const dlgBusy = ref(false)
const form = ref({ username: '', role: 'user' as AccountRole, password: '', password2: '' })
// 删除账号：拥有的项目（打开对话框时读取）与处理方式
const owned = ref<OwnedProject[] | null>(null)
const delMode = ref<'transfer' | 'delete'>('transfer')
const delTo = ref('')
const ROLE_ICON: Record<AccountRole, string> = { admin: 'shield', maintainer: 'book', user: 'user' }
const ROLE_CHIP: Record<AccountRole, string> = { admin: 'r-admin', maintainer: 'r-maint', user: 'r-read' }
const PERM_MARK: Record<Perm, string> = { y: '✓', c: '◐', r: '◐', s: '✎', n: '—' }
const PERM_KEYS: Perm[] = ['y', 'c', 'r', 's', 'n']
const targets = computed(() => (dialog.value?.kind === 'delete' ? transferTargets(rows.value, dialog.value.user.username) : []))
const reveal = ref(false)

const shown = computed(() => rows.value.filter((u) => showOff.value || !u.disabled))
const n = computed(() => counts(rows.value))
const pwProblems = computed(() => passwordProblems(form.value.password, dialog.value?.kind === 'reset' ? form.value.password2 : undefined))
const dlgOk = computed(() => {
  const d = dialog.value
  if (!d) return false
  if (d.kind === 'new') return validName(form.value.username) && pwProblems.value.length === 0
  if (d.kind === 'reset') return pwProblems.value.length === 0
  if (d.kind === 'role') return form.value.role !== d.user.role
  if (d.kind === 'delete') return owned.value !== null && deleteUserPath(d.user.username, owned.value.length, delMode.value, delTo.value) !== null
  return true
})

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    rows.value = (await get<{ users: UserRow[] }>('/users')).users
  } catch (e) {
    loadError.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function flash(msg: string): void {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 2400)
}

const isMe = (u: UserRow) => auth.me?.via === 'session' && auth.me.username === u.username
/** 某个操作为什么不能做（空字符串表示可以）。 */
function blocked(u: UserRow, _action: 'demote' | 'disable' | 'delete'): string {
  if (isMe(u)) return t('users.self')
  if (isLastAdmin(u, rows.value)) return t('users.lastAdmin')
  return ''
}

function replace(u: UserRow): void {
  rows.value = rows.value.map((r) => (r.username === u.username ? u : r))
}

async function update(u: UserRow, body: Record<string, unknown>, msg: string): Promise<void> {
  busy.value = u.username
  try {
    replace((await put<{ user: UserRow }>(`/users/${encodeURIComponent(u.username)}`, body)).user)
    flash(msg)
  } catch (e) {
    flash(errorText(e))
  } finally {
    busy.value = ''
  }
}

async function open(d: Dialog): Promise<void> {
  form.value = { username: '', role: d.kind === 'role' ? d.user.role : 'user', password: '', password2: '' }
  reveal.value = false
  dlgError.value = ''
  dialog.value = d
  if (d.kind === 'delete') {
    owned.value = null
    delMode.value = 'transfer'
    delTo.value = transferTargets(rows.value, d.user.username).find((n) => n === auth.me?.username) ?? ''
    get<{ projects: OwnedProject[] }>(`/users/${encodeURIComponent(d.user.username)}/projects`)
      .then((r) => { owned.value = r.projects })
      .catch((e) => { dlgError.value = errorText(e) })
  }
  await nextTick()
  document.querySelector<HTMLInputElement>('.modal input, .modal button[data-ok]')?.focus()
}
function close(): void { if (!dlgBusy.value) dialog.value = null }

async function confirm(): Promise<void> {
  const d = dialog.value
  if (!d || !dlgOk.value) return
  dlgBusy.value = true
  dlgError.value = ''
  try {
    if (d.kind === 'new') {
      const r = await post<{ user: UserRow }>('/users', { username: form.value.username.trim(), password: form.value.password, role: form.value.role })
      rows.value = [...rows.value, r.user].sort((a, b) => a.username.localeCompare(b.username))
      flash(t('users.created', { name: r.user.username }))
    } else if (d.kind === 'reset') {
      const r = await post<{ user: UserRow }>(`/users/${encodeURIComponent(d.user.username)}/password`, { password: form.value.password })
      replace(r.user)
      flash(t('users.resetDone', { name: d.user.username }))
    } else if (d.kind === 'role') {
      replace((await put<{ user: UserRow }>(`/users/${encodeURIComponent(d.user.username)}`, { role: form.value.role })).user)
      flash(t('users.roleSaved'))
    } else if (d.kind === 'disable') {
      replace((await put<{ user: UserRow }>(`/users/${encodeURIComponent(d.user.username)}`, { disabled: true })).user)
      flash(t('users.saved'))
    } else {
      const path = deleteUserPath(d.user.username, owned.value?.length ?? 0, delMode.value, delTo.value)
      if (!path) return
      await del(path)
      rows.value = rows.value.filter((r) => r.username !== d.user.username)
      flash(t('users.saved'))
    }
    form.value.password = form.value.password2 = ''
    dlgBusy.value = false
    close()
  } catch (e) {
    dlgError.value = errorText(e)
  } finally {
    dlgBusy.value = false
  }
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.sys') }}</span><span class="sep">/</span><span>{{ $t('nav.users') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('users.title') }}</h1>
          <p class="ph-sub">{{ $t('users.sub') }}</p>
        </div>
        <div class="ph-actions">
          <button type="button" class="btn btn-primary" data-testid="users-new" @click="open({ kind: 'new' })"><Icon name="plus" small />{{ $t('users.new') }}</button>
        </div>
      </div>

      <div class="acct-strip" data-testid="users-strip">
        <div><div class="v">{{ n.all }}</div><div class="k">{{ $t('users.kAll') }}</div></div>
        <div><div class="v">{{ n.admin }}</div><div class="k">{{ $t('users.kAdmin') }}</div></div>
        <div><div class="v">{{ n.maint }}</div><div class="k">{{ $t('users.kMaint') }}</div></div>
        <div><div class="v">{{ n.locked }}</div><div class="k">{{ $t('users.kLocked') }}</div></div>
        <div><div class="v">{{ n.disabled }}</div><div class="k">{{ $t('users.kDisabled') }}</div></div>
      </div>

      <section class="panel">
        <div class="panel-h">
          <h2>{{ $t('users.list') }}</h2>
          <label class="check ml-auto small"><input v-model="showOff" type="checkbox" data-testid="users-show-off" /> {{ $t('users.showOff') }}</label>
        </div>
        <div v-if="loading && !rows.length" class="empty">{{ $t('c.loading') }}</div>
        <div v-else-if="loadError" class="panel-b">
          <div class="notice err" role="alert"><Icon name="err" /><div class="grow small">{{ loadError }}</div>
            <button type="button" class="btn btn-sm" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div>
        </div>
        <div v-else-if="!rows.length" class="empty">{{ $t('users.empty') }}</div>
        <div v-else class="tbl-wrap">
          <table class="tbl" data-testid="users-table">
            <thead><tr>
              <th>{{ $t('users.colName') }}</th><th>{{ $t('users.colRole') }}</th><th>{{ $t('users.colState') }}</th>
              <th>{{ $t('users.colProjects') }}</th><th>{{ $t('users.colTokens') }}</th>
              <th>{{ $t('users.colLast') }}</th><th>{{ $t('users.colCreated') }}</th><th class="right">{{ $t('users.colActions') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="u in shown" :key="u.id" :class="{ 'row-off': u.disabled }" :data-testid="`user-row-${u.username}`">
                <td>
                  <div class="who">
                    <span :class="['av', { admin: u.role === 'admin' }]" aria-hidden="true">{{ u.username.charAt(0).toUpperCase() }}</span>
                    <b>{{ u.username }}</b><span v-if="isMe(u)" class="me-tag">{{ $t('users.you') }}</span>
                  </div>
                </td>
                <td><span :class="['rolechip', ROLE_CHIP[u.role] ?? 'r-read']" :data-testid="`user-role-${u.role}`"><Icon :name="ROLE_ICON[u.role] ?? 'user'" small />{{ $t(`users.role.${u.role}`) }}</span></td>
                <td>
                  <span :class="['st-dot', stateOf(u) === 'locked' ? 'lock' : stateOf(u) === 'disabled' ? 'off' : '']">
                    <i />{{ stateOf(u) === 'locked' ? $t('users.st.locked', { t: shortTime(u.locked_until) }) : $t(`users.st.${stateOf(u)}`) }}
                  </span>
                </td>
                <td class="small"><span v-if="u.projects">{{ $t('users.nProjects', { n: u.projects }) }}</span><span v-else class="faint">—</span></td>
                <td class="small"><span v-if="u.tokens">{{ $t('users.nTokens', { n: u.tokens }) }}</span><span v-else class="faint">—</span></td>
                <td class="mono"><span v-if="u.last_login_at">{{ shortTime(u.last_login_at) }}</span><span v-else class="faint">{{ $t('users.never') }}</span></td>
                <td class="mono">{{ shortTime(u.created_at).slice(0, 10) }}</td>
                <td>
                  <div class="acts">
                    <button type="button" class="btn btn-xs" :disabled="(u.role === 'admin' && !!blocked(u, 'demote')) || busy === u.username"
                      :title="u.role === 'admin' ? blocked(u, 'demote') : ''" data-testid="user-role" @click="open({ kind: 'role', user: u })">{{ $t('users.changeRole') }}</button>
                    <button type="button" class="btn btn-xs" data-testid="user-reset" @click="open({ kind: 'reset', user: u })"><Icon name="key" small />{{ $t('users.reset') }}</button>
                    <button v-if="u.locked" type="button" class="btn btn-xs" :disabled="busy === u.username" data-testid="user-unlock"
                      @click="update(u, { unlock: true }, $t('users.saved'))"><Icon name="lock" small />{{ $t('users.unlock') }}</button>
                    <button v-if="u.disabled" type="button" class="btn btn-xs" :disabled="busy === u.username" data-testid="user-enable"
                      @click="update(u, { disabled: false, unlock: true }, $t('users.saved'))">{{ $t('users.enable') }}</button>
                    <button v-else type="button" class="btn btn-xs" :disabled="!!blocked(u, 'disable')" :title="blocked(u, 'disable')"
                      data-testid="user-disable" @click="open({ kind: 'disable', user: u })">{{ $t('users.disable') }}</button>
                    <button type="button" class="btn btn-xs btn-ghost btn-danger btn-icon" :disabled="!!blocked(u, 'delete')"
                      :title="blocked(u, 'delete') || $t('users.delete')" :aria-label="$t('users.delete')" data-testid="user-delete"
                      @click="open({ kind: 'delete', user: u })"><Icon name="trash" small /></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <div class="notice info mt12"><Icon name="shield" /><div class="grow small">{{ $t('users.note') }}</div></div>

      <section class="panel mt16" data-testid="perm-matrix">
        <div class="panel-h"><h2>{{ $t('users.pmTitle') }}</h2><span class="meta">{{ $t('users.pmMeta') }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl permx">
            <thead><tr>
              <th>{{ $t('users.pmFeature') }}</th><th>{{ $t('users.role.admin') }}</th><th>{{ $t('users.role.maintainer') }}</th>
              <th>{{ $t('users.pmUser') }}</th><th>{{ $t('users.pmRead') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in PERM_MATRIX" :key="r.key">
                <td>{{ $t(`users.pm.${r.key}`) }}</td>
                <td v-for="(c, i) in r.cells" :key="i"><span :class="['pm', c === 'c' ? 'y' : c]" :title="$t(`users.pmk.${c}`)">{{ PERM_MARK[c] }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="panel-f small faint row wrap" style="gap: 14px">
          <span v-for="c in PERM_KEYS" :key="c" :class="['pm', c === 'c' ? 'y' : c]">{{ PERM_MARK[c] }} {{ $t(`users.pmk.${c}`) }}</span>
        </div>
      </section>
    </div>

    <div v-if="dialog" class="modal-back" @click.self="close" @keydown.esc="close">
      <form class="modal narrow" role="dialog" aria-modal="true" data-testid="users-dialog" novalidate @submit.prevent="confirm">
        <div class="modal-h">
          <h2>
            <template v-if="dialog.kind === 'new'">{{ $t('users.new') }}</template>
            <template v-else-if="dialog.kind === 'reset'">{{ $t('users.resetTitle', { name: dialog.user.username }) }}</template>
            <template v-else-if="dialog.kind === 'role'">{{ $t('users.roleTitle', { name: dialog.user.username }) }}</template>
            <template v-else-if="dialog.kind === 'disable'">{{ $t('users.disableTitle') }}</template>
            <template v-else>{{ $t('users.deleteTitle') }}</template>
          </h2>
          <button type="button" class="btn btn-sm btn-ghost btn-icon" :aria-label="$t('c.cancel')" @click="close"><Icon name="x" small /></button>
        </div>
        <div class="modal-b">
          <div v-if="dialog.kind === 'new'" class="form-stack">
            <div class="field">
              <label for="nu-name">{{ $t('users.colName') }}</label>
              <input id="nu-name" v-model="form.username" class="input" autocomplete="off" spellcheck="false" data-testid="new-username" />
              <span class="hint">{{ $t('account.nameHint') }}</span>
            </div>
            <div class="field">
              <span class="field-label">{{ $t('users.roleLabel') }}</span>
              <div class="role-cards three" role="radiogroup">
                <label v-for="r in ROLES" :key="r" class="radio-card"><span><input v-model="form.role" type="radio" :value="r" :data-testid="`new-role-${r}`" /> <b>{{ $t(`users.role.${r}`) }}</b></span><span class="rd">{{ $t(`users.roleDesc.${r}`) }}</span></label>
              </div>
            </div>
            <div class="field">
              <label for="nu-pw">{{ $t('users.initialPw') }}</label>
              <div class="pw">
                <input id="nu-pw" v-model="form.password" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" data-testid="new-password" />
                <button type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal" :aria-label="$t('login.show')" @click="reveal = !reveal"><Icon name="eye" small /></button>
              </div>
              <span class="hint">{{ $t('users.initialHint') }}</span>
            </div>
          </div>
          <div v-else-if="dialog.kind === 'reset'" class="form-stack">
            <div class="field">
              <label for="rp-pw">{{ $t('users.newPw') }}</label>
              <div class="pw">
                <input id="rp-pw" v-model="form.password" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" data-testid="reset-password" />
                <button type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal" :aria-label="$t('login.show')" @click="reveal = !reveal"><Icon name="eye" small /></button>
              </div>
            </div>
            <div class="field">
              <label for="rp-pw2">{{ $t('account.repeat') }}</label>
              <input id="rp-pw2" v-model="form.password2" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" data-testid="reset-password2" />
              <span v-for="p in pwProblems" :key="p" class="hint">{{ $t(`account.rule.${p}`) }}</span>
            </div>
            <div class="notice warn"><Icon name="warn" /><div class="grow small">{{ $t('users.resetNote') }}</div></div>
          </div>
          <div v-else-if="dialog.kind === 'role'" class="form-stack">
            <div class="role-cards three" role="radiogroup">
              <label v-for="r in ROLES" :key="r" class="radio-card"><span><input v-model="form.role" type="radio" :value="r" :data-testid="`role-${r}`" /> <b>{{ $t(`users.role.${r}`) }}</b></span><span class="rd">{{ $t(`users.roleDesc.${r}`) }}</span></label>
            </div>
            <p class="small faint">{{ $t('users.roleNote') }}</p>
          </div>
          <template v-else-if="dialog.kind === 'disable'">
            <p>{{ $t('users.disableNote') }}</p>
            <p class="mt8"><b class="mono">{{ dialog.user.username }}</b></p>
          </template>
          <div v-else class="form-stack">
            <p><b class="mono">{{ dialog.user.username }}</b></p>
            <p v-if="owned === null && !dlgError" class="faint">{{ $t('c.loading') }}</p>
            <template v-else-if="owned && owned.length">
              <p class="muted" data-testid="del-owned">{{ $t('users.delOwns', { n: owned.length }) }}<b>{{ owned.map((p) => p.name).join('、') }}</b></p>
              <div class="radio-cards">
                <label class="radio-card">
                  <input v-model="delMode" type="radio" value="transfer" data-testid="del-mode-transfer" />
                  <div style="flex: 1">
                    <div class="rc-t">{{ $t('users.delTransfer') }}</div>
                    <select v-model="delTo" class="select mt8" style="width: 220px" :disabled="delMode !== 'transfer'" data-testid="del-transfer-to">
                      <option value="" disabled>{{ $t('users.delPick') }}</option>
                      <option v-for="n in targets" :key="n" :value="n">{{ n }}</option>
                    </select>
                    <div class="rc-d mt8">{{ $t('users.delTransferNote') }}</div>
                  </div>
                </label>
                <label class="radio-card">
                  <input v-model="delMode" type="radio" value="delete" data-testid="del-mode-delete" />
                  <div><div class="rc-t">{{ $t('users.delProjects') }}</div><div class="rc-d">{{ $t('users.delProjectsNote') }}</div></div>
                </label>
              </div>
            </template>
            <p v-else-if="owned" class="muted">{{ $t('users.delNoProjects') }}</p>
            <p>{{ $t('users.deleteNote') }}</p>
            <p class="small faint">{{ $t('users.delAssets') }}</p>
          </div>
          <div v-if="dlgError" class="notice err mt12" role="alert" data-testid="users-dialog-error"><Icon name="err" /><div class="grow small">{{ dlgError }}</div></div>
        </div>
        <div class="modal-f">
          <button type="button" class="btn" @click="close">{{ $t('c.cancel') }}</button>
          <button type="submit" data-ok :class="['btn', dialog.kind === 'disable' || dialog.kind === 'delete' ? 'btn-danger-solid' : 'btn-primary']"
            :disabled="!dlgOk || dlgBusy" data-testid="users-dialog-ok">
            <template v-if="dialog.kind === 'new'">{{ $t('users.create') }}</template>
            <template v-else-if="dialog.kind === 'reset'">{{ $t('users.reset') }}</template>
            <template v-else-if="dialog.kind === 'role'">{{ $t('c.save') }}</template>
            <template v-else-if="dialog.kind === 'disable'">{{ $t('users.disable') }}</template>
            <template v-else>{{ $t('users.delete') }}</template>
          </button>
        </div>
      </form>
    </div>
    <div v-if="toast" class="toast" role="status" data-testid="users-toast"><Icon name="check" small /><span>{{ toast }}</span></div>
  </main>
</template>

<style scoped>
.acct-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-panel); margin-bottom: 12px; }
.acct-strip > div { padding: 10px 14px; border-left: 1px solid var(--line); min-width: 0; }
.acct-strip > div:first-child { border-left: 0; }
.acct-strip .v { font: 600 20px/1.25 var(--font-display); }
.acct-strip .k { font-size: 12px; color: var(--ink-2); }
.who { display: flex; align-items: center; gap: 9px; min-width: 0; }
.who .av { width: 26px; height: 26px; border-radius: 50%; background: var(--surface-3); color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 12px; flex: none; }
.who .av.admin { background: var(--teal-soft); color: var(--teal-ink); border: 1px solid var(--teal-line); }
.who b { font-weight: 600; }
.me-tag { font-size: 11px; color: var(--ink-3); }
.st-dot { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; white-space: nowrap; }
.st-dot i { width: 7px; height: 7px; border-radius: 50%; background: var(--teal); display: inline-block; }
.st-dot.off { color: var(--ink-3); }
.st-dot.off i { background: var(--line-strong); }
.st-dot.lock { color: var(--amber-ink); }
.st-dot.lock i { background: var(--amber); }
.row-off td { color: var(--ink-3); }
.acts { display: flex; gap: 4px; justify-content: flex-end; flex-wrap: wrap; }
.modal.narrow { width: min(640px, 100%); }
.radio-cards { display: flex; flex-direction: column; gap: 8px; }
.radio-cards .radio-card { align-items: flex-start; gap: 10px; }
.rc-t { font-weight: 600; }
.rc-d { font-size: 12px; color: var(--ink-2); }
.form-stack { display: flex; flex-direction: column; gap: 14px; }
.role-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.role-cards.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.role-cards .radio-card { flex-direction: column; align-items: flex-start; gap: 4px; }
.role-cards .rd { font-size: 12px; color: var(--ink-2); }
.pw { position: relative; display: flex; align-items: center; }
.pw .input { width: 100%; padding-right: 34px; }
.pw .reveal { position: absolute; right: 3px; }
.pw .reveal[aria-pressed="true"] { color: var(--teal-ink); }
@media (max-width: 900px) {
  .acct-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .acct-strip > div:nth-child(3) { border-left: 0; }
  .role-cards { grid-template-columns: 1fr; }
}
</style>
