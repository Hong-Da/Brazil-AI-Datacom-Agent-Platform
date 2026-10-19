<script setup lang="ts">
/** 个人 API（REQ-040 追加，/me/ai/personal）：编辑自己的 AI 接口（Key 只显示已设置 / 清除）、测试、删除；
 *  可在保存时同时改用个人 API。管理员也看不到这里的内容。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, errorText, get, post, put } from '@/api'
import Icon from '@/components/Icon.vue'
import { useAuth } from '@/stores/auth'
import { useStatus } from '@/stores/status'
import ConnFields from './ai/ConnFields.vue'
import { buildPayload, emptyForm, formFrom, payloadIsEmpty, validateConn, type ConnForm, type MyAi, type TestResult } from './ai/logic'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`my-ai.${k}`, p ?? {})
const A = (k: string, p?: Record<string, unknown>) => t(`ai-settings.${k}`, p ?? {})
const auth = useAuth()
const status = useStatus()
const viaToken = computed(() => auth.me?.via === 'token')

const my = ref<MyAi | null>(null)
const loading = ref(true)
const loadErr = ref('')
const form = reactive<ConnForm>(emptyForm())
const orig = ref<ConnForm | null>(null)
const keyInput = ref('')
const clearKey = ref(false)
const showProblems = ref(false)
const useIt = ref(true)

function apply(m: MyAi): void {
  my.value = m
  const f = m.personal ? formFrom(m.personal) : emptyForm()
  Object.assign(form, f)
  orig.value = m.personal ? { ...f } : null
  keyInput.value = ''
  clearKey.value = false
  showProblems.value = false
  useIt.value = m.choice !== 'personal'
}
async function load(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    apply(await get<MyAi>('/me/ai'))
  } catch (e) {
    loadErr.value = errorText(e)
  } finally {
    loading.value = false
  }
}

const keySet = computed(() => !!my.value?.personal?.api_key_set)
const body = computed(() => buildPayload(orig.value, form, keyInput.value, clearKey.value, keySet.value, false, false))
const dirty = computed(() => (orig.value ? !payloadIsEmpty(body.value) : !!(form.base_url.trim() || form.model.trim() || keyInput.value.trim())))
const problems = computed(() => (showProblems.value ? validateConn(form, keySet.value, keyInput.value, clearKey.value, false) : {}))
const isChosen = computed(() => my.value?.choice === 'personal')

const saving = ref(false)
const saveErr = ref('')
const savedMsg = ref(false)
async function save(): Promise<void> {
  showProblems.value = true
  saveErr.value = ''
  savedMsg.value = false
  if (Object.keys(validateConn(form, keySet.value, keyInput.value, clearKey.value, false)).length) return
  const req: Record<string, unknown> = {}
  if (dirty.value) req.personal = body.value
  if (useIt.value && !isChosen.value) req.choice = 'personal'
  if (!Object.keys(req).length) return
  saving.value = true
  try {
    apply(await put<MyAi>('/me/ai', req))
    savedMsg.value = true
    testRes.value = null
    void status.refresh()
  } catch (e) {
    const d = e instanceof ApiError ? (e.data as { error?: string } | null) : null
    saveErr.value = d?.error ? `${errorText(e)}：${d.error}` : errorText(e)
  } finally {
    saving.value = false
  }
}
function discard(): void { if (my.value) apply(my.value); saveErr.value = '' }

async function remove(): Promise<void> {
  if (!window.confirm(T('removeConfirm'))) return
  saveErr.value = ''
  try {
    apply(await put<MyAi>('/me/ai', { remove_personal: true }))
    savedMsg.value = false
    void status.refresh()
  } catch (e) {
    saveErr.value = errorText(e)
  }
}

const testing = ref(false)
const testRes = ref<{ ok: boolean; text: string } | null>(null)
async function test(): Promise<void> {
  testing.value = true
  testRes.value = null
  const t0 = performance.now()
  try {
    const r = await post<TestResult>('/me/ai/test', { target: 'personal' })
    testRes.value = { ok: true, text: A('testOk', { m: r.model, ms: Math.round(performance.now() - t0), i: r.tokens_in, o: r.tokens_out }) }
  } catch (e) {
    testRes.value = { ok: false, text: A('testFail', { e: errorText(e) }) }
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><router-link :to="{ name: 'my-ai' }" data-testid="my-ai-p-back">{{ T('backMy') }}</router-link><span class="sep">/</span><span>{{ T('personalT') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ T('personalT') }} <span class="tag" :class="{ pass: my?.personal }">{{ my?.personal ? T('personalTagSet') : T('personalTagNone') }}</span></h1>
          <p class="ph-sub">{{ T('personalPageSub') }}</p>
        </div>
        <div v-if="my && !viaToken" class="ph-actions">
          <span v-if="dirty" class="small" style="color: var(--amber-ink)" data-testid="my-ai-p-dirty">{{ T('unsaved') }}</span>
          <span v-else-if="savedMsg" class="small" style="color: var(--teal-ink)" data-testid="my-ai-p-saved">{{ T('saved') }}</span>
          <button class="btn" :disabled="!dirty || saving" data-testid="my-ai-p-discard" @click="discard">{{ T('discard') }}</button>
          <button class="btn btn-primary" :disabled="(!dirty && !(useIt && !isChosen && my.personal)) || saving" data-testid="my-ai-p-save" @click="save">{{ $t('c.save') }}</button>
        </div>
      </div>

      <div v-if="loading" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
      <div v-else-if="loadErr || !my" class="panel"><div class="empty"><p>{{ loadErr }}</p><button class="btn" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div></div>
      <div v-else-if="viaToken" class="notice info"><Icon name="key" /><div class="grow small">{{ T('tokenNote') }}</div></div>

      <div v-else class="grid g-side collapse">
        <section class="panel" data-testid="my-ai-personal">
          <div class="panel-b">
            <p class="small faint" style="margin: 0 0 12px">{{ T('personalNote') }}</p>
            <ConnFields v-model:key-input="keyInput" v-model:clear-key="clearKey" :form="form" :key-set="keySet" :problems="problems" tid="my-ai-p" />
            <label v-if="!isChosen" class="check mt16"><input v-model="useIt" type="checkbox" data-testid="my-ai-p-use"><span>{{ T('useP') }}</span></label>
            <div v-if="saveErr" class="notice err mt12" data-testid="my-ai-p-error"><Icon name="err" /><div class="grow small">{{ saveErr }}</div></div>
          </div>
        </section>
        <div class="stack">
          <section class="panel">
            <div class="panel-h"><h2>{{ A('testT') }}</h2></div>
            <div class="panel-b">
              <button class="btn" :disabled="!my.personal || dirty || testing" data-testid="my-ai-test-personal" @click="test">
                <Icon name="refresh" small />{{ testing ? T('testing') : T('testP') }}
              </button>
              <p v-if="dirty" class="small faint mt8">{{ T('testSaveFirst') }}</p>
              <p v-if="testRes" class="small mt8" :style="{ color: testRes.ok ? 'var(--teal-ink)' : 'var(--red-ink)' }" data-testid="my-ai-test-personal-result">{{ testRes.text }}</p>
            </div>
          </section>
          <section v-if="my.personal" class="panel">
            <div class="panel-b">
              <button class="btn btn-danger" data-testid="my-ai-remove-personal" @click="remove"><Icon name="trash" small />{{ T('removeP') }}</button>
            </div>
          </section>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.ph-text h1 { display: flex; gap: 10px; align-items: center; }
.ph-text h1 .tag { font-size: 12px; font-weight: 500; }
@media (max-width: 1100px) { .g-side.collapse { grid-template-columns: minmax(0, 1fr); } }
</style>
