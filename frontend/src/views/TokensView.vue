<script setup lang="ts">
/**
 * 我的 API 令牌（M6-4，预览 DevelopDocs/ui-preview/M6/tokens.html）：列表、生成（只显示一次）、撤销、移除；
 * 下方是用令牌调用 API（项目在路径中，设计问题 1 的结论）与命令行 --project 的示例。
 * 用全局 API 令牌访问时没有账号，/tokens 返回 409，页面说明需要用账号登录。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { del, errorText, get, post } from '@/api'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import { fmtTime } from '@/views/check-projects/logic'
import { apiExample, canRemove, canRevoke, cliExample, DEFAULT_DAYS, EXPIRY_DAYS, sortTokens, type CreatedToken, type TokenRow } from './tokens/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`tokens.${k}`, p ?? {})
const auth = useAuth()
const project = useProject()

const noAccount = computed(() => auth.me?.via === 'token')
const rows = ref<TokenRow[] | null>(null)
const loadErr = ref('')
const sample = ref<{ id: number; name: string } | null>(null)

async function load(): Promise<void> {
  loadErr.value = ''
  if (noAccount.value) { rows.value = []; return }
  try { rows.value = sortTokens((await get<{ tokens: TokenRow[] }>('/tokens')).tokens) } catch (e) { loadErr.value = errorText(e) }
}
async function loadSample(): Promise<void> {
  try {
    const d = (await get<{ devices: { id: number; name: string }[] }>('/devices')).devices
    sample.value = d[0] ?? null
  } catch { /* 示例里用占位 */ }
}

const slug = computed(() => project.slug ?? 'default')
const host = location.origin
const api = computed(() => apiExample(host, slug.value, sample.value?.id ?? null))
const cli = computed(() => cliExample(slug.value, sample.value?.name ?? null, T('devicePh')))

/* ---------------------------------------------------------------- 提示 */
const toast = ref('')
let toastTimer = 0
function flash(s: string): void { toast.value = s; window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => { toast.value = '' }, 2600) }

/* ---------------------------------------------------------------- 生成 */
const showNew = ref(false)
const nName = ref('')
const nDays = ref<number>(DEFAULT_DAYS)
const nRo = ref(false)
const nErr = ref('')
const nameErr = ref(false)
const busy = ref(false)
const created = ref<CreatedToken | null>(null)
const nameEl = ref<HTMLInputElement | null>(null)

function openNew(): void {
  nName.value = ''
  nDays.value = DEFAULT_DAYS
  nRo.value = false
  nErr.value = ''
  nameErr.value = false
  created.value = null
  showNew.value = true
  void nextTick(() => nameEl.value?.focus())
}
async function generate(): Promise<void> {
  if (!nName.value.trim()) { nameErr.value = true; return }
  nameErr.value = false
  busy.value = true
  nErr.value = ''
  try {
    created.value = await post<CreatedToken>('/tokens', { name: nName.value.trim(), read_only: nRo.value, days: nDays.value })
    void load()
  } catch (e) { nErr.value = errorText(e) } finally { busy.value = false }
}
async function copyToken(): Promise<void> {
  if (!created.value) return
  try { await navigator.clipboard.writeText(created.value.token); flash(T('copied')) } catch { flash(T('copyFailed')) }
}
function closeNew(): void {
  // 关闭后令牌不再保留在页面里
  created.value = null
  showNew.value = false
}

/* ---------------------------------------------------------------- 撤销 / 移除 */
const revTarget = ref<TokenRow | null>(null)
const revErr = ref('')
async function revoke(): Promise<void> {
  const tk = revTarget.value
  if (!tk) return
  busy.value = true
  revErr.value = ''
  try {
    await post(`/tokens/${tk.id}/revoke`)
    revTarget.value = null
    flash(T('revoked'))
    await load()
  } catch (e) { revErr.value = errorText(e) } finally { busy.value = false }
}
async function removeToken(tk: TokenRow): Promise<void> {
  try {
    await del(`/tokens/${tk.id}`)
    flash(T('removed'))
    await load()
  } catch (e) { flash(errorText(e)) }
}

