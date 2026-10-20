<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api, ApiError } from '@/api'
import { LANGS, type Lang } from '@/i18n'
import { usePrefs } from '@/stores/prefs'
import { markConfigured } from '@/router'
import { useAuth } from '@/stores/auth'
import { passwordProblems, validName } from './account/account'
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import BareTopbar from '@/components/wizard-bare-topbar.vue'
import WizardField from './wizard/WizardField.vue'
import {
  aiTestReason, blocksOf, confirmRows, confirmStats, displayHost, displayValue, groupErrors, initialValues, labelKey, LANG_NOTES, optionKey,
  pickErrors, visibleGroups, type Running, type Values, type WField, type WGroup,
} from './wizard/wizard'

interface SetupResult {
  api_token: string
  token_generated: boolean
  url: string
  restart_required: boolean
  changed: string[]
  config_path?: string
  admin?: { username: string; role: string } | null
  session_expires_at?: string
}

const prefs = usePrefs()
const auth = useAuth()
const router = useRouter()
const { t, te } = useI18n()

const groups = ref<WGroup[]>([])
const addresses = ref<string[]>([])
const values = reactive<Values>({})
const errors = reactive<Record<string, string>>({})
const okKeys = reactive(new Set<string>()) // 服务端校验通过的字段（显示“端口可用”等）
const step = ref(0) // 0 = 语言；1..n = 分组；n+1 = 确认
const loading = ref(true)
const loadError = ref('')
const submitError = ref('')
const submitting = ref(false)
const result = ref<SetupResult | null>(null)
const dbPg = ref(false) // 数据库选了 PostgreSQL（地址可能还没填）
const aiOn = ref(false)
const copied = ref(false)
// 确认页（M6-9）：将写入的配置文件、运行中的监听地址、统一校验状态、只看已修改
const configPath = ref('')
const running = ref<Running>({})
const checking = ref(false)
const checked = ref(false)
const onlyChanged = ref(false)
// 第一个管理员（REQ-030）：在确认页之前单独一步
const admin = reactive({ username: 'admin', password: '', password2: '' })
const adminProblems = computed(() => passwordProblems(admin.password, admin.password2))

