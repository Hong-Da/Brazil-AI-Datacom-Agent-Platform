<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, errorText, get, post, put } from '@/api'
import Icon from '@/components/Icon.vue'
import { useStatus } from '@/stores/status'
import {
  LIMITS, PROVIDERS, buildPayload, effectiveModel, envName, fmtTokens, formFrom, isEnv, monthStart, needsBaseUrl,
  payloadIsEmpty, usageByTask, usesKey, validateAi, type AiCall, type AiForm, type AiSettings, type AiStatus, type Provider,
} from './ai/logic'
import { fmtTime } from './ingest/logic'

const { t } = useI18n()
const status = useStatus()

const settings = ref<AiSettings | null>(null)
const aiStatus = ref<AiStatus | null>(null)
const form = reactive<AiForm>({ provider: '', base_url: '', model: '', model_extract: '', model_merge: '', timeout: 60, max_tokens: 4096 })
const keyInput = ref('')
const clearKey = ref(false)
const loading = ref(true)
const loadErr = ref('')

async function load(): Promise<void> {
  loading.value = true
  loadErr.value = ''
  try {
    const [s, st] = await Promise.all([get<AiSettings>('/ai/settings'), get<AiStatus>('/ai/status')])
    apply(s)
    aiStatus.value = st
    void loadCalls()
  } catch (e) {
    loadErr.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function apply(s: AiSettings): void {
  settings.value = s
  Object.assign(form, formFrom(s))
  keyInput.value = ''
  clearKey.value = false
}

const env = (k: string) => isEnv(settings.value?.sources, k)
const anyEnv = computed(() => Object.values(settings.value?.sources ?? {}).includes('env'))
const configured = computed(() => !!aiStatus.value?.configured)
const keySet = computed(() => !!settings.value?.api_key_set)

// ---------- 保存 ----------
const problems = computed(() => validateAi(form, keySet.value, keyInput.value, clearKey.value))
const showProblems = ref(false)
const payload = computed(() => (settings.value ? buildPayload(settings.value, form, keyInput.value, clearKey.value) : null))
const dirty = computed(() => !!payload.value && !payloadIsEmpty(payload.value))
const saving = ref(false)
const saveErr = ref('')
const savedMsg = ref(false)

function errOf(k: keyof typeof problems.value): string {
  const p = problems.value[k]
  if (!showProblems.value || !p) return ''
  if (p === 'errRange') { const [lo, hi] = LIMITS[k as 'timeout' | 'max_tokens']; return t('ai-settings.errRange', { lo, hi }) }
  return t(`ai-settings.${p}`)
}

async function save(): Promise<void> {
  showProblems.value = true
  saveErr.value = ''
  savedMsg.value = false
  if (Object.keys(problems.value).length || !payload.value || !dirty.value) return
  saving.value = true
  try {
    apply(await put<AiSettings>('/ai/settings', payload.value))
    aiStatus.value = await get<AiStatus>('/ai/status')
    showProblems.value = false
    savedMsg.value = true
    testRes.value = null
    testErr.value = ''
    void status.refresh()
  } catch (e) {
    const d = e instanceof ApiError ? (e.data as { error?: string } | null) : null
    saveErr.value = d?.error ? `${errorText(e)}：${d.error}` : errorText(e)
  } finally {
    saving.value = false
  }
}

function discard(): void {
  if (settings.value) apply(settings.value)
  showProblems.value = false
  saveErr.value = ''
}

function pickProvider(p: Provider): void {
  if (!env('provider')) form.provider = p
}

// ---------- 测试连接 ----------
interface TestResult { model: string; reply: string; tokens_in: number; tokens_out: number }
const testing = ref(false)
const testRes = ref<(TestResult & { ms: number }) | null>(null)
const testErr = ref('')

async function test(): Promise<void> {
  testing.value = true
  testRes.value = null
  testErr.value = ''
  const t0 = performance.now()
  try {
    const r = await post<TestResult>('/ai/test')
    testRes.value = { ...r, ms: Math.round(performance.now() - t0) }
  } catch (e) {
    testErr.value = errorText(e)
  } finally {
    testing.value = false
    void loadCalls()
  }
}

// ---------- 调用记录 ----------
const calls = ref<AiCall[]>([])
const callsErr = ref('')
const callsLoading = ref(false)
const taskFilter = ref('')

async function loadCalls(): Promise<void> {
  callsLoading.value = true
  callsErr.value = ''
  try {
    calls.value = (await get<{ calls: AiCall[] }>('/ai/calls?limit=1000')).calls
  } catch (e) {
    callsErr.value = errorText(e)
  } finally {
    callsLoading.value = false
  }
}

const taskNames = computed(() => [...new Set(calls.value.map((c) => c.task))].sort())
const shownCalls = computed(() => calls.value.filter((c) => !taskFilter.value || c.task === taskFilter.value).slice(0, 200))
const usage = computed(() => usageByTask(calls.value, monthStart()))
const usageTotal = computed(() => usage.value.reduce((s, u) => s + u.tokensIn + u.tokensOut, 0))
const usageMax = computed(() => Math.max(1, ...usage.value.map((u) => u.tokensIn + u.tokensOut)))
const taskLabel = (k: string) => (['extract', 'merge', 'test'].includes(k) ? t(`ai-settings.task_${k}`) : k)

const LOGO: Record<string, string> = { anthropic: 'A', openai: 'OA', local: 'L' }

onMounted(load)
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.ai-settings') }}</h1>
          <p class="ph-sub">{{ $t('ai-settings.sub') }}</p>
        </div>
        <div v-if="settings" class="ph-actions">
          <span v-if="dirty" class="small" style="color: var(--amber-ink)" data-testid="ai-dirty">{{ $t('ai-settings.unsaved') }}</span>
          <span v-else-if="savedMsg" class="small" style="color: var(--teal-ink)">{{ $t('c.saved') }}</span>
          <button class="btn" :disabled="!dirty || saving" data-testid="ai-discard" @click="discard">{{ $t('ai-settings.discard') }}</button>
          <button class="btn btn-primary" :disabled="!dirty || saving" data-testid="ai-save" @click="save">{{ $t('c.save') }}</button>
        </div>
      </div>

      <div v-if="loading" class="panel"><div class="empty">{{ $t('c.loading') }}</div></div>
      <div v-else-if="loadErr || !settings" class="panel">
        <div class="empty">
          <p>{{ loadErr }}</p>
          <button class="btn" data-testid="ai-retry" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
        </div>
      </div>

      <div v-else class="grid g-side collapse">
        <div class="stack">
          <!-- 降级模式说明 -->
          <div v-if="!configured" class="panel" data-testid="ai-degraded">
            <div class="panel-h"><h2>{{ $t('ai-settings.offT') }}</h2><span class="tag">{{ $t('ai-settings.degraded') }}</span></div>
            <div class="off-hero">
              <div class="yes">
                <h3><Icon name="ok" small style="color: var(--teal-ink)" /><span>{{ $t('ai-settings.worksT') }}</span></h3>
                <ul>
                  <li v-for="i in 4" :key="i"><Icon name="check" small /><span>{{ $t(`ai-settings.works${i}`) }}</span></li>
                </ul>
              </div>
              <div class="no">
                <h3><Icon name="eyeOff" small style="color: var(--ink-3)" /><span>{{ $t('ai-settings.hiddenT') }}</span></h3>
                <ul>
                  <li><Icon name="minus" small /><span>{{ $t('ai-settings.hidden1') }}</span></li>
                </ul>
              </div>
            </div>
          </div>

          <!-- 接口 -->
          <div class="panel" data-testid="ai-interface">
            <div class="panel-h">
              <h2>{{ $t('ai-settings.ifT') }}</h2>
              <span v-if="configured" class="tag pass"><Icon name="check" small />{{ $t('ai-settings.configured') }}</span>
              <span v-else class="tag">{{ $t('ai-settings.notConfigured') }}</span>
            </div>
            <div class="panel-b">
              <span class="field-label">{{ $t('ai-settings.type') }}</span>
              <div class="types mt8" data-testid="ai-provider">
                <label v-for="p in PROVIDERS" :key="p" class="radio-card" :class="{ ro: env('provider') }">
                  <span class="head">
                    <input type="radio" name="provider" :checked="form.provider === p" :disabled="env('provider')" @change="pickProvider(p)">
                    <span class="lg" :class="p">{{ LOGO[p] }}</span>
                    <span class="rc-t">{{ $t(`ai-settings.p_${p}`) }}</span>
                  </span>
                  <span class="rc-d">{{ $t(`ai-settings.p_${p}_d`) }}</span>
                </label>
                <label class="radio-card" :class="{ ro: env('provider') }">
                  <span class="head">
                    <input type="radio" name="provider" :checked="form.provider === ''" :disabled="env('provider')" @change="pickProvider('')">
                    <span class="lg none"><Icon name="minus" small /></span>
                    <span class="rc-t">{{ $t('ai-settings.p_none') }}</span>
                  </span>
                  <span class="rc-d">{{ $t('ai-settings.p_none_d') }}</span>
                </label>
              </div>
              <span v-if="env('provider')" class="hint envhint"><Icon name="lock" small />{{ $t('ai-settings.envSet', { v: envName('provider') }) }}</span>

              <div v-if="form.provider" class="form-grid mt16">
                <div class="field span2">
                  <label for="ai-url">{{ $t('ai-settings.baseUrl') }}</label>
                  <input
                    id="ai-url" v-model="form.base_url" class="input mono" :class="{ 'is-error': errOf('base_url') }" :disabled="env('base_url')"
                    :placeholder="form.provider === 'local' ? 'http://127.0.0.1:11434/v1' : form.provider === 'openai' ? 'https://…/v1' : 'https://api.anthropic.com'"
                    spellcheck="false" data-testid="ai-base-url"
                  >
                  <span v-if="env('base_url')" class="hint envhint"><Icon name="lock" small />{{ $t('ai-settings.envSet', { v: envName('base_url') }) }}</span>
                  <span v-else-if="errOf('base_url')" class="err"><Icon name="err" small />{{ errOf('base_url') }}</span>
                  <span v-else class="hint">{{ needsBaseUrl(form.provider) ? $t('ai-settings.baseUrlNeed') : $t('ai-settings.baseUrlOpt') }}</span>
                </div>

                <div class="field span2">
                  <label for="ai-key">API Key</label>
                  <div class="keyrow">
                    <input
                      id="ai-key" v-model="keyInput" type="password" autocomplete="new-password" class="input" :class="{ 'is-error': errOf('api_key') }"
                      :disabled="env('api_key')" :placeholder="keySet && !clearKey ? $t('ai-settings.keySetPh') : usesKey(form.provider) ? $t('ai-settings.keyPh') : $t('ai-settings.keyLocalPh')"
                      data-testid="ai-api-key" @input="clearKey = false"
                    >
                    <span v-if="keySet && !clearKey" class="tag pass nowrap" data-testid="ai-key-set"><Icon name="lock" small />{{ $t('ai-settings.keySet') }}</span>
                    <span v-else-if="clearKey" class="tag t-amber nowrap">{{ $t('ai-settings.keyWillClear') }}</span>
                    <button v-if="keySet && !env('api_key')" class="btn" data-testid="ai-key-clear" @click="clearKey = !clearKey; keyInput = ''">
                      {{ clearKey ? $t('ai-settings.keyKeep') : $t('ai-settings.keyClear') }}
                    </button>
                  </div>
                  <span v-if="env('api_key')" class="hint envhint"><Icon name="lock" small />{{ $t('ai-settings.envSet', { v: envName('api_key') }) }}</span>
                  <span v-else-if="errOf('api_key')" class="err"><Icon name="err" small />{{ errOf('api_key') }}</span>
                  <span class="enc"><Icon name="lock" small />{{ $t('ai-settings.keyNote') }}</span>
                </div>

                <div class="field">
                  <label for="ai-model">{{ $t('ai-settings.model') }}</label>
                  <input id="ai-model" v-model="form.model" class="input mono" :class="{ 'is-error': errOf('model') }" :disabled="env('model')" spellcheck="false" data-testid="ai-model">
                  <span v-if="env('model')" class="hint envhint"><Icon name="lock" small />{{ $t('ai-settings.envSet', { v: envName('model') }) }}</span>
                  <span v-else-if="errOf('model')" class="err"><Icon name="err" small />{{ errOf('model') }}</span>
                  <span v-else class="hint">{{ $t('ai-settings.modelHint') }}</span>
                </div>
                <div class="field">
                  <label>{{ $t('ai-settings.limits') }}</label>
                  <div class="row">
                    <label class="mini">
                      <span class="small muted">{{ $t('ai-settings.timeout') }}</span>
                      <input v-model.number="form.timeout" type="number" :min="LIMITS.timeout[0]" :max="LIMITS.timeout[1]" class="input" :class="{ 'is-error': errOf('timeout') }" :disabled="env('timeout')" data-testid="ai-timeout">
                    </label>
                    <label class="mini">
                      <span class="small muted">{{ $t('ai-settings.maxTokens') }}</span>
                      <input v-model.number="form.max_tokens" type="number" :min="LIMITS.max_tokens[0]" :max="LIMITS.max_tokens[1]" class="input" :class="{ 'is-error': errOf('max_tokens') }" :disabled="env('max_tokens')" data-testid="ai-max-tokens">
                    </label>
                  </div>
                  <span v-if="env('timeout') || env('max_tokens')" class="hint envhint"><Icon name="lock" small />{{ $t('ai-settings.envSetSome') }}</span>
                  <span v-else-if="errOf('timeout') || errOf('max_tokens')" class="err"><Icon name="err" small />{{ errOf('timeout') || errOf('max_tokens') }}</span>
                  <span v-else class="hint">{{ $t('ai-settings.limitsHint') }}</span>
                </div>
              </div>
              <p v-else class="small muted mt12">{{ $t('ai-settings.noneNote') }}</p>

              <div v-if="saveErr" class="notice err mt12" data-testid="ai-save-error"><Icon name="err" /><div class="grow small">{{ saveErr }}</div></div>

              <div class="row wrap mt16">
                <button class="btn" :disabled="!configured || dirty || testing" data-testid="ai-test" @click="test">
                  <Icon name="refresh" small />{{ testing ? $t('ai-settings.testing') : $t('ai-settings.test') }}
                </button>
                <span v-if="testRes" class="small" style="color: var(--teal-ink)" data-testid="ai-test-ok">
                  {{ $t('ai-settings.testOk', { m: testRes.model, ms: testRes.ms, i: testRes.tokens_in, o: testRes.tokens_out }) }}
                  <span class="mono faint">“{{ testRes.reply }}”</span>
                </span>
                <span v-else-if="testErr" class="small" style="color: var(--red-ink)" data-testid="ai-test-err">{{ $t('ai-settings.testFail', { e: testErr }) }}</span>
                <span v-else-if="dirty" class="small faint">{{ $t('ai-settings.testAfterSave') }}</span>
                <span v-else-if="!configured" class="small faint">{{ $t('ai-settings.testNeedConfig') }}</span>
              </div>
            </div>
          </div>

          <!-- 按任务选模型 -->
          <div v-if="form.provider" class="panel" data-testid="ai-task-models">
            <div class="panel-h"><h2>{{ $t('ai-settings.perTaskT') }}</h2><span class="meta">{{ $t('ai-settings.perTaskMeta') }}</span></div>
            <div class="tbl-wrap">
              <table class="tbl task-tbl">
                <thead><tr><th>{{ $t('ai-settings.task') }}</th><th>{{ $t('ai-settings.taskModel') }}</th><th>{{ $t('ai-settings.effective') }}</th></tr></thead>
                <tbody>
                  <tr v-for="k in (['extract', 'merge'] as const)" :key="k">
                    <td><div class="tn">{{ $t(`ai-settings.task_${k}`) }}</div><div class="td">{{ $t(`ai-settings.task_${k}_d`) }}</div></td>
                    <td>
                      <input
                        v-model="form[k === 'extract' ? 'model_extract' : 'model_merge']" class="input mono" :disabled="env(`model_${k}`)"
                        :placeholder="$t('ai-settings.useDefault')" spellcheck="false" :data-testid="`ai-model-${k}`"
                      >
                      <div v-if="env(`model_${k}`)" class="td">{{ $t('ai-settings.envSet', { v: envName(`model_${k}`) }) }}</div>
                    </td>
                    <td class="mono small">{{ effectiveModel(form, k) || '—' }}</td>
                  </tr>
                  <tr>
                    <td><div class="tn">{{ $t('ai-settings.task_test') }}</div><div class="td">{{ $t('ai-settings.task_test_d') }}</div></td>
                    <td class="small faint">{{ $t('ai-settings.useDefaultFixed') }}</td>
                    <td class="mono small">{{ form.model.trim() || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 调用记录 -->
          <div class="panel" data-testid="ai-calls">
            <div class="panel-h">
              <h2>{{ $t('ai-settings.callsT') }}</h2>
              <select v-model="taskFilter" class="select hsel" data-testid="ai-calls-filter">
                <option value="">{{ $t('ai-settings.allTasks') }}</option>
                <option v-for="k in taskNames" :key="k" :value="k">{{ taskLabel(k) }}</option>
              </select>
              <button class="btn btn-sm btn-icon" :title="$t('c.refresh')" :aria-label="$t('c.refresh')" data-testid="ai-calls-refresh" @click="loadCalls"><Icon name="refresh" small /></button>
            </div>
            <div v-if="callsErr" class="empty small"><p>{{ callsErr }}</p><button class="btn btn-sm" @click="loadCalls">{{ $t('c.retry') }}</button></div>
            <div v-else-if="callsLoading && !calls.length" class="empty small">{{ $t('c.loading') }}</div>
            <div v-else-if="!calls.length" class="empty small">{{ $t('ai-settings.noCalls') }}</div>
            <div v-else class="tbl-wrap" style="max-height: 360px">
              <table class="tbl compact" data-testid="ai-calls-table">
                <thead>
                  <tr>
                    <th>{{ $t('ai-settings.time') }}</th><th>{{ $t('ai-settings.task') }}</th><th>{{ $t('ai-settings.ifModel') }}</th>
                    <th class="num">{{ $t('ai-settings.in') }}</th><th class="num">{{ $t('ai-settings.out') }}</th><th>{{ $t('ai-settings.result') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="c in shownCalls" :key="c.id">
                    <td class="nowrap faint">{{ fmtTime(c.created_at) }}</td>
                    <td>{{ taskLabel(c.task) }}</td>
                    <td class="nowrap"><span class="small">{{ c.provider }}</span> <span class="mono small faint">{{ c.model }}</span></td>
                    <td class="num">{{ (c.tokens_in ?? 0).toLocaleString('en-US') }}</td>
                    <td class="num">{{ (c.tokens_out ?? 0).toLocaleString('en-US') }}</td>
                    <td class="nowrap">
                      <span v-if="c.status === 'ok'" class="tag pass">{{ $t('ai-settings.callOk') }}</span>
                      <span v-else class="tag error" :title="c.error ?? ''">{{ $t('ai-settings.callErr') }}</span>
                      <router-link v-if="c.review_item_id" class="mono small" :to="{ name: 'review' }"> #{{ c.review_item_id }}</router-link>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- 右栏 -->
        <div class="stack">
          <div class="panel">
            <div class="panel-h"><h2>{{ $t('ai-settings.safetyT') }}</h2><Icon name="shield" small style="color: var(--teal-ink)" /></div>
            <div class="panel-b safety">
              <div v-for="i in 4" :key="i" class="sw-row"><span class="t">{{ $t(`ai-settings.safe${i}`) }}</span><span class="d">{{ $t(`ai-settings.safe${i}_d`) }}</span></div>
            </div>
            <div class="panel-f small faint"><Icon name="key" small /><span>{{ $t('ai-settings.keyFoot') }}</span></div>
          </div>

          <div v-if="anyEnv" class="notice warn" data-testid="ai-env-notice">
            <Icon name="lock" /><div class="grow small">{{ $t('ai-settings.envNotice') }}</div>
          </div>

          <div class="panel usage" data-testid="ai-usage">
            <div class="panel-h"><h2>{{ $t('ai-settings.usageT') }}</h2><span class="meta">{{ fmtTokens(usageTotal) }} tokens</span></div>
            <div class="panel-b">
              <div v-if="!usage.length" class="small faint">{{ $t('ai-settings.noUsage') }}</div>
              <div v-for="u in usage" :key="u.task" class="r">
                <span>{{ taskLabel(u.task) }} <span class="faint">· {{ $t('ai-settings.usageCalls', { n: u.calls, e: u.errors }) }}</span></span>
                <b>{{ fmtTokens(u.tokensIn + u.tokensOut) }}</b>
                <div class="meter"><div class="bar"><i :style="{ width: `${Math.round(((u.tokensIn + u.tokensOut) / usageMax) * 100)}%` }" /></div></div>
              </div>
              <p class="small faint mt8">{{ $t('ai-settings.usageNote') }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.keyrow { display: flex; gap: 6px; align-items: center; }
.keyrow .input { flex: 1; min-width: 0; font-family: var(--font-mono); letter-spacing: .04em; }
.enc { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--teal-ink); }
.envhint { display: inline-flex; gap: 5px; align-items: center; color: var(--amber-ink) !important; margin-top: 6px; }
.task-tbl td { vertical-align: middle; }
.task-tbl .input { height: 28px; font-size: 12px; }
.task-tbl .tn { font-weight: 600; }
.task-tbl .td { font-size: 12px; color: var(--ink-3); }
.hsel { width: auto; height: 28px; }
.mini { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
.sw-row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.sw-row:last-child { border-bottom: 0; }
.sw-row .t { font-weight: 600; }
.sw-row .d { font-size: 12px; color: var(--ink-2); }
.safety { padding-top: 4px; padding-bottom: 4px; }
.off-hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.off-hero > div { padding: 18px 20px; }
.off-hero > div + div { border-left: 1px solid var(--line); }
.off-hero h3 { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.off-hero ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 7px; }
.off-hero li { display: flex; gap: 8px; align-items: flex-start; }
.off-hero li .ico { margin-top: 2px; flex: none; }
.off-hero .yes li .ico { color: var(--teal-ink); }
.off-hero .no li .ico { color: var(--ink-3); }
.types { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.types .radio-card { flex-direction: column; gap: 6px; }
.types .radio-card.ro { cursor: not-allowed; opacity: .75; }
.types .head { display: flex; gap: 8px; align-items: center; }
.lg { width: 24px; height: 24px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; font: 700 10px var(--font-ui); color: var(--surface); flex: none; }
.lg.anthropic { background: var(--amber-ink); }
.lg.openai { background: var(--blue-ink); }
.lg.local { background: var(--ink-2); }
.lg.none { background: transparent; color: var(--ink-3); border: 1px dashed var(--line-strong); }
.usage .r { display: grid; grid-template-columns: minmax(0, 1fr) auto; font-size: 12px; padding: 5px 0; }
.usage .meter { margin-top: 4px; grid-column: 1 / -1; }
@media (max-width: 1100px) {
  .g-side.collapse { grid-template-columns: minmax(0, 1fr); }
  .types { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .off-hero { grid-template-columns: minmax(0, 1fr); }
  .off-hero > div + div { border-left: 0; border-top: 1px solid var(--line); }
}
</style>