onMounted(() => { void load(); void loadSample() })
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ auth.me?.username }}</span><span class="sep">/</span><span>{{ $t('nav.tokens') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.tokens') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions">
          <button v-if="!noAccount" class="btn btn-primary" type="button" data-testid="tok-new" @click="openNew"><Icon name="plus" small /><span>{{ T('generate') }}</span></button>
        </div>
      </div>

      <div v-if="noAccount" class="notice warn" data-testid="tok-no-account"><Icon name="warn" /><div>{{ T('globalToken') }}</div></div>
      <div v-else-if="loadErr" class="notice err"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <section v-else class="panel">
        <div class="tbl-wrap">
          <table class="tbl" data-testid="tok-table">
            <thead><tr>
              <th>{{ T('col.name') }}</th><th>{{ T('col.token') }}</th><th>{{ T('col.access') }}</th><th>{{ T('col.created') }}</th>
              <th>{{ T('col.expires') }}</th><th>{{ T('col.lastUsed') }}</th><th>{{ T('col.state') }}</th><th />
            </tr></thead>
            <tbody>
              <tr v-if="rows === null"><td colspan="8" class="muted" style="text-align: center; padding: 20px">{{ $t('c.loading') }}</td></tr>
              <tr v-else-if="!rows.length"><td colspan="8"><div class="empty" data-testid="tok-empty"><p>{{ T('empty') }}</p></div></td></tr>
              <template v-else>
              <tr v-for="tk in rows" :key="tk.id" :class="{ 'tr-dim': tk.state !== 'active' }" :data-testid="`tok-row-${tk.id}`">
                <td><b>{{ tk.name }}</b></td>
                <td class="mono">{{ tk.prefix }}…</td>
                <td class="small">{{ tk.read_only ? T('accessRo') : T('accessSame') }}</td>
                <td class="small muted nowrap">{{ fmtTime(tk.created_at) }}</td>
                <td class="small muted nowrap">{{ tk.expires_at ? fmtTime(tk.expires_at) : T('never') }}</td>
                <td class="small nowrap">
                  <template v-if="tk.last_used_at">{{ fmtTime(tk.last_used_at) }}<div v-if="tk.last_used_ip" class="faint">{{ tk.last_used_ip }}</div></template>
                  <span v-else class="faint">{{ T('unused') }}</span>
                </td>
                <td><span class="st-tok" :class="tk.state" :data-state="tk.state"><i />{{ T(`state.${tk.state}`) }}</span></td>
                <td class="right">
                  <button v-if="canRevoke(tk)" class="btn btn-sm btn-danger" type="button" :data-testid="`tok-revoke-${tk.id}`" @click="revTarget = tk; revErr = ''">{{ T('revoke') }}</button>
                  <button v-else-if="canRemove(tk)" class="btn btn-sm btn-ghost" type="button" :data-testid="`tok-remove-${tk.id}`" @click="removeToken(tk)">{{ T('remove') }}</button>
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>

      <div class="grid g2 mt16" style="align-items: start">
        <section class="panel">
          <div class="panel-h"><h2>{{ T('apiTitle') }}</h2><span class="tag t-blue">{{ T('apiPath') }}</span></div>
          <div class="panel-b stack" style="gap: 10px">
            <pre class="codeblk" data-testid="tok-api-example"><template v-for="(ex, i) in api" :key="i"><span class="c">{{ T(`c.${ex.comment}`) }}</span>{{ '\n' + ex.line + (i < api.length - 1 ? '\n\n' : '') }}</template></pre>
            <p class="small faint">{{ T('apiNote') }}</p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ T('cliTitle') }}</h2></div>
          <div class="panel-b stack" style="gap: 10px">
            <pre class="codeblk" data-testid="tok-cli-example"><span class="c">{{ T('cliComment') }}</span>{{ '\n' + cli.join('\n') + '\n' }}<span class="c">{{ T('cliForms') }}</span></pre>
            <p class="small faint">{{ T('cliNote') }}</p>
          </div>
        </section>
      </div>
    </div>

    <div v-if="showNew" class="modal-back" data-testid="tok-new-modal" @click.self="!created && closeNew()" @keydown.esc="!created && closeNew()">
      <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true" aria-labelledby="tokNewT">
        <div class="modal-h"><h2 id="tokNewT">{{ T('newTitle') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="closeNew"><Icon name="x" /></button></div>
        <div v-if="!created" class="modal-b form-stack">
          <div class="field">
            <label for="tokName">{{ T('col.name') }}</label>
            <input id="tokName" ref="nameEl" v-model="nName" class="input" :class="{ 'is-error': nameErr }" :placeholder="T('namePh')" maxlength="200" data-testid="tok-name" @keydown.enter="generate">
            <div v-if="nameErr" class="err"><Icon name="warn" small /><span>{{ T('nameRequired') }}</span></div>
          </div>
          <div class="field">
            <span class="field-label">{{ T('expiresIn') }}</span>
            <div class="seg" role="group" data-testid="tok-days">
              <button v-for="d in EXPIRY_DAYS" :key="d" type="button" :aria-pressed="nDays === d" :data-days="d" @click="nDays = d">{{ d ? T('days', { n: d }) : T('never') }}</button>
            </div>
          </div>
          <div class="field">
            <span class="field-label">{{ T('col.access') }}</span>
            <div class="radio-cards">
              <label class="radio-card"><input v-model="nRo" type="radio" :value="false"><div><div class="rc-t">{{ T('accessSame') }}</div><div class="rc-d">{{ T('sameDesc') }}</div></div></label>
              <label class="radio-card"><input v-model="nRo" type="radio" :value="true" data-testid="tok-ro"><div><div class="rc-t">{{ T('accessRo') }}</div><div class="rc-d">{{ T('roDesc') }}</div></div></label>
            </div>
          </div>
          <div v-if="nErr" class="notice err"><Icon name="err" /><div>{{ nErr }}</div></div>
        </div>
        <div v-else class="modal-b form-stack">
          <div class="notice warn"><Icon name="warn" /><div>{{ T('onceWarn') }}</div></div>
          <div class="tok-once"><code data-testid="tok-value">{{ created.token }}</code><button class="btn btn-sm" type="button" data-testid="tok-copy" @click="copyToken"><Icon name="copy" small /><span>{{ T('copy') }}</span></button></div>
          <p class="small faint">{{ T('prefixNote') }}</p>
        </div>
        <div v-if="!created" class="modal-f">
          <button class="btn" type="button" @click="closeNew">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="busy" data-testid="tok-generate" @click="generate">{{ T('doGenerate') }}</button>
        </div>
        <div v-else class="modal-f"><button class="btn btn-primary" type="button" data-testid="tok-saved" @click="closeNew">{{ T('saved') }}</button></div>
      </div>
    </div>

    <div v-if="revTarget" class="modal-back" data-testid="tok-revoke-modal" @click.self="revTarget = null" @keydown.esc="revTarget = null">
      <div class="modal" style="width: min(440px, 100%)" role="dialog" aria-modal="true" aria-labelledby="tokRevT">
        <div class="modal-h"><h2 id="tokRevT">{{ T('revokeTitle') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="revTarget = null"><Icon name="x" /></button></div>
        <div class="modal-b">
          <p><b>{{ revTarget.name }}</b> <span class="mono">{{ revTarget.prefix }}…</span></p>
          <p class="small faint mt8">{{ T('revokeNote') }}</p>
          <div v-if="revErr" class="notice err mt8"><Icon name="err" /><div>{{ revErr }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="revTarget = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger-solid" type="button" :disabled="busy" data-testid="tok-revoke-ok" @click="revoke">{{ T('revoke') }}</button>
        </div>
      </div>
    </div>

    <div v-if="toast" class="toast" role="status" data-testid="tok-toast">{{ toast }}</div>
  </main>
</template>