const shown = computed(() => visibleGroups(groups.value))
const adminStep = computed(() => shown.value.length + 1)
const lastStep = computed(() => shown.value.length + 2)
const current = computed(() => (step.value >= 1 && step.value <= shown.value.length ? shown.value[step.value - 1] : undefined))
const blocks = computed(() => (current.value ? blocksOf(current.value) : []))
const stepTitles = computed(() => [t('wizard.stepLanguage'), ...shown.value.map((g) => g.title), t('wizard.stepAdmin'), t('wizard.stepConfirm')])
const isAiStep = computed(() => blocks.value.some((b) => b.type === 'ai'))
const langLabel = computed(() => LANGS.find((l) => l.code === prefs.lang)?.label ?? prefs.lang)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api<{ groups: WGroup[]; addresses: string[]; config_path?: string; running?: Running }>('/setup')
    groups.value = data.groups
    addresses.value = data.addresses
    configPath.value = data.config_path ?? ''
    running.value = data.running ?? {}
    Object.assign(values, initialValues(data.groups, { ...values }))
    values['ui.language'] = prefs.lang
    dbPg.value = dbPg.value || !!values['database.url']
    aiOn.value = aiOn.value || !!values['ai.provider']
  } catch (e) {
    if (e instanceof ApiError && e.code === 1003) {
      markConfigured()
      await router.replace('/')
      return
    }
    loadError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
// 换语言后重新取说明文字（服务端按 Accept-Language 返回）
watch(() => prefs.lang, () => { values['ui.language'] = prefs.lang; if (!result.value) void load() })

function setValue(key: string, v: string | number): void {
  values[key] = v
  delete errors[key]
  okKeys.delete(key)
  if (key.startsWith('ai.') && aiTest.value.state !== 'run') aiTest.value = { state: 'idle' } // 接口参数变了，旧的测试结果不再有效
}

// AI 一步的“测试连接”（REQ-048）：POST /setup/ai-test，只在未配置时可用；Key 不保存、不写日志
interface AiTestState { state: 'idle' | 'run' | 'ok' | 'err'; model?: string; ms?: number; reason?: string }
const aiTest = ref<AiTestState>({ state: 'idle' })
async function testAi(): Promise<void> {
  for (const k of ['ai.provider', 'ai.base_url', 'ai.model']) delete errors[k]
  aiTest.value = { state: 'run' }
  try {
    const r = await api<{ model: string; elapsed_ms: number }>('/setup/ai-test', {
      method: 'POST',
      body: JSON.stringify({ provider: values['ai.provider'] ?? '', base_url: values['ai.base_url'] ?? '', api_key: values['ai.api_key'] ?? '', model: values['ai.model'] ?? '' }),
    })
    aiTest.value = { state: 'ok', model: r.model, ms: r.elapsed_ms }
  } catch (e) {
    if (e instanceof ApiError && e.status === 422 && e.data && typeof e.data === 'object' && 'errors' in e.data) {
      Object.assign(errors, (e.data as { errors: Record<string, string> }).errors)
      aiTest.value = { state: 'idle' }
      return
    }
    const d = (e instanceof ApiError ? e.data : null) as { status?: number | null; error_type?: string } | null
    aiTest.value = { state: 'err', reason: e instanceof ApiError && e.status === 502 ? t(aiTestReason(d?.status, d?.error_type), { s: d?.status ?? '' }) : (e as Error).message }
  }
}

/** 把当前全部取值交给服务端 dry_run 校验，只显示这些字段的结果。 */
async function validate(keys: string[]): Promise<boolean> {
  submitError.value = ''
  for (const k of keys) { delete errors[k]; okKeys.delete(k) }
  let mine: Record<string, string> = {}
  try {
    await api('/setup', { method: 'POST', body: JSON.stringify({ language: prefs.lang, values, admin: adminBody(), dry_run: true }) })
  } catch (e) {
    if (e instanceof ApiError && e.data && typeof e.data === 'object' && 'errors' in e.data) {
      mine = pickErrors((e.data as { errors: Record<string, string> }).errors, keys)
    } else {
      submitError.value = (e as Error).message
      return false
    }
  }
  Object.assign(errors, mine)
  for (const k of keys) if (!(k in mine)) okKeys.add(k)
  return Object.keys(mine).length === 0
}

function adminBody(): { username: string; password: string } {
  return { username: admin.username.trim(), password: admin.password }
}

/** 管理员一步：先在本地检查，再交给服务端校验用户名与密码规则。 */
async function checkAdmin(): Promise<boolean> {
  delete errors['admin.username']
  delete errors['admin.password']
  if (!validName(admin.username)) errors['admin.username'] = t('account.nameHint')
  if (adminProblems.value.length) errors['admin.password'] = t(`account.rule.${adminProblems.value[0]}`)
  if (errors['admin.username'] || errors['admin.password']) return false
  return validate(['admin.username', 'admin.password'])
}

/** 下一步；toConfirm 为真时校验本步后直接回到确认页（从确认页“返回修改”过来时用）。 */
async function next(toConfirm = false): Promise<void> {
  if (step.value === adminStep.value) {
    if (await checkAdmin()) step.value = lastStep.value
    return
  }
  const g = current.value
  if (g) {
    if (dbPg.value && g.fields.some((f) => f.kind === 'dburl' && !String(values[f.key] ?? '').trim())) {
      const f = g.fields.find((x) => x.kind === 'dburl') as WField
      errors[f.key] = t('wizard.dbRequired')
      return
    }
    if (!(await validate(g.fields.map((f) => f.key)))) return
  }
  step.value = toConfirm ? lastStep.value : Math.min(step.value + 1, lastStep.value)
}

function back(): void {
  submitError.value = ''
  step.value = Math.max(0, step.value - 1)
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  submitting.value = true
  submitError.value = ''
  try {
    result.value = await api<SetupResult>('/setup', { method: 'POST', body: JSON.stringify({ language: prefs.lang, values, admin: adminBody() }) })
    admin.password = admin.password2 = ''
    if (result.value.admin) auth.set(result.value.admin, result.value.session_expires_at ?? null)
    markConfigured()
  } catch (e) {
    if (e instanceof ApiError && e.data && typeof e.data === 'object' && 'errors' in e.data) {
      // 某一步的取值不合格：回到第一个出错字段所在的步骤
      const errs = (e.data as { errors: Record<string, string> }).errors
      Object.assign(errors, errs)
      if (Object.keys(errs).some((k) => k.startsWith('admin.'))) { step.value = adminStep.value; return }
      const idx = shown.value.findIndex((g) => g.fields.some((f) => f.key in errs))
      if (idx >= 0) { step.value = idx + 1; return }
    }
    submitError.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}

function setLang(code: Lang): void { prefs.lang = code }

function setLocalOnly(host: WField, on: boolean): void {
  setValue(host.key, on ? '127.0.0.1' : String(host.default || '0.0.0.0'))
}

function setDb(f: WField, pg: boolean): void {
  dbPg.value = pg
  if (!pg) setValue(f.key, '')
}

function setAi(f: WField, on: boolean): void {
  aiOn.value = on
  setValue(f.key, on ? String(values[f.key] || f.choices.find((c) => c) || '') : '')
}

function providerLabel(c: string): string {
  return c && te(`wizard.prov_${c}`) ? t(`wizard.prov_${c}`) : c || t('wizard.none')
}

function label(f: WField): string {
  return te(labelKey(f.key)) ? t(labelKey(f.key)) : f.desc
}

/** 汇总里的一行：未填写时按字段给出含义。 */
function summaryText(f: WField): string {
  const v = displayValue(f, values[f.key])
  const o = optText(f, values[f.key])
  if (o !== null) return o
  if (v !== null) return v
  if (f.kind === 'dburl') return t('wizard.dbSqliteValue')
  if (f.kind === 'token') return t('wizard.tokenAutoValue')
  return t('wizard.notSet')
}

/** 默认值的显示文字（“默认：9090”）。 */
/** 选项的显示文字（开关、显示风格 Huawei / Cisco / Nokia、AI 接口类型、语言）；不是选项时 null。 */
function optText(f: WField, v: string | number | undefined): string | null {
  if (f.key === 'ui.language') return LANGS.find((l) => l.code === v)?.label ?? null
  const k = optionKey(f.key, f.kind, String(v ?? ''))
  return k && te(k) ? t(k) : null
}

function defaultText(f: WField): string {
  const o = optText(f, f.default)
  if (o !== null) return o
  if (f.kind === 'dburl' && !f.default) return t('wizard.dbSqliteValue')
  return String(f.default ?? '') || t('wizard.notSet')
}

const langField = computed(() => groups.value.flatMap((g) => g.fields).find((f) => f.key === 'ui.language'))
const langChanged = computed(() => !!langField.value && prefs.lang !== String(langField.value.default))
const stats = computed(() => confirmStats(shown.value, values, errors, running.value))
const adminErrors = computed(() => ['admin.username', 'admin.password'].filter((k) => errors[k]).length)
const restartLabels = computed(() => stats.value.restart.map((k) => {
  const f = shown.value.flatMap((g) => g.fields).find((x) => x.key === k)
  return f ? label(f) : k
}))
const canSubmit = computed(() => checked.value && !checking.value && !submitting.value && stats.value.errors === 0)

/** 进入确认页时把全部取值（含管理员）交给服务端统一校验一次。 */
async function checkAll(): Promise<void> {
  checking.value = true
  checked.value = false
  try {
    const keys = [...shown.value.flatMap((g) => g.fields.map((f) => f.key)), 'admin.username', 'admin.password']
    await validate(keys)
    if (dbPg.value) {
      const f = shown.value.flatMap((g) => g.fields).find((x) => x.kind === 'dburl')
      if (f && !String(values[f.key] ?? '').trim()) errors[f.key] = t('wizard.dbRequired')
    }
    checked.value = !submitError.value
  } finally {
    checking.value = false
  }
}
const seenConfirm = ref(false)
watch(step, (s) => {
  if (s !== lastStep.value || result.value) return
  seenConfirm.value = true
  void checkAll()
})

const usageHost = computed(() => {
  const host = String(values['server.host'] ?? '')
  return `${displayHost(host)}:${values['server.port'] ?? ''}`
})

async function copyToken(): Promise<void> {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.api_token)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* 剪贴板不可用时可手动选中复制 */ }
}
</script>

