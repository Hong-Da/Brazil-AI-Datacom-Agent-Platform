<script setup lang="ts">
/**
 * 转交项目（POST /projects/{p}/transfer，属主与管理员）。普通用户没有账号列表接口，新属主用文本输入；
 * 管理员从 GET /users 取启用中的账号做候选。
 */
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { ApiError, errorText, get, post } from '@/api'
import { validSlug } from './logic'
import { useAuth } from '@/stores/auth'

const props = defineProps<{ project: { slug: string; ref: string; name: string; owner: string | null } }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'transferred', r: { project: string; owner: string; kept_as: string | null; rule_set_copied: unknown; full_ref: string }): void }>()
const auth = useAuth()

const to = ref('')
const keep = ref<'edit' | 'read' | ''>('edit')
const busy = ref(false)
const error = ref('')
const accounts = ref<string[]>([])
/** 新属主已有同名标识（409，data.suggested）：转交时改用的新标识 */
const taken = ref<{ owner: string; slug: string } | null>(null)
const newSlug = ref('')
const iAmOwner = computed(() => auth.me?.username === props.project.owner)

onMounted(async () => {
  if (!auth.isAdmin) return
  try {
    const users = (await get<{ users: { username: string; disabled: boolean }[] }>('/users')).users
    accounts.value = users.filter((u) => !u.disabled && u.username !== props.project.owner).map((u) => u.username)
  } catch { /* 候选取不到时手动输入 */ }
})

async function ok(): Promise<void> {
  if (!to.value.trim() || busy.value || (taken.value && !validSlug(newSlug.value.trim()))) return
  busy.value = true
  error.value = ''
  try {
    const r = await post<{ project: string; owner: string; kept_as: string | null; rule_set_copied: unknown; full_ref: string }>(
      `/projects/${encodeURIComponent(props.project.ref)}/transfer`,
      { to: to.value.trim(), keep_as: keep.value || null, ...(taken.value ? { slug: newSlug.value.trim() } : {}) },
    )
    emit('transferred', r)
  } catch (e) {
    const sug = e instanceof ApiError && e.status === 409 ? (e.data as { suggested?: string } | null)?.suggested : undefined
    if (sug && !taken.value) {
      taken.value = { owner: to.value.trim(), slug: props.project.slug }
      newSlug.value = sug
    } else error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="project-transfer-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" style="width: min(520px, 100%)" role="dialog" aria-modal="true" aria-labelledby="trT">
      <div class="modal-h">
        <h2 id="trT">{{ $t('projects.dlg.trTitle') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b stack-12">
        <p class="muted">{{ $t('projects.dlg.trWhat', { p: project.name }) }}</p>
        <div class="field">
          <label for="trTo">{{ $t('projects.dlg.trTo') }}</label>
          <input id="trTo" v-model="to" class="input" :list="accounts.length ? 'trAcc' : undefined" :placeholder="$t('projects.dlg.trToPh')" autocomplete="off" data-testid="tr-to" @keydown.enter="ok">
          <datalist v-if="accounts.length" id="trAcc"><option v-for="a in accounts" :key="a" :value="a" /></datalist>
          <div class="hint">{{ $t('projects.dlg.trHint') }}</div>
        </div>
        <div v-if="iAmOwner || auth.isAdmin" class="field">
          <label for="trKeep">{{ $t('projects.dlg.trKeep') }}</label>
          <select id="trKeep" v-model="keep" class="select" data-testid="tr-keep">
            <option value="edit">{{ $t('projects.dlg.trKeepEdit') }}</option>
            <option value="read">{{ $t('projects.dlg.trKeepRead') }}</option>
            <option value="">{{ $t('projects.dlg.trKeepNone') }}</option>
          </select>
        </div>
        <div class="notice warn"><Icon name="warn" /><div>{{ $t('projects.dlg.trWarn') }}</div></div>
        <div v-if="taken" class="field" data-testid="tr-taken">
          <div class="notice warn"><Icon name="warn" /><div>{{ $t('projects.dlg.transferTaken', { owner: taken.owner, s: taken.slug }) }}</div></div>
          <label for="trSlug">{{ $t('projects.dlg.transferSlug') }}</label>
          <input id="trSlug" v-model="newSlug" :class="['input mono', { 'is-error': !validSlug(newSlug.trim()) }]" maxlength="64" data-testid="tr-slug" @keydown.enter="ok">
        </div>
        <div v-if="error" class="notice err" data-testid="tr-error"><Icon name="err" /><div>{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="busy || !to.trim()" data-testid="tr-ok" @click="ok"><Icon name="transfer" small />{{ busy ? $t('projects.busy') : $t('projects.dlg.trOk') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stack-12 { display: flex; flex-direction: column; gap: 12px; }
</style>
