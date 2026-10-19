<script setup lang="ts">
/**
 * 自助注册（REQ-039，预览 DevelopDocs/ui-preview/REQ-039/login.html）：注册表单（规则逐条打勾）→ 结果：
 * 需要审核时“等待管理员审核”，不需审核时已登录并进入首页；注册关闭时说明“注册未开放”。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api'
import { usePrefs } from '@/stores/prefs'
import { useAuth } from '@/stores/auth'
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import BareTopbar from '@/components/wizard-bare-topbar.vue'
import { signUpChecks, type AuthStatus } from './account/account'

interface RegisterResult { username: string; status: 'pending' | 'active'; user?: { username: string; role: string }; expires_at?: string }

const prefs = usePrefs()
const auth = useAuth()
const router = useRouter()

const status = ref<AuthStatus | null>(null)
const loadError = ref('')
const username = ref('')
const password = ref('')
const password2 = ref('')
const reveal = ref(false)
const busy = ref(false)
const error = ref('')
const taken = ref(false)
const rate = ref('')
const done = ref<RegisterResult | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

const open = computed(() => !!status.value?.registration?.open)
const approval = computed(() => status.value?.registration?.approval !== false)
const checks = computed(() => signUpChecks(username.value, password.value, password2.value))
const canSubmit = computed(() => !busy.value && !rate.value && Object.values(checks.value).every((v) => v === true))

watch(() => prefs.lang, () => { error.value = ''; rate.value = '' })
watch(username, () => { taken.value = false })

async function loadStatus(): Promise<void> {
  loadError.value = ''
  try {
    status.value = await api<AuthStatus>('/auth/status')
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
}
onMounted(loadStatus)
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await api<RegisterResult>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username: username.value.trim(), password: password.value }),
    })
    password.value = password2.value = ''
    done.value = r
    if (r.status === 'active' && r.user && r.expires_at) {
      auth.set(r.user, r.expires_at)
      timer = setTimeout(() => { void router.replace('/') }, 1800)
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    if (e instanceof ApiError && e.status === 409) taken.value = true
    else if (e instanceof ApiError && e.status === 429) rate.value = msg
    else if (e instanceof ApiError && e.status === 403) await loadStatus() // 管理员刚关闭了注册
    else error.value = msg
  } finally {
    busy.value = false
  }
}

function mark(v: boolean | null): { cls: string; icon: string } {
  if (v === null) return { cls: 'todo', icon: 'info' }
  return v ? { cls: 'ok', icon: 'check' } : { cls: 'bad', icon: 'x' }
}
</script>

<template>
  <div class="bare login-page">
    <BareTopbar />
    <div class="login-wrap">
      <form class="login-card" novalidate data-testid="register-form" @submit.prevent="submit">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span class="login-logo" v-html="LOGO_SVG" />

        <div v-if="loadError" class="notice err" role="alert">
          <Icon name="err" /><div class="grow small">{{ loadError }}</div>
          <button type="button" class="btn btn-sm" @click="loadStatus"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
        </div>
        <p v-else-if="!status" class="faint">{{ $t('c.loading') }}</p>

        <!-- 注册成功：等待审核 -->
        <div v-else-if="done && done.status === 'pending'" class="result" role="status" data-testid="register-pending">
          <span class="badge wait"><Icon name="clock" /></span>
          <h1>{{ $t('register.pendingTitle') }}</h1>
          <div class="who-line"><span class="av">{{ done.username.charAt(0).toUpperCase() }}</span><b>{{ done.username }}</b><span class="tag t-amber">{{ $t('register.pendingTag') }}</span></div>
          <p>{{ $t('register.pendingText') }}</p>
          <ul class="steps">
            <li class="done"><Icon name="ok" small /><span>{{ $t('register.step.submitted') }}</span></li>
            <li class="now"><Icon name="clock" small /><span>{{ $t('register.step.waiting') }}</span></li>
            <li class="next"><Icon name="chevR" small /><span>{{ $t('register.step.next') }}</span></li>
          </ul>
          <router-link class="btn go" :to="{ name: 'login' }" data-testid="register-back"><Icon name="chevL" small />{{ $t('register.back') }}</router-link>
        </div>

        <!-- 注册成功：已登录 -->
        <div v-else-if="done" class="result" role="status" data-testid="register-active">
          <span class="badge ok"><Icon name="check" /></span>
          <h1>{{ $t('register.activeTitle') }}</h1>
          <div class="who-line"><span class="av">{{ done.username.charAt(0).toUpperCase() }}</span><b>{{ done.username }}</b><span class="tag">{{ $t('register.userTag') }}</span></div>
          <ul class="steps">
            <li class="done"><Icon name="ok" small /><span>{{ $t('register.step.created') }}</span></li>
            <li class="done"><Icon name="ok" small /><span>{{ $t('register.step.project') }}</span></li>
            <li class="done"><Icon name="ok" small /><span>{{ $t('register.step.signedIn', { h: status.session_hours }) }}</span></li>
          </ul>
          <div class="progress-line" aria-hidden="true"><i /></div>
          <p>{{ $t('register.going') }}</p>
          <router-link class="btn btn-primary go" to="/" data-testid="register-go">{{ $t('register.goNow') }}</router-link>
        </div>

        <!-- 注册关闭 -->
        <div v-else-if="!open" class="result" role="alert" data-testid="register-closed">
          <span class="badge off"><Icon name="lock" /></span>
          <h1>{{ $t('register.closedTitle') }}</h1>
          <p>{{ $t('register.closedText') }}</p>
          <router-link class="btn go" :to="{ name: 'login' }"><Icon name="chevL" small />{{ $t('register.back') }}</router-link>
        </div>

        <!-- 注册表单 -->
        <template v-else>
          <h1>{{ $t('register.title') }}</h1>
          <p class="muted">{{ approval ? $t('register.hintApproval') : $t('register.hintDirect') }}</p>
          <div v-if="rate" class="notice warn" role="alert" data-testid="register-rate">
            <Icon name="clock" /><div class="grow small"><b>{{ $t('register.rateTitle') }}</b><br />{{ rate }}</div>
          </div>
          <div class="field">
            <label for="rg-user">{{ $t('register.username') }}</label>
            <input id="rg-user" v-model="username" :class="['input', { 'is-error': taken }]" autocomplete="username" spellcheck="false" maxlength="64" autofocus
              :aria-invalid="taken" data-testid="register-username" />
            <span v-if="taken" class="err" role="alert" data-testid="register-taken"><Icon name="err" small />{{ $t('register.taken') }}</span>
            <div class="rules">
              <span :class="mark(checks.nameLen).cls"><Icon :name="mark(checks.nameLen).icon" small />{{ $t('register.rule.nameLen') }}</span>
              <span :class="mark(checks.nameChars).cls"><Icon :name="mark(checks.nameChars).icon" small />{{ $t('register.rule.nameChars') }}</span>
            </div>
          </div>
          <div class="field">
            <label for="rg-pw">{{ $t('register.password') }}</label>
            <div class="tk">
              <input id="rg-pw" v-model="password" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" spellcheck="false" data-testid="register-password" />
              <button type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal"
                :title="$t(reveal ? 'register.hide' : 'register.show')" :aria-label="$t(reveal ? 'register.hide' : 'register.show')" @click="reveal = !reveal">
                <Icon :name="reveal ? 'eyeOff' : 'eye'" small />
              </button>
            </div>
          </div>
          <div class="field">
            <label for="rg-pw2">{{ $t('register.password2') }}</label>
            <input id="rg-pw2" v-model="password2" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" spellcheck="false" data-testid="register-password2" />
            <div class="rules">
              <span :class="mark(checks.pwLen).cls"><Icon :name="mark(checks.pwLen).icon" small />{{ $t('register.rule.pwLen') }}</span>
              <span :class="mark(checks.same).cls"><Icon :name="mark(checks.same).icon" small />{{ $t('register.rule.same') }}</span>
            </div>
          </div>
          <div class="reg-mode"><Icon name="user" small /><span>{{ $t('register.mode') }}</span></div>
          <span v-if="error" class="err" role="alert" data-testid="register-error"><Icon name="err" small />{{ error }}</span>
          <button type="submit" class="btn btn-primary go" :disabled="!canSubmit" data-testid="register-submit">
            {{ busy ? $t('register.submitting') : approval ? $t('register.submitApproval') : $t('register.submitDirect') }}
          </button>
          <div class="auth-alt"><span>{{ $t('register.haveAccount') }}</span><router-link :to="{ name: 'login' }" data-testid="register-to-login">{{ $t('register.signIn') }}</router-link></div>
        </template>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page { display: flex; flex-direction: column; background: var(--bg); }
.login-wrap { flex: 1; display: flex; align-items: center; justify-content: center; padding: 28px 16px 64px; }
.login-card {
  width: min(420px, 100%); background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 28px 28px 24px; display: flex; flex-direction: column; gap: 14px;
}
.login-logo { display: contents; }
.login-logo :deep(svg) { width: 44px; height: 44px; }
.login-card h1 { font-size: 20px; margin: 2px 0 0; }
.login-card > p { margin: -6px 0 2px; font-size: 13px; overflow-wrap: anywhere; }
.tk { position: relative; display: flex; align-items: center; }
.tk .input { width: 100%; padding-right: 34px; }
.tk .reveal { position: absolute; right: 3px; }
.tk .reveal[aria-pressed="true"] { color: var(--teal-ink); }
.go { width: 100%; justify-content: center; height: 34px; }
.rules { display: flex; flex-direction: column; gap: 3px; font-size: 12px; }
.rules span { display: inline-flex; align-items: center; gap: 5px; }
.rules .todo { color: var(--ink-3); }
.rules .ok { color: var(--teal-ink); }
.rules .bad { color: var(--red-ink); }
.err { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--red-ink); }
.reg-mode { display: flex; gap: 10px; align-items: flex-start; padding: 9px 11px; border-radius: 6px; border: 1px dashed var(--line-strong); background: var(--surface-2); font-size: 12.5px; color: var(--ink-2); }
.reg-mode :deep(.ico) { color: var(--ink-3); margin-top: 1px; flex: none; }
.auth-alt { display: flex; justify-content: center; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-2); }
.auth-alt a { color: var(--teal-ink); font-weight: 600; }
.result { display: flex; flex-direction: column; gap: 12px; }
.result .badge { width: 44px; height: 44px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--line); }
.result .badge.wait { background: var(--amber-soft); border-color: var(--amber-line); color: var(--amber-ink); }
.result .badge.ok { background: var(--teal-soft); border-color: var(--teal-line); color: var(--teal-ink); }
.result .badge.off { background: var(--surface-2); border-color: var(--line-strong); color: var(--ink-3); }
.result h1 { font-size: 20px; margin: 0; }
.result p { margin: 0; font-size: 13px; color: var(--ink-2); }
.who-line { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); font-size: 13px; }
.who-line .av { width: 22px; height: 22px; border-radius: 50%; background: var(--surface-3); color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 11px; }
.who-line .tag { margin-left: auto; }
.steps { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; color: var(--ink-2); }
.steps li { display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 8px; align-items: start; }
.steps li.done { color: var(--ink); }
.steps li.done :deep(.ico) { color: var(--teal-ink); }
.steps li.now :deep(.ico) { color: var(--amber-ink); }
.steps li.next :deep(.ico) { color: var(--ink-3); }
.progress-line { height: 3px; border-radius: 2px; background: var(--surface-3); overflow: hidden; }
.progress-line i { display: block; height: 100%; width: 70%; background: var(--teal); border-radius: 2px; animation: reg-go 1.6s ease-in-out infinite alternate; }
@keyframes reg-go { from { width: 25%; } to { width: 92%; } }
@media (prefers-reduced-motion: reduce) { .progress-line i { animation: none; } }
@media (max-width: 520px) { .login-card { padding: 22px 18px 20px; } }
</style>