<template>
  <div class="bare wz-page">
    <BareTopbar />
    <div class="wz-wrap">
      <div class="wz">
        <!-- M9-7 评审（空白太多）：左侧步骤栏 + 右侧两列字段，卡片高度随内容 -->
        <div class="wz-card">
          <aside class="wz-rail">
            <div class="wz-brand">
              <!-- eslint-disable-next-line vue/no-v-html -->
              <span class="wz-logo" v-html="LOGO_SVG" />
              <div><h1>{{ $t('wizard.title') }}</h1><small>{{ $t('wizard.subtitle') }}</small></div>
            </div>
            <ol v-if="shown.length" class="wz-steps" data-testid="wizard-steps">
              <li v-for="(title, i) in stepTitles" :key="i" :class="['st', { done: result || i < step, cur: !result && i === step }]">
                <span class="no"><Icon v-if="result || i < step" name="check" small /><template v-else>{{ i + 1 }}</template></span>
                <span class="t">{{ title }}</span>
              </li>
            </ol>
          </aside>
          <section class="wz-main">

          <!-- 完成 -->
          <div v-if="result" class="wz-body" data-testid="wizard-done">
            <div class="empty done">
              <div class="done-art"><Icon name="check" /></div>
              <h3>{{ $t('wizard.doneTitle') }}</h3>
              <p>{{ $t('wizard.doneLead') }}</p>
              <p v-if="result.admin" class="small" data-testid="wizard-signed-in">{{ $t('wizard.adminSignedIn', { name: result.admin.username }) }}</p>
            </div>
            <dl class="kv done-kv">
              <dt>{{ $t('wizard.doneUrl') }}</dt>
              <dd><a :href="result.url" class="mono">{{ result.url }}</a></dd>
            </dl>
            <div v-if="result.restart_required" class="notice warn mt12"><Icon name="warn" /><div class="grow small">{{ $t('wizard.restart') }}</div></div>
            <template v-if="result.token_generated">
              <div class="section-t mt16">{{ $t('wizard.lbl.security_api_token') }}</div>
              <div class="token">
                <code data-testid="wizard-token">{{ result.api_token }}</code>
                <button type="button" class="btn" data-testid="wizard-copy-token" @click="copyToken">
                  <Icon :name="copied ? 'check' : 'copy'" small />{{ copied ? $t('c.copied') : $t('c.copy') }}
                </button>
              </div>
              <div class="notice warn mt12"><Icon name="key" /><div class="grow small">{{ $t('wizard.tokenOnce') }}</div></div>
            </template>
            <div class="row done-actions">
              <router-link class="btn btn-primary" :to="{ name: 'devices' }" data-testid="wizard-import"><Icon name="upload" small />{{ $t('wizard.importConfigs') }}</router-link>
              <router-link class="btn" :to="{ name: 'dashboard' }" data-testid="wizard-home">{{ $t('wizard.openHome') }}</router-link>
            </div>
          </div>

          <div v-else-if="loading && !shown.length" class="wz-body"><div class="empty">{{ $t('c.loading') }}</div></div>

          <div v-else-if="loadError && !shown.length" class="wz-body">
            <div class="notice err" data-testid="wizard-load-error">
              <Icon name="err" />
              <div class="grow"><b>{{ $t('wizard.loadFailed') }}</b><div class="small">{{ loadError }}</div></div>
              <button type="button" class="btn btn-sm" @click="load"><Icon name="refresh" small />{{ $t('c.retry') }}</button>
            </div>
          </div>

          <template v-else>
            <div class="wz-body">
              <!-- 第一步：语言 -->
              <template v-if="step === 0">
                <div class="wz-head"><h2>{{ $t('wizard.langTitle') }}</h2><p class="lead">{{ $t('wizard.langLead') }}</p></div>
                <div class="radio-cards lang-cards" role="radiogroup" data-testid="wizard-lang">
                  <label v-for="l in LANGS" :key="l.code" class="radio-card">
                    <input type="radio" name="lang" :value="l.code" :checked="prefs.lang === l.code" @change="setLang(l.code)" />
                    <span class="ln">{{ l.label }}</span>
                    <span class="lnote">{{ LANG_NOTES[l.code] }}</span>
                  </label>
                </div>
                <div class="section-t mt16">{{ $t('wizard.themeTitle') }}</div>
                <p class="small muted">{{ $t('wizard.themeHint') }}</p>
              </template>

              <!-- 设置分组：字段来自 GET /setup -->
              <template v-else-if="current">
                <div class="wz-head"><h2>{{ current.title }}</h2><p v-if="te(`wizard.lead_${current.id}`)" class="lead">{{ $t(`wizard.lead_${current.id}`) }}</p></div>
                <div class="blocks fgrid">
                  <template v-for="b in blocks" :key="b.type === 'hostport' ? b.host.key : b.field.key">
                    <div v-if="b.type === 'hostport'" class="span2">
                      <div :class="{ hostport: b.port }">
                        <WizardField :field="b.host" :model-value="values[b.host.key]" :error="errors[b.host.key]" :addresses="addresses"
                          @update:model-value="setValue(b.host.key, $event)" @commit="validate([b.host.key])" />
                        <WizardField v-if="b.port" :field="b.port" :model-value="values[b.port.key]" :error="errors[b.port.key]" hint=""
                          :ok="okKeys.has(b.port.key) ? $t('wizard.portFree') : ''"
                          @update:model-value="setValue(b.port!.key, $event)" @commit="validate([b.host.key, b.port!.key])" />
                      </div>
                      <label class="check mt12">
                        <input type="checkbox" :checked="values[b.host.key] === '127.0.0.1'" data-testid="wizard-local-only"
                          @change="setLocalOnly(b.host, ($event.target as HTMLInputElement).checked)" />
                        {{ $t('wizard.localOnly') }}
                      </label>
                      <div v-if="values[b.host.key] !== '127.0.0.1'" class="notice info mt12"><Icon name="info" /><div class="grow small">{{ $t('wizard.lanNote') }}</div></div>
                    </div>

                    <div v-else-if="b.type === 'dburl'" class="span2">
                      <div class="field-label">{{ $t('wizard.dbType') }}</div>
                      <div class="radio-cards db-cards mt8" role="radiogroup">
                        <label class="radio-card">
                          <input type="radio" name="db" :checked="!dbPg" data-testid="wizard-db-sqlite" @change="setDb(b.field, false)" />
                          <span><span class="rc-t">SQLite <span class="tag t-teal">{{ $t('wizard.dbDefault') }}</span></span><br /><span class="rc-d">{{ $t('wizard.dbSqliteDesc') }}</span></span>
                        </label>
                        <label class="radio-card">
                          <input type="radio" name="db" :checked="dbPg" data-testid="wizard-db-pg" @change="setDb(b.field, true)" />
                          <span><span class="rc-t">PostgreSQL</span><br /><span class="rc-d">{{ $t('wizard.dbPgDesc') }}</span></span>
                        </label>
                      </div>
                      <WizardField v-if="dbPg" class="mt12" :field="b.field" :model-value="values[b.field.key]" :error="errors[b.field.key]"
                        :ok="okKeys.has(b.field.key) && values[b.field.key] ? $t('wizard.dbOk') : ''" :placeholder="$t('wizard.dbPgPh')"
                        @update:model-value="setValue(b.field.key, $event)" @commit="validate([b.field.key])" />
                    </div>

                    <div v-else-if="b.type === 'ai'" class="span2 ai-block">
                      <div class="radio-cards two" role="radiogroup">
                        <label class="radio-card">
                          <input type="radio" name="ai" :checked="!aiOn" data-testid="wizard-ai-skip" @change="setAi(b.field, false)" />
                          <span><span class="rc-t">{{ $t('wizard.aiSkip') }}</span><br /><span class="rc-d">{{ $t('wizard.aiSkipDesc') }}</span></span>
                        </label>
                        <label class="radio-card">
                          <input type="radio" name="ai" :checked="aiOn" data-testid="wizard-ai-now" @change="setAi(b.field, true)" />
                          <span><span class="rc-t">{{ $t('wizard.aiNow') }}</span><br /><span class="rc-d">{{ $t('wizard.aiNowDesc') }}</span></span>
                        </label>
                      </div>
                      <WizardField v-if="aiOn" class="mt16" :field="b.field" :model-value="values[b.field.key]" :error="errors[b.field.key]"
                        :choices="b.field.choices.filter((c) => c)" :option-label="providerLabel" hint=""
                        @update:model-value="setValue(b.field.key, $event)" @commit="validate([b.field.key, 'ai.base_url'])" />
                    </div>

                    <WizardField v-else-if="!b.needsAi || aiOn" :field="b.field" :model-value="values[b.field.key]" :error="errors[b.field.key]"
                      :placeholder="b.field.kind === 'token' ? $t('wizard.tokenAuto') : undefined"
                      @update:model-value="setValue(b.field.key, $event)" @commit="validate([b.field.key])" />

                    <template v-if="b.type === 'field' && b.field.kind === 'token'">
                      <div class="token-usage span2">
                        <div class="section-t">{{ $t('wizard.tokenUsage') }}</div>
                        <pre class="block">curl -H "Authorization: Bearer {{ $t('wizard.tokenPlaceholder') }}" http://{{ usageHost }}/api/v1/summary</pre>
                        <div class="notice warn mt12"><Icon name="key" /><div class="grow small">{{ $t('wizard.tokenNote') }}</div></div>
                      </div>
                    </template>
                  </template>
                  <div v-if="isAiStep && aiOn" :class="['aitest', 'span2', 'is-' + aiTest.state]" data-testid="wizard-ai-test">
                    <button type="button" class="btn" :disabled="aiTest.state === 'run'" data-testid="wizard-ai-test-btn" @click="testAi"><Icon name="plug" small />{{ $t('wizard.aiTest') }}</button>
                    <div class="res" role="status" data-testid="wizard-ai-test-result">
                      <template v-if="aiTest.state === 'idle'"><span class="idle">{{ $t('wizard.aiTestIdle') }}</span></template>
                      <template v-else-if="aiTest.state === 'run'"><span class="spin" />{{ $t('wizard.aiTestRun') }}</template>
                      <template v-else-if="aiTest.state === 'ok'"><Icon name="ok" small />{{ $t('wizard.aiTestOk') }}</template>
                      <template v-else><Icon name="err" small />{{ $t('wizard.aiTestFail', { r: aiTest.reason }) }}</template>
                    </div>
                    <div v-if="aiTest.state === 'ok'" class="det">{{ $t('wizard.aiTestOkDetail', { m: aiTest.model, s: ((aiTest.ms ?? 0) / 1000).toFixed(1) }) }}</div>
                    <div v-else-if="aiTest.state === 'err'" class="det">{{ $t('wizard.aiTestFailHint') }}</div>
                  </div>
                  <div v-if="isAiStep && aiOn" class="notice info span2"><Icon name="shield" /><div class="grow small">{{ $t('wizard.aiNote') }}</div></div>
                </div>
              </template>

              <!-- 管理员账号（REQ-030） -->
              <template v-else-if="step === adminStep">
                <div class="wz-head"><h2>{{ $t('wizard.adminTitle') }}</h2><p class="lead">{{ $t('wizard.adminLead') }}</p></div>
                <div class="blocks fgrid" data-testid="wizard-admin">
                  <div class="field">
                    <label for="wz-admin-name">{{ $t('wizard.adminName') }}</label>
                    <input id="wz-admin-name" v-model="admin.username" :class="['input', { 'is-error': errors['admin.username'] }]" autocomplete="username"
                      spellcheck="false" data-testid="wizard-admin-name" @input="delete errors['admin.username']" />
                    <span v-if="errors['admin.username']" class="err"><Icon name="err" small />{{ errors['admin.username'] }}</span>
                    <span v-else class="hint">{{ $t('account.nameHint') }}</span>
                  </div>
                  <div class="field">
                    <label for="wz-admin-pw">{{ $t('wizard.adminPassword') }}</label>
                    <input id="wz-admin-pw" v-model="admin.password" type="password" :class="['input', { 'is-error': errors['admin.password'] }]" autocomplete="new-password"
                      data-testid="wizard-admin-password" @input="delete errors['admin.password']" />
                    <span v-if="errors['admin.password']" class="err"><Icon name="err" small />{{ errors['admin.password'] }}</span>
                    <span v-else class="hint">{{ $t('account.rule.short') }}</span>
                  </div>
                  <div class="field">
                    <label for="wz-admin-pw2">{{ $t('account.repeat') }}</label>
                    <input id="wz-admin-pw2" v-model="admin.password2" type="password" class="input" autocomplete="new-password" data-testid="wizard-admin-password2"
                      @input="delete errors['admin.password']" />
                  </div>
                  <div class="notice info span2"><Icon name="shield" /><div class="grow small">{{ $t('wizard.adminNote') }}</div></div>
                </div>
              </template>

              <!-- 确认（M6-9）：按组汇总、突出改动、统一校验、写入路径与需重启的项 -->
              <template v-else>
                <div class="wz-head"><h2>{{ $t('wizard.confirmTitle') }}</h2><p class="lead">{{ $t('wizard.cfLead') }}</p></div>
                <div :class="['cf-strip', { bad: checked && stats.errors > 0 }]" data-testid="wizard-cf-strip">
                  <span class="cf-verdict" data-testid="wizard-cf-verdict">
                    <span class="dot"><Icon :name="checking || !checked ? 'refresh' : stats.errors ? 'err' : 'check'" small /></span>
                    <template v-if="checking || !checked">{{ $t('wizard.cfChecking') }}</template>
                    <template v-else-if="stats.errors">{{ $t('wizard.cfProblems', { n: stats.errors }) }}</template>
                    <template v-else>{{ $t('wizard.cfOk') }}</template>
                  </span>
                  <span v-if="configPath" class="cf-path">{{ $t('wizard.cfWritesTo') }} <code data-testid="wizard-cf-path">{{ configPath }}</code></span>
                  <div class="cf-facts">
                    <span>{{ $t('wizard.cfChangedN', { n: stats.changed }) }}</span>
                    <span>{{ $t('wizard.cfDefaultN', { n: stats.unchanged }) }}</span>
                    <span v-if="stats.restart.length" data-testid="wizard-cf-restart-n">{{ $t('wizard.cfRestartN', { n: stats.restart.length }) }}</span>
                    <button v-if="checked && !checking" type="button" class="btn btn-xs btn-ghost" data-testid="wizard-cf-recheck" @click="checkAll"><Icon name="refresh" small />{{ $t('wizard.cfRecheck') }}</button>
                    <span class="seg" role="group">
                      <button type="button" :aria-pressed="!onlyChanged" @click="onlyChanged = false">{{ $t('wizard.cfAll') }}</button>
                      <button type="button" :aria-pressed="onlyChanged" data-testid="wizard-cf-only" @click="onlyChanged = true">{{ $t('wizard.cfOnlyChanged') }}</button>
                    </span>
                  </div>
                </div>
                <div class="cf-groups" data-testid="wizard-summary">
                  <section v-if="!onlyChanged || langChanged" class="cf-g">
                    <div class="cf-gh">
                      <h3>{{ $t('wizard.stepLanguage') }}</h3>
                      <button type="button" class="btn btn-xs" @click="step = 0"><Icon name="chevL" small />{{ $t('wizard.cfEdit') }}</button>
                    </div>
                    <div :class="['cf-r', langChanged ? 'is-chg' : 'is-def']">
                      <span class="k">{{ $t('wizard.language') }}</span>
                      <span class="v">{{ langLabel }}</span>
                      <span class="b"><span v-if="langChanged" class="tag t-teal">{{ $t('wizard.changed') }}</span><span v-else class="tag default">{{ $t('wizard.cfDefault') }}</span></span>
                    </div>
                  </section>
                  <template v-for="(g, gi) in shown" :key="g.id">
                    <section v-if="!onlyChanged || confirmRows(g, values, errors, running, true).length"
                      :class="['cf-g', { 'has-err': groupErrors(g, errors) }]" :data-testid="`wizard-sum-${g.id}`">
                      <div class="cf-gh">
                        <h3>{{ g.title }}</h3>
                        <span v-if="groupErrors(g, errors)" class="tag t-red">{{ $t('wizard.cfGroupProblems', { n: groupErrors(g, errors) }) }}</span>
                        <span v-else-if="confirmRows(g, values, errors, running, true).length" class="cnt">{{ $t('wizard.cfGroupChanged', { n: confirmRows(g, values, errors, running, true).length }) }}</span>
                        <button type="button" class="btn btn-xs" :data-testid="`wizard-cf-edit-${g.id}`" @click="step = gi + 1"><Icon name="chevL" small />{{ $t('wizard.cfEdit') }}</button>
                      </div>
                      <div v-if="!values['ai.provider'] && g.fields.some((f) => f.key === 'ai.provider')" class="cf-empty"><span class="tag">{{ $t('wizard.aiOff') }}</span></div>
                      <div v-for="r in confirmRows(g, values, errors, running, onlyChanged)" :key="r.field.key"
                        :class="['cf-r', r.error ? 'is-err' : r.changed ? 'is-chg' : 'is-def']" :data-testid="`wizard-cf-row-${r.field.key}`">
                        <span class="k">{{ label(r.field) }}</span>
                        <span :class="['v', { mono: !r.secretState && r.field.kind !== 'choice' && r.field.kind !== 'bool' && displayValue(r.field, values[r.field.key]) !== null }]">
                          <template v-if="r.secretState === 'set'">{{ $t('wizard.cfSet') }}</template>
                          <template v-else-if="r.secretState === 'unset'">{{ r.field.kind === 'token' ? $t('wizard.tokenAutoValue') : $t('wizard.cfUnset') }}</template>
                          <template v-else>{{ summaryText(r.field) }}</template>
                          <span v-if="r.changed && !r.secretState" class="was">{{ $t('wizard.cfWas', { v: defaultText(r.field) }) }}</span>
                        </span>
                        <span class="b">
                          <span v-if="r.changed" class="tag t-teal">{{ $t('wizard.changed') }}</span>
                          <span v-else-if="!r.secretState" class="tag default">{{ $t('wizard.cfDefault') }}</span>
                          <span v-if="r.restart" class="tag t-amber" data-testid="wizard-cf-restart">{{ $t('wizard.cfRestart') }}</span>
                        </span>
                        <span v-if="r.error" class="e" role="alert"><Icon name="err" small />{{ r.error }}</span>
                      </div>
                    </section>
                  </template>
                  <section v-if="!onlyChanged || adminErrors" :class="['cf-g', { 'has-err': adminErrors }]" data-testid="wizard-sum-admin">
                    <div class="cf-gh">
                      <h3>{{ $t('wizard.stepAdmin') }}</h3>
                      <span v-if="adminErrors" class="tag t-red">{{ $t('wizard.cfGroupProblems', { n: adminErrors }) }}</span>
                      <button type="button" class="btn btn-xs" data-testid="wizard-cf-edit-admin" @click="step = adminStep"><Icon name="chevL" small />{{ $t('wizard.cfEdit') }}</button>
                    </div>
                    <div :class="['cf-r', errors['admin.username'] ? 'is-err' : 'is-def']">
                      <span class="k">{{ $t('wizard.adminName') }}</span><span class="v mono">{{ admin.username }}</span><span class="b"></span>
                      <span v-if="errors['admin.username']" class="e" role="alert"><Icon name="err" small />{{ errors['admin.username'] }}</span>
                    </div>
                    <div :class="['cf-r', errors['admin.password'] ? 'is-err' : 'is-def']">
                      <span class="k">{{ $t('wizard.adminPassword') }}</span><span class="v">{{ admin.password ? $t('wizard.cfSet') : $t('wizard.cfUnset') }}</span><span class="b"></span>
                      <span v-if="errors['admin.password']" class="e" role="alert"><Icon name="err" small />{{ errors['admin.password'] }}</span>
                    </div>
                  </section>
                </div>
                <div v-if="restartLabels.length" class="notice warn cf-restart" data-testid="wizard-cf-restart-note">
                  <Icon name="warn" /><div class="grow small">{{ $t('wizard.cfRestartList') }}<b>{{ restartLabels.join($t('wizard.cfSep')) }}</b></div>
                </div>
              </template>

              <div v-if="submitError" class="notice err mt16" role="alert" data-testid="wizard-error"><Icon name="err" /><div class="grow small">{{ submitError }}</div></div>
            </div>

            <div class="wz-foot">
              <button v-if="step > 0" type="button" class="btn" data-testid="wizard-back" @click="back">{{ $t('c.back') }}</button>
              <span v-if="step === lastStep && checked && stats.errors" class="grow small fix-first" data-testid="wizard-fix-first">{{ $t('wizard.cfFixFirst', { n: stats.errors }) }}</span>
              <span v-else class="grow small faint">{{ step < lastStep ? $t('wizard.stepOf', { n: step + 1, total: lastStep + 1 }) : '' }}</span>
              <button v-if="seenConfirm && step < lastStep" type="button" class="btn" data-testid="wizard-to-confirm" @click="next(true)">{{ $t('wizard.cfBackToConfirm') }}</button>
              <button v-if="step === lastStep" type="button" class="btn btn-primary" :disabled="!canSubmit" data-testid="wizard-submit" @click="submit">
                <Icon name="check" small />{{ submitting ? $t('c.loading') : $t('wizard.save') }}
              </button>
              <button v-else type="button" class="btn btn-primary" data-testid="wizard-next" @click="next()">
                {{ isAiStep && !aiOn ? $t('wizard.skipAi') : $t('c.next') }}
              </button>
            </div>
          </template>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wz-page { display: flex; flex-direction: column; background: var(--bg); }
