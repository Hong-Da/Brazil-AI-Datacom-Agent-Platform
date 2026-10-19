<script setup lang="ts">
/** 账号管理里的“自助注册”设置（REQ-039，预览 users.html）：允许注册、需要审核、每个地址每小时次数；写入配置文件 [auth]。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { errorText, get, put } from '@/api'
import Icon from '@/components/Icon.vue'
import { regPatch, validRate, type RegSettings } from '../account/account'

const emit = defineEmits<{ (e: 'saved', s: RegSettings): void }>()
const saved = ref<RegSettings | null>(null)
const draft = reactive<RegSettings>({ registration: false, approval: true, rate_per_hour: 5 })
const loadError = ref('')
const error = ref('')
const busy = ref(false)

const patch = computed(() => (saved.value ? regPatch(saved.value, draft) : {}))
const dirty = computed(() => Object.keys(patch.value).length > 0)
const rateOk = computed(() => validRate(draft.rate_per_hour))

async function load(): Promise<void> {
  loadError.value = ''
  try {
    const s = await get<RegSettings>('/auth/settings')
    saved.value = { registration: s.registration, approval: s.approval, rate_per_hour: s.rate_per_hour }
    Object.assign(draft, saved.value)
  } catch (e) {
    loadError.value = errorText(e)
  }
}
onMounted(load)

function revert(): void { if (saved.value) Object.assign(draft, saved.value) }

async function save(): Promise<void> {
  if (!dirty.value || !rateOk.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const s = await put<RegSettings>('/auth/settings', patch.value)
    saved.value = { registration: s.registration, approval: s.approval, rate_per_hour: s.rate_per_hour }
    Object.assign(draft, saved.value)
    emit('saved', saved.value)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="panel reg-panel" data-testid="reg-panel" aria-labelledby="regTitle">
    <div class="panel-h">
      <h2 id="regTitle">{{ $t('users.reg.title') }}</h2>
      <span v-if="saved?.registration" class="tag t-teal" data-testid="reg-state-open"><Icon name="check" small />{{ $t('users.reg.open') }}</span>
      <span v-else-if="saved" class="tag" data-testid="reg-state-closed"><Icon name="lock" small />{{ $t('users.reg.closed') }}</span>
      <span class="meta">{{ $t('users.reg.meta') }}</span>
    </div>
    <div v-if="loadError" class="panel-b">
      <div class="notice err" role="alert"><Icon name="err" /><div class="grow small">{{ loadError }}</div>
        <button type="button" class="btn btn-sm" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div>
    </div>
    <template v-else-if="saved">
      <div class="reg-grid">
        <div class="reg-item">
          <div class="top"><b>{{ $t('users.reg.allow') }}</b>
            <label class="switch"><input v-model="draft.registration" type="checkbox" :aria-label="$t('users.reg.allow')" data-testid="reg-allow" /><span /></label></div>
          <div class="d">{{ $t('users.reg.allowD') }}</div>
          <div class="key">auth.registration = {{ draft.registration }} · {{ $t('users.reg.defOff') }}</div>
        </div>
        <div :class="['reg-item', { 'is-muted': !draft.registration }]">
          <div class="top"><b>{{ $t('users.reg.approval') }}</b>
            <label class="switch"><input v-model="draft.approval" type="checkbox" :aria-label="$t('users.reg.approval')" data-testid="reg-approval" /><span /></label></div>
          <div class="d">{{ draft.approval ? $t('users.reg.approvalOn') : $t('users.reg.approvalOff') }}</div>
          <div class="key">auth.registration_approval = {{ draft.approval }} · {{ $t('users.reg.defOn') }}</div>
        </div>
        <div :class="['reg-item', { 'is-muted': !draft.registration }]">
          <div class="top"><b>{{ $t('users.reg.rate') }}</b></div>
          <div class="num">
            <input v-model.number="draft.rate_per_hour" type="number" min="1" max="1000" step="1" :class="['input', { 'is-error': !rateOk }]"
              :aria-label="$t('users.reg.rateAria')" data-testid="reg-rate" />
            <span class="unit">{{ $t('users.reg.rateUnit') }}</span>
          </div>
          <span v-if="!rateOk" class="err" role="alert"><Icon name="err" small />{{ $t('users.reg.rateErr') }}</span>
          <div class="d">{{ $t('users.reg.rateD') }}</div>
          <div class="key">auth.registration_rate_per_hour = {{ draft.rate_per_hour }} · {{ $t('users.reg.defRate') }}</div>
        </div>
      </div>
      <div v-if="!draft.registration" class="panel-b closed-note"><div class="notice info"><Icon name="info" /><div class="grow small">{{ $t('users.reg.closedNote') }}</div></div></div>
      <div v-if="error" class="panel-b closed-note"><div class="notice err" role="alert"><Icon name="err" /><div class="grow small">{{ error }}</div></div></div>
      <div class="panel-f">
        <span class="grow small">
          <span v-if="dirty" class="dirty"><Icon name="warn" small />{{ $t('users.reg.dirty') }}</span>
          <span v-else class="faint">{{ $t('users.reg.wizard') }}</span>
        </span>
        <button class="btn btn-sm" type="button" :disabled="!dirty || busy" data-testid="reg-revert" @click="revert">{{ $t('users.reg.revert') }}</button>
        <button class="btn btn-sm btn-primary" type="button" :disabled="!dirty || !rateOk || busy" data-testid="reg-save" @click="save">{{ $t('c.save') }}</button>
      </div>
    </template>
    <div v-else class="empty">{{ $t('c.loading') }}</div>
  </section>
</template>

<style scoped>
.reg-panel { margin-bottom: 12px; }
.reg-panel .panel-h .tag { flex: none; }
.reg-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.reg-item { padding: 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.reg-item:first-child { border-left: 0; }
.reg-item .top { display: flex; align-items: center; gap: 10px; }
.reg-item .top b { font-size: 13px; }
.reg-item .top .switch { margin-left: auto; }
.reg-item .d { font-size: 12px; color: var(--ink-2); }
.reg-item .key { font: 11px var(--font-mono); color: var(--ink-3); overflow-wrap: anywhere; }
.reg-item.is-muted .top b, .reg-item.is-muted .d { color: var(--ink-3); }
.reg-item .num { display: flex; align-items: center; gap: 8px; }
.reg-item .num .input { width: 90px; }
.reg-item .num .unit { font-size: 12px; color: var(--ink-2); }
.reg-item .err { font-size: 12px; color: var(--red-ink); display: flex; gap: 5px; align-items: center; }
.closed-note { padding-top: 0; }
.panel-f { display: flex; align-items: center; gap: 8px; }
.panel-f .grow { flex: 1; min-width: 0; }
.dirty { color: var(--amber-ink); display: inline-flex; gap: 5px; align-items: center; }
@media (max-width: 900px) { .reg-grid { grid-template-columns: 1fr; } .reg-item { border-left: 0; border-top: 1px solid var(--line); } .reg-item:first-child { border-top: 0; } }
</style>
