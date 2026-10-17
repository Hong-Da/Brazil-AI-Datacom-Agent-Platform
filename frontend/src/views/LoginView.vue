<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api'
import { usePrefs } from '@/stores/prefs'
import LangSwitch from '@/layouts/LangSwitch.vue'
import ThemeSwitch from '@/layouts/ThemeSwitch.vue'

const prefs = usePrefs()
const router = useRouter()
const route = useRoute()
const value = ref('')
const error = ref('')

async function submit(): Promise<void> {
  error.value = ''
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
  }
}
</script>

<template>
  <div class="center">
    <el-card class="card">
      <div class="head"><img src="/favicon.svg" width="40" height="40" alt="" /><h2>{{ $t('login.title') }}</h2></div>
      <p class="dim">{{ $t('login.hint') }}</p>
      <el-input v-model="value" type="password" show-password :placeholder="$t('login.placeholder')" data-testid="token" @keyup.enter="submit" />
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="gap" />
      <el-button type="primary" class="gap" :disabled="!value" data-testid="login" @click="submit">{{ $t('login.submit') }}</el-button>
      <div class="switches"><LangSwitch /><ThemeSwitch /></div>
    </el-card>
  </div>
</template>

<style scoped>
.center { display: grid; place-items: center; min-height: 100%; padding: 16px; }
.card { width: min(440px, 100%); }
.head { display: flex; align-items: center; gap: 10px; }
.head h2 { margin: 0; font-size: 20px; }
.dim { color: var(--lm-text-dim); }
.gap { margin-top: 12px; }
.switches { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
</style>
