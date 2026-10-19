<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api'
import { usePrefs } from '@/stores/prefs'
import { useAuth } from '@/stores/auth'
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import BareTopbar from '@/components/wizard-bare-topbar.vue'
import { bootMode, passwordProblems, safeNext, type AuthStatus } from './account/account'

interface LoginResult { user: { username: string; role: string }; expires_at: string }

const prefs = usePrefs()
const auth = useAuth()
const router = useRouter()
const route = useRoute()

const status = ref<AuthStatus | null>(null)
const loadError = ref('')
const username = ref('')
const password = ref('')
const password2 = ref('')
const token = ref('')
const reveal = ref(false)
const error = ref('')
const locked = ref(false)
const busy = ref(false)

const expired = computed(() => route.query.expired === '1')
const bootstrap = computed(() => status.value !== null && !status.value.has_users)
const noToken = computed(() => bootMode(status.value) === 'cli')
const configFile = computed(() => status.value?.config_file || 'config/config.toml')
const CLI_ADD = 'lmesh user add <username> --role admin'
const bootProblems = computed(() => passwordProblems(password.value, password2.value))
const canSubmit = computed(() => {
  if (busy.value || noToken.value || !username.value.trim() || !password.value) return false
  if (bootstrap.value) return !!token.value.trim() && bootProblems.value.length === 0
  return true
})

// 错误提示是服务端按当时语言返回的，换语言后清掉
watch(() => prefs.lang, () => { error.value = '' })

