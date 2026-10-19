<script setup lang="ts">
/** AI 接口设置页（管理员，REQ-040 追加）：/ai/connections/:id 编辑地址、Key、各用途模型、公共使用与启用，测试连接，
 *  看这个接口的用量与最近调用，删除；/ai/connections/new 新建。 */
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError, del, errorText, get, post, put } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import ConnFields from './ai/ConnFields.vue'
import CallsPanel from './ai/CallsPanel.vue'
import UsagePanel from './ai/UsagePanel.vue'
import { buildPayload, emptyForm, formFrom, payloadIsEmpty, validateConn, type Connection, type ConnForm, type TestResult } from './ai/logic'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-settings.${k}`, p ?? {})
const status = useStatus()

const isNew = computed(() => route.params.id === 'new')
const conn = ref<Connection | null>(null)
const loading = ref(false)
const loadErr = ref('')
const notFound = ref(false)
const form = reactive<ConnForm>(emptyForm())
const orig = ref<ConnForm | null>(null)
const keyInput = ref('')
const clearKey = ref(false)
const showProblems = ref(false)

function apply(c: Connection | null): void {
  conn.value = c
  const f = c ? formFrom(c) : emptyForm()
  Object.assign(form, f)
  orig.value = c ? { ...f } : null
  keyInput.value = ''
  clearKey.value = false
  showProblems.value = false
}

async function load(): Promise<void> {
  notFound.value = false
  loadErr.value = ''
  testRes.value = null
  if (isNew.value) { apply(null); return }
  loading.value = true
  try {
    apply(await get<Connection>(`/ai/connections/${encodeURIComponent(String(route.params.id))}`))
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound.value = true
    else loadErr.value = errorText(e)
  } finally {
    loading.value = false
  }
}

const keySet = computed(() => !!conn.value?.api_key_set)
const problems = computed(() => (showProblems.value ? validateConn(form, keySet.value, keyInput.value, clearKey.value) : {}))
const body = computed(() => buildPayload(orig.value, form, keyInput.value, clearKey.value, keySet.value))
const dirty = computed(() => isNew.value || !payloadIsEmpty(body.value))
const saving = ref(false)
const saveErr = ref('')
const savedMsg = ref('')

async function save(): Promise<void> {
  showProblems.value = true
  saveErr.value = ''
  savedMsg.value = ''
  if (Object.keys(validateConn(form, keySet.value, keyInput.value, clearKey.value)).length) return
  if (!isNew.value && payloadIsEmpty(body.value)) return
  saving.value = true
  try {
    if (isNew.value) {
      const c = await post<Connection>('/ai/connections', body.value)
      await router.replace({ name: 'ai-connection', params: { id: String(c.id) } })
      savedMsg.value = T('created', { n: c.name })
    } else if (conn.value) {
      apply(await put<Connection>(`/ai/connections/${conn.value.id}`, body.value))
      savedMsg.value = t('c.saved')
    }
    void status.refresh()
  } catch (e) {
    const d = e instanceof ApiError ? (e.data as { error?: string } | null) : null
    saveErr.value = T('saveErr', { e: d?.error ? `${errorText(e)}：${d.error}` : errorText(e) })
  } finally {
    saving.value = false
  }
}
function discard(): void { apply(conn.value); saveErr.value = '' }

// ---------- 测试 ----------
const testing = ref(false)
const testRes = ref<{ ok: boolean; text: string } | null>(null)
const callsRef = ref<InstanceType<typeof CallsPanel> | null>(null)
const usageRef = ref<InstanceType<typeof UsagePanel> | null>(null)
async function test(): Promise<void> {
  if (!conn.value) return
  testing.value = true
  testRes.value = null
  const t0 = performance.now()
  try {
    const r = await post<TestResult>(`/ai/connections/${conn.value.id}/test`)
    testRes.value = { ok: true, text: T('testOk', { m: r.model, ms: Math.round(performance.now() - t0), i: r.tokens_in, o: r.tokens_out }) }
  } catch (e) {
    testRes.value = { ok: false, text: T('testFail', { e: errorText(e) }) }
  } finally {
    testing.value = false
    void callsRef.value?.load()
    void usageRef.value?.load()
  }
}

// ---------- 删除 ----------
const confirmDel = ref(false)
const delErr = ref('')
async function remove(): Promise<void> {
  if (!conn.value) return
  delErr.value = ''
  try {
    await del(`/ai/connections/${conn.value.id}`)
    void status.refresh()
    await router.push({ name: 'ai-settings' })
  } catch (e) {
    delErr.value = errorText(e)
  }
}

watch(() => route.params.id, () => { if (route.name === 'ai-connection') void load() }, { immediate: true })
const LOGO: Record<string, string> = { anthropic: 'A', openai: 'OA', local: 'L' }
const connId = computed(() => conn.value?.id ?? null)
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><router-link :to="{ name: 'ai-settings' }" data-testid="ai-conn-back">{{ T('back') }}</router-link><span class="sep">/</span><span>{{ isNew ? T('newT') : conn?.name ?? '…' }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1 class="h-conn">
            <span v-if="conn" class="lg" :class="conn.provider">{{ LOGO[conn.provider] ?? '?' }}</span>
            <span>{{ isNew ? T('newT') : conn?.name ?? '…' }}</span>
            <span v-if="conn?.is_default" class="tag t-teal" :title="T('defaultTip')">{{ T('default') }}</span>
            <span v-if="conn" class="tag" :class="conn.enabled ? 'pass' : ''">{{ conn.enabled ? T('statusOn') : T('statusOff') }}</span>
            <span v-if="conn?.public" class="tag t-teal">{{ T('publicOn') }}</span>
          </h1>
          <p class="ph-sub">{{ isNew ? T('newSub') : T('detailSub') }}</p>
        </div>
        <div v-if="!notFound && !loadErr" class="ph-actions">
          <span v-if="dirty && !isNew" class="small" style="color: var(--amber-ink)" data-testid="ai-conn-dirty">{{ T('unsaved') }}</span>
          <span v-else-if="savedMsg" class="small" style="color: var(--teal-ink)" data-testid="ai-conn-saved">{{ savedMsg }}</span>
          <button v-if="!isNew" class="btn" :disabled="!dirty || saving" data-testid="ai-conn-discard" @click="discard">{{ T('discard') }}</button>
          <button class="btn btn-primary" :disabled="!dirty || saving" data-testid="ai-conn-save" @click="save">{{ $t('c.save') }}</button>
        </div>
      </div>

      <div v-if="loading" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
      <div v-else-if="notFound" class="panel" data-testid="ai-conn-missing"><div class="empty"><p>{{ T('notFound') }}</p><router-link class="btn" :to="{ name: 'ai-settings' }">{{ T('back') }}</router-link></div></div>
      <div v-else-if="loadErr" class="panel"><div class="empty"><p>{{ loadErr }}</p><button class="btn" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div></div>

      <div v-else class="grid g-side collapse">
        <div class="stack">
          <section class="panel" data-testid="ai-conn-form">
            <div class="panel-b">
              <ConnFields v-model:key-input="keyInput" v-model:clear-key="clearKey" :form="form" :key-set="keySet" :problems="problems" with-name with-flags tid="ai-conn-f" />
              <div v-if="saveErr" class="notice err mt12" data-testid="ai-conn-save-error"><Icon name="err" /><div class="grow small">{{ saveErr }}</div></div>
            </div>
          </section>
          <template v-if="conn">
            <UsagePanel ref="usageRef" :connection-id="connId" compact />
            <CallsPanel ref="callsRef" :title="T('recentT')" :connection-id="connId" :limit="50" />
          </template>
        </div>
        <div class="stack">
          <section class="panel" data-testid="ai-conn-test-panel">
            <div class="panel-h"><h2>{{ T('testT') }}</h2></div>
            <div class="panel-b">
              <p class="small faint" style="margin: 0 0 10px">{{ isNew ? T('newSub') : T('testHint') }}</p>
              <button class="btn" :disabled="!conn || !conn.enabled || dirty || testing" data-testid="ai-conn-test" @click="test">
                <Icon name="refresh" small />{{ testing ? T('testing') : T('test') }}
              </button>
              <p v-if="conn && dirty" class="small faint mt8">{{ T('testSaveFirst') }}</p>
              <p v-if="testRes" class="small mt8" :style="{ color: testRes.ok ? 'var(--teal-ink)' : 'var(--red-ink)' }" data-testid="ai-conn-test-result">{{ testRes.text }}</p>
            </div>
          </section>
          <section v-if="conn" class="panel">
            <div class="panel-b">
              <dl class="kv">
                <dt>{{ T('chosenByK') }}</dt><dd>{{ conn.chosen_by }}</dd>
                <dt>{{ T('colUsage') }}</dt><dd>{{ T('calls', { n: conn.usage.calls }) }} · {{ (conn.usage.tokens_in + conn.usage.tokens_out).toLocaleString('en-US') }} tokens</dd>
              </dl>
            </div>
          </section>
          <section v-if="conn" class="panel danger" data-testid="ai-conn-danger">
            <div class="panel-h"><h2>{{ T('dangerT') }}</h2></div>
            <div class="panel-b">
              <p class="small" style="margin: 0 0 10px">{{ conn.chosen_by ? T('delUsers', { n: conn.chosen_by }) : T('delNone') }} {{ T('delKeep') }}</p>
              <button v-if="!confirmDel" class="btn btn-danger" data-testid="ai-conn-del" @click="confirmDel = true"><Icon name="trash" small />{{ T('delete') }}</button>
              <div v-else class="row wrap">
                <button class="btn" @click="confirmDel = false">{{ $t('c.cancel') }}</button>
                <button class="btn btn-danger-solid" data-testid="ai-conn-del-ok" @click="remove">{{ T('delete') }}</button>
              </div>
              <div v-if="delErr" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ delErr }}</div></div>
            </div>
          </section>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.h-conn { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.h-conn .tag { font-size: 12px; font-weight: 500; }
.lg { width: 30px; height: 30px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; font: 700 11px var(--font-ui); color: var(--surface); flex: none; }
.lg.anthropic { background: var(--amber-ink); }
.lg.openai { background: var(--blue-ink); }
.lg.local { background: var(--ink-2); }
.danger { border-color: color-mix(in srgb, var(--red) 35%, var(--line)); }
@media (max-width: 1100px) { .g-side.collapse { grid-template-columns: minmax(0, 1fr); } }
</style>
