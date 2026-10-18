<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorText, post } from '@/api'
import { useAuth } from '@/stores/auth'
import Icon from '@/components/Icon.vue'
import { passwordProblems } from './account/account'

const auth = useAuth()
const current = ref('')
const next = ref('')
const repeat = ref('')
const reveal = ref(false)
const busy = ref(false)
const error = ref('')
const done = ref<number | null>(null)

const problems = computed(() => (next.value || repeat.value ? passwordProblems(next.value, repeat.value, current.value) : []))
const canSubmit = computed(() => !busy.value && !!current.value && !!next.value && problems.value.length === 0)

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  busy.value = true
  error.value = ''
  done.value = null
  try {
    const r = await post<{ sessions_closed: number }>('/auth/password', { old_password: current.value, new_password: next.value })
    done.value = r.sessions_closed
    current.value = next.value = repeat.value = ''
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('password.title') }}</h1>
          <p class="ph-sub">{{ $t('password.sub') }}</p>
        </div>
      </div>
      <section class="panel pw-panel">
        <div class="panel-b">
          <div v-if="auth.me?.via === 'token'" class="notice info"><Icon name="info" /><div class="grow small">{{ $t('password.tokenOnly') }}</div></div>
          <form v-else class="form-stack" novalidate data-testid="password-form" @submit.prevent="submit">
            <div v-if="done !== null" class="notice ok" role="status" data-testid="password-done"><Icon name="ok" /><div class="grow small">{{ $t('password.done', { n: done }) }}</div></div>
            <div class="field">
              <label for="pw-cur">{{ $t('password.current') }}</label>
              <div class="pw">
                <input id="pw-cur" v-model="current" :type="reveal ? 'text' : 'password'" :class="['input', { 'is-error': error }]" autocomplete="current-password"
                  data-testid="password-current" @input="error = ''" />
                <button type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal" :aria-label="$t(reveal ? 'login.hide' : 'login.show')" @click="reveal = !reveal"><Icon name="eye" small /></button>
              </div>
              <span v-if="error" class="err" role="alert" data-testid="password-error"><Icon name="err" small />{{ error }}</span>
            </div>
            <div class="field">
              <label for="pw-new">{{ $t('password.new') }}</label>
              <input id="pw-new" v-model="next" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" data-testid="password-new" />
            </div>
            <div class="field">
              <label for="pw-rep">{{ $t('password.repeat') }}</label>
              <input id="pw-rep" v-model="repeat" :type="reveal ? 'text' : 'password'" class="input" autocomplete="new-password" data-testid="password-repeat" />
              <div class="rules">
                <span v-for="p in problems" :key="p" class="bad"><Icon name="x" small />{{ $t(`account.rule.${p}`) }}</span>
              </div>
            </div>
            <div class="row">
              <button type="submit" class="btn btn-primary" :disabled="!canSubmit" data-testid="password-submit"><Icon name="key" small />{{ $t('password.submit') }}</button>
            </div>
          </form>
        </div>
      </section>
      <p class="small faint mt12">{{ $t('password.forgot') }}</p>
    </div>
  </main>
</template>

<style scoped>
.pw-panel { max-width: 520px; }
.form-stack { display: flex; flex-direction: column; gap: 14px; }
.pw { position: relative; display: flex; align-items: center; }
.pw .input { width: 100%; padding-right: 34px; }
.pw .reveal { position: absolute; right: 3px; }
.pw .reveal[aria-pressed="true"] { color: var(--teal-ink); }
.rules { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.rules .bad { display: inline-flex; align-items: center; gap: 6px; color: var(--red-ink); }
</style>
