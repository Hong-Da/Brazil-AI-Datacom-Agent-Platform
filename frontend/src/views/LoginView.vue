<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api'
import { usePrefs } from '@/stores/prefs'
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import BareTopbar from '@/components/wizard-bare-topbar.vue'

const prefs = usePrefs()
const router = useRouter()
const route = useRoute()
const value = ref('')
const error = ref('')
const checking = ref(false)
const reveal = ref(false)
// 错误提示是服务端按当时语言返回的，换语言后清掉
watch(() => prefs.lang, () => { error.value = '' })

async function submit(): Promise<void> {
  if (!value.value.trim() || checking.value) return
  error.value = ''
  checking.value = true
  prefs.token = value.value.trim()
  try {
    localStorage.setItem('lmesh-token', prefs.token)
  } catch {
    /* 浏览器存储不可用时，本次会话内仍可使用 */
  }
  try {
    await api('/config')
    await router.replace(String(route.query.next || '/'))
  } catch (e) {
    prefs.token = ''
    error.value = e instanceof ApiError ? e.message : String(e)
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <div class="bare login-page">
    <BareTopbar />
    <div class="login-wrap">
      <form class="login-card" novalidate @submit.prevent="submit">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span class="login-logo" v-html="LOGO_SVG" />
        <h1>{{ $t('login.title') }}</h1>
        <p class="muted">{{ $t('login.hint') }}</p>
        <div class="field">
          <label for="login-token">{{ $t('login.label') }}</label>
          <div class="tk">
            <input id="login-token" v-model="value" :type="reveal ? 'text' : 'password'" :class="['input', 'mono', { 'is-error': error }]"
              :placeholder="$t('login.placeholder')" autocomplete="current-password" spellcheck="false" autofocus
              :aria-invalid="!!error" data-testid="token" @input="error = ''" />
            <button type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal"
              :title="$t(reveal ? 'login.hide' : 'login.show')" :aria-label="$t(reveal ? 'login.hide' : 'login.show')" @click="reveal = !reveal">
              <Icon name="eye" small />
            </button>
          </div>
          <span v-if="error" class="err" role="alert" data-testid="login-error"><Icon name="err" small />{{ error }}</span>
          <span v-else class="hint">{{ $t('login.remember') }}</span>
        </div>
        <button type="submit" class="btn btn-primary go" :disabled="!value.trim() || checking" data-testid="login">
          {{ checking ? $t('login.checking') : $t('login.submit') }}
        </button>
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
.login-logo :deep(svg) { width: 48px; height: 48px; }
.login-card h1 { font-size: 20px; margin: 2px 0 0; }
.login-card > p { margin: -6px 0 4px; font-size: 13px; overflow-wrap: anywhere; }
.tk { position: relative; display: flex; align-items: center; }
.tk .input { width: 100%; padding-right: 34px; }
.tk .reveal { position: absolute; right: 3px; }
.tk .reveal[aria-pressed="true"] { color: var(--teal-ink); }
.go { width: 100%; justify-content: center; height: 34px; }
@media (max-width: 520px) { .login-card { padding: 22px 18px 20px; } }
</style>