.wz-wrap { flex: 1; display: flex; justify-content: center; align-items: flex-start; padding: 20px 16px 28px; }
.wz { width: min(1120px, 100%); }
/* M9-7 评审（空白太多）：左侧步骤栏 + 右侧内容，字段两列，卡片高度随内容 */
.wz-card { display: grid; grid-template-columns: 236px minmax(0, 1fr); background: var(--surface); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.wz-rail { min-width: 0; background: var(--surface-2); border-right: 1px solid var(--line); padding: 16px 12px; display: flex; flex-direction: column; gap: 14px; }
.wz-brand { display: flex; gap: 10px; align-items: flex-start; padding: 0 4px; }
.wz-logo { display: contents; }
.wz-logo :deep(svg) { width: 36px; height: 36px; flex: none; }
.wz-brand h1 { font-size: 14px; margin: 0; }
.wz-brand small { display: block; font-size: 11.5px; color: var(--ink-3); margin-top: 2px; line-height: 1.45; }
.wz-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
.wz-steps .st { display: flex; align-items: center; gap: 9px; padding: 5px 8px; border-radius: 6px; font-size: 12.5px; color: var(--ink-3); min-width: 0; }
.wz-steps .st .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wz-steps .st .no { width: 20px; height: 20px; border-radius: 50%; border: 1px solid var(--line-strong); display: inline-flex; align-items: center; justify-content: center; font-size: 11px; flex: none; background: var(--surface); }
.wz-steps .st.done { color: var(--ink-2); }
.wz-steps .st.done .no { background: var(--teal-soft); border-color: var(--teal-line); color: var(--teal-ink); }
.wz-steps .st.cur { color: var(--ink); font-weight: 600; background: var(--surface); box-shadow: inset 0 0 0 1px var(--line); }
.wz-steps .st.cur .no { background: var(--teal); border-color: var(--teal); color: #fff; }
.wz-main { display: flex; flex-direction: column; min-width: 0; }
.wz-body { padding: 20px 24px; flex: 1; }
.wz-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.wz-head h2 { font-size: 17px; margin: 0; }
.wz-head .lead { margin: 0; color: var(--ink-2); font-size: 12.5px; }
.wz-foot { display: flex; gap: 8px; align-items: center; padding: 10px 24px; border-top: 1px solid var(--line); }
.wz-foot .grow { flex: 1; }
.blocks { display: flex; flex-direction: column; gap: 14px; }
.fgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; align-items: start; }
.fgrid > .span2 { grid-column: 1 / -1; }
.ai-block .field { max-width: calc(50% - 9px); }
.lang-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.lang-cards .radio-card { flex-direction: column; gap: 6px; padding: 14px; position: relative; }
.lang-cards .ln { font: 600 16px var(--font-display); }
.lang-cards .lnote { color: var(--ink-2); font-size: 12px; }
.lang-cards input { position: absolute; opacity: 0; }
.lang-cards .radio-card:has(input:focus-visible) { outline: 2px solid var(--focus); }
.radio-cards.two, .db-cards { grid-template-columns: 1fr 1fr; }
.rc-t .tag { margin-left: 6px; }
.hostport { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; }
/* AI 测试连接（REQ-048） */
.aitest { border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 14px; align-items: center; background: var(--surface-2); }
.aitest .btn { grid-row: span 2; }
.aitest .res { display: flex; gap: 6px; align-items: center; font-size: 13px; font-weight: 600; min-height: 20px; }
.aitest .res .idle { font-weight: 400; color: var(--ink-3); }
.aitest .det { grid-column: 2; font-size: 12px; color: var(--ink-2); overflow-wrap: anywhere; }
.aitest.is-ok { border-color: var(--teal-line); background: color-mix(in srgb, var(--teal-soft) 55%, var(--surface)); }
.aitest.is-ok .res { color: var(--teal-ink); }
.aitest.is-err { border-color: var(--red-line); background: color-mix(in srgb, var(--red-soft) 55%, var(--surface)); }
.aitest.is-err .res { color: var(--red-ink); }
.spin { width: 14px; height: 14px; border: 2px solid var(--line-strong); border-top-color: var(--blue); border-radius: 50%; animation: wz-spin .8s linear infinite; display: inline-block; }
@keyframes wz-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.token { display: flex; gap: 8px; align-items: center; }
.token code { flex: 1; padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 5px; font-size: 13px; overflow-wrap: anywhere; }
/* 确认页（M6-9） */
.cf-strip { border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2); padding: 12px 14px; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 14px; align-items: center; margin-bottom: 14px; }
.cf-strip.bad { border-color: var(--red-line); background: color-mix(in srgb, var(--red-soft) 55%, var(--surface)); }
.cf-verdict { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; white-space: nowrap; }
.cf-verdict .dot { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: var(--teal-soft); color: var(--teal-ink); }
.cf-strip.bad .cf-verdict .dot { background: var(--red-soft); color: var(--red-ink); }
.cf-path { display: flex; gap: 8px; align-items: center; min-width: 0; font-size: 12.5px; color: var(--ink-2); }
.cf-path code { font: 12px var(--font-mono); color: var(--ink); overflow-wrap: anywhere; min-width: 0; }
.cf-facts { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; font-size: 12.5px; color: var(--ink-2); }
.cf-facts .seg { margin-left: auto; }
.cf-groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; align-items: start; }
.cf-g { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.cf-g.has-err { border-color: var(--red-line); }
.cf-gh { display: flex; align-items: center; gap: 8px; padding: 7px 8px 7px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); }
.cf-gh h3 { font-size: 13px; }
.cf-gh .cnt { font-size: 12px; color: var(--ink-3); }
.cf-gh .btn { margin-left: auto; }
.cf-r { display: grid; grid-template-columns: 170px minmax(0, 1fr) auto; gap: 4px 14px; padding: 8px 12px; border-top: 1px solid var(--line); align-items: baseline; position: relative; }
.cf-gh + .cf-r { border-top: 0; }
.cf-r .k { color: var(--ink-2); font-size: 12.5px; }
.cf-r .v { min-width: 0; overflow-wrap: anywhere; }
.cf-r .v .was { display: block; font: 11.5px var(--font-ui); color: var(--ink-3); margin-top: 2px; }
.cf-r .b { display: flex; gap: 4px; justify-content: flex-end; flex-wrap: wrap; }
.cf-r.is-def .v { color: var(--ink-2); }
.cf-r.is-chg { background: color-mix(in srgb, var(--teal-soft) 40%, transparent); }
.cf-r.is-chg::before, .cf-r.is-err::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--teal); }
.cf-r.is-err { background: color-mix(in srgb, var(--red-soft) 55%, transparent); }
.cf-r.is-err::before { background: var(--red); }
.cf-r .e { grid-column: 2 / -1; color: var(--red-ink); font-size: 12px; display: flex; gap: 6px; align-items: center; }
.cf-empty { padding: 10px 12px; font-size: 12.5px; color: var(--ink-3); }
.cf-restart { margin-top: 12px; }
.fix-first { color: var(--red-ink); }
.done { padding: 20px 0 16px; }
.done-art { width: 64px; height: 64px; border-radius: 50%; background: var(--teal-soft); color: var(--teal-ink); display: flex; align-items: center; justify-content: center; }
.done-art :deep(.ico) { width: 30px; height: 30px; stroke-width: 2; }
.done-kv { max-width: 560px; margin: 0 auto; }
.done-actions { justify-content: center; margin-top: 20px; }
@media (max-width: 1100px) { .cf-groups { grid-template-columns: 1fr; } }
@media (max-width: 900px) {
  .lang-cards { grid-template-columns: 1fr; }
  .wz-card { grid-template-columns: minmax(0, 1fr); }
  .wz-rail { border-right: 0; border-bottom: 1px solid var(--line); padding: 10px 12px; flex-direction: row; align-items: center; gap: 10px; }
  .wz-brand small { display: none; }
  .wz-steps { flex-direction: row; overflow-x: auto; gap: 2px; flex: 1; }
  .wz-steps .st { padding: 4px 6px; }
  .wz-steps .st:not(.cur) .t { display: none; }
}
@media (max-width: 620px) {
  .cf-strip { grid-template-columns: 1fr; }
  .cf-facts .seg { margin-left: 0; }
  .cf-r { grid-template-columns: minmax(0, 1fr) auto; }
  .cf-r .k, .cf-r .e { grid-column: 1 / -1; }
}
@media (max-width: 600px) {
  .wz-wrap { padding: 0; }
  .wz-card { border-radius: 0; border-left: 0; border-right: 0; }
  .wz-brand div { display: none; }
  .fgrid, .hostport, .radio-cards.two, .db-cards { grid-template-columns: 1fr; }
  .ai-block .field { max-width: none; }
  .aitest { grid-template-columns: 1fr; }
  .aitest .btn { grid-row: auto; justify-self: start; }
  .aitest .det { grid-column: 1; }
  .wz-body { padding: 18px 16px; }
  .wz-foot { padding: 12px 16px; }
}
</style>