async function loadStatus(): Promise<void> {
  loadError.value = ''
  try {
    status.value = await api<AuthStatus>('/auth/status')
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
}
onMounted(loadStatus)

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  error.value = ''
  locked.value = false
  busy.value = true
  try {
    const path = bootstrap.value ? '/auth/bootstrap' : '/auth/login'
    const body = bootstrap.value
      ? { token: token.value.trim(), username: username.value.trim(), password: password.value }
      : { username: username.value.trim(), password: password.value }
    const r = await api<LoginResult>(path, { method: 'POST', body: JSON.stringify(body) })
    auth.set(r.user, r.expires_at)
    password.value = password2.value = token.value = ''
    await router.replace(safeNext(route.query.next))
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    locked.value = e instanceof ApiError && e.status === 429
    if (e instanceof ApiError && e.status === 409) await loadStatus() // 别人刚创建了管理员
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="bare login-page">
    <BareTopbar />
    <div class="login-wrap">
      <form :class="['login-card', { wide: bootstrap }]" novalidate data-testid="login-form" @submit.prevent="submit">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span class="login-logo" v-html="LOGO_SVG" />
        <template v-if="bootstrap">
          <h1>{{ $t('login.bootTitle') }}</h1>
          <p v-if="!noToken" class="muted" data-testid="login-boot-hint">{{ $t('login.bootHint', { file: configFile }) }}</p>
        </template>
        <template v-else>
          <h1>{{ $t('login.title') }}</h1>
          <p class="muted">{{ $t('login.hint') }}</p>
        </template>

        <div v-if="loadError" class="notice err" role="alert">
          <Icon name="err" /><div class="grow small">{{ loadError }}</div>
          <button type="button" class="btn btn-sm" @click="loadStatus"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
        </div>
        <div v-if="expired && !bootstrap" class="notice info" data-testid="login-expired">
          <Icon name="clock" /><div class="grow small">{{ $t('login.expired', { h: status?.session_hours ?? 12 }) }}</div>
        </div>
        <div v-if="locked" class="notice warn" role="alert" data-testid="login-locked">
          <Icon name="lock" /><div class="grow small"><b>{{ $t('login.lockedTitle') }}</b><br />{{ error }}</div>
        </div>

        <div v-if="noToken" class="notoken" data-testid="login-no-token">
          <div class="notice warn"><Icon name="warn" /><div class="grow small">{{ $t('login.noTokenHint') }}</div></div>
          <ol class="ways">
            <li>{{ $t('login.noTokenCli') }}<code class="mono cmd" data-testid="login-cli">{{ CLI_ADD }}</code><span class="hint">{{ $t('login.noTokenCliNote') }}</span></li>
            <li>{{ $t('login.noTokenSet') }}<code class="mono cmd path" data-testid="login-config-file">{{ configFile }}</code><span class="hint">{{ $t('login.noTokenSetNote') }}</span></li>
          </ol>
          <button type="button" class="btn go" data-testid="login-refresh" @click="loadStatus"><Icon name="refresh" small />{{ $t('login.refresh') }}</button>
        </div>
        <template v-else>
        <div v-if="bootstrap" class="field">
          <label for="login-token">{{ $t('login.token') }}</label>
          <input id="login-token" v-model="token" type="password" class="input mono" autocomplete="off" spellcheck="false" data-testid="login-token" @input="error = ''" />
        </div>
        <div v-if="bootstrap" class="sep" />

        <div class="field">
          <label for="login-user">{{ bootstrap ? $t('login.adminName') : $t('login.username') }}</label>
          <input id="login-user" v-model="username" class="input" autocomplete="username" spellcheck="false" autofocus
            data-testid="login-username" @input="error = ''" />
          <span v-if="bootstrap" class="hint">{{ $t('account.nameHint') }}</span>
        </div>
        <div class="field">
          <label for="login-password">{{ $t('login.password') }}</label>
          <div class="tk">
            <input id="login-password" v-model="password" :type="reveal ? 'text' : 'password'" :class="['input', { 'is-error': error && !locked }]"
              :autocomplete="bootstrap ? 'new-password' : 'current-password'" spellcheck="false" :aria-invalid="!!error && !locked"
              data-testid="login-password" @input="error = ''" />
            <button type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal"
              :title="$t(reveal ? 'login.hide' : 'login.show')" :aria-label="$t(reveal ? 'login.hide' : 'login.show')" @click="reveal = !reveal">
              <Icon name="eye" small />
            </button>
          </div>
          <span v-if="error && !locked" class="err" role="alert" data-testid="login-error"><Icon name="err" small />{{ error }}</span>
        </div>
        <div v-if="bootstrap" class="field">
          <label for="login-password2">{{ $t('account.repeat') }}</label>
          <input id="login-password2" v-model="password2" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" data-testid="login-password2" />
          <span v-for="p in bootProblems" :key="p" class="hint">{{ $t(`account.rule.${p}`) }}</span>
        </div>

        <button type="submit" class="btn btn-primary go" :disabled="!canSubmit || locked" data-testid="login">
          {{ busy ? $t('login.checking') : bootstrap ? $t('login.bootSubmit') : $t('login.submit') }}
        </button>
        <div class="foot">{{ bootstrap ? $t('login.bootFoot') : $t('login.foot') }}</div>
        </template>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page { display: flex; flex-direction: column; background: var(--bg); }
.login-wrap { flex: 1; display: flex; align-items: center; justify-content: center; padding: 28px 16px 64px; }
.login-card {
  width: min(400px, 100%); background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 28px 28px 24px; display: flex; flex-direction: column; gap: 14px;
}
.login-card.wide { width: min(460px, 100%); }
.login-logo { display: contents; }
.login-logo :deep(svg) { width: 44px; height: 44px; }
.login-card h1 { font-size: 20px; margin: 2px 0 0; }
.login-card > p { margin: -6px 0 2px; font-size: 13px; overflow-wrap: anywhere; }
.tk { position: relative; display: flex; align-items: center; }
.tk .input { width: 100%; padding-right: 34px; }
.tk .reveal { position: absolute; right: 3px; }
.tk .reveal[aria-pressed="true"] { color: var(--teal-ink); }
.sep { border-top: 1px solid var(--line); margin: 2px 0; }
.go { width: 100%; justify-content: center; height: 34px; }
.notoken { display: flex; flex-direction: column; gap: 12px; }
.ways { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; font-size: 13px; color: var(--ink-2); }
.ways li { display: flex; flex-direction: column; gap: 4px; }
.cmd {
  display: block; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg);
  color: var(--ink); font-size: 12px; overflow-wrap: anywhere; user-select: all;
}
.foot { font-size: 12px; color: var(--ink-3); text-align: center; overflow-wrap: anywhere; }
@media (max-width: 520px) { .login-card { padding: 22px 18px 20px; } }
</style>
