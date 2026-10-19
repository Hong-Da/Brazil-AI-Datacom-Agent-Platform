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
  blocksOf, confirmRows, confirmStats, displayHost, displayValue, groupErrors, initialValues, labelKey, LANG_NOTES, pickErrors,
  visibleGroups, type Running, type Values, type WField, type WGroup,
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
  if (f.key === 'ai.provider') return providerLabel(String(values[f.key] ?? ''))
  if (f.kind === 'bool') return t(String(values[f.key]) === 'true' ? 'wizard.on' : 'wizard.off')
  if (v !== null) return v
  if (f.kind === 'dburl') return t('wizard.dbSqliteValue')
  if (f.kind === 'token') return t('wizard.tokenAutoValue')
  return t('wizard.notSet')
}

/** 默认值的显示文字（“默认：9090”）。 */
function defaultText(f: WField): string {
  if (f.key === 'ai.provider') return providerLabel(String(f.default ?? ''))
  if (f.kind === 'bool') return t(String(f.default) === 'true' ? 'wizard.on' : 'wizard.off')
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
        <div class="wz-intro">
          <!-- eslint-disable-next-line vue/no-v-html -->
          <span class="wz-logo" v-html="LOGO_SVG" />
          <div>
            <h1>{{ $t('wizard.title') }}</h1>
            <p class="muted">{{ $t('wizard.subtitle') }}</p>
          </div>
        </div>

        <div class="wz-card">
          <div v-if="shown.length" class="steps" data-testid="wizard-steps">
            <div v-for="(title, i) in stepTitles" :key="i" :class="['st', { done: result || i < step, cur: !result && i === step }]">
              <span class="no"><Icon v-if="result || i < step" name="check" small /><template v-else>{{ i + 1 }}</template></span>
              <span>{{ title }}</span>
            </div>
          </div>

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
                <h2>{{ $t('wizard.langTitle') }}</h2>
                <p class="lead">{{ $t('wizard.langLead') }}</p>
                <div class="radio-cards lang-cards" role="radiogroup" data-testid="wizard-lang">
                  <label v-for="l in LANGS" :key="l.code" class="radio-card">
                    <input type="radio" name="lang" :value="l.code" :checked="prefs.lang === l.code" @change="setLang(l.code)" />
                    <span class="ln">{{ l.label }}</span>
                    <span class="ls">{{ LANG_NOTES[l.code] }}</span>
                  </label>
                </div>
                <div class="section-t mt16">{{ $t('wizard.themeTitle') }}</div>
                <p class="small muted">{{ $t('wizard.themeHint') }}</p>
              </template>

              <!-- 设置分组：字段来自 GET /setup -->
              <template v-else-if="current">
                <h2>{{ current.title }}</h2>
                <p v-if="te(`wizard.lead_${current.id}`)" class="lead">{{ $t(`wizard.lead_${current.id}`) }}</p>
                <div class="blocks">
                  <template v-for="b in blocks" :key="b.type === 'hostport' ? b.host.key : b.field.key">
                    <div v-if="b.type === 'hostport'">
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

                    <div v-else-if="b.type === 'dburl'">
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

                    <div v-else-if="b.type === 'ai'">
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
                      <div>
                        <div class="section-t">{{ $t('wizard.tokenUsage') }}</div>
                        <pre class="block">curl -H "Authorization: Bearer {{ $t('wizard.tokenPlaceholder') }}" http://{{ usageHost }}/api/v1/summary</pre>
                        <div class="notice warn mt12"><Icon name="key" /><div class="grow small">{{ $t('wizard.tokenNote') }}</div></div>
                      </div>
                    </template>
                  </template>
                  <div v-if="isAiStep && aiOn" class="notice info"><Icon name="shield" /><div class="grow small">{{ $t('wizard.aiNote') }}</div></div>
                </div>
              </template>

              <!-- 管理员账号（REQ-030） -->
              <template v-else-if="step === adminStep">
                <h2>{{ $t('wizard.adminTitle') }}</h2>
                <p class="lead">{{ $t('wizard.adminLead') }}</p>
                <div class="blocks admin-blocks" data-testid="wizard-admin">
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
                  <div class="notice info"><Icon name="shield" /><div class="grow small">{{ $t('wizard.adminNote') }}</div></div>
                </div>
              </template>

              <!-- 确认（M6-9）：按组汇总、突出改动、统一校验、写入路径与需重启的项 -->
              <template v-else>
                <h2>{{ $t('wizard.confirmTitle') }}</h2>
                <p class="lead">{{ $t('wizard.cfLead') }}</p>
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
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wz-page { display: flex; flex-direction: column; background: var(--bg); }
.wz-wrap { flex: 1; display: flex; justify-content: center; padding: 28px 16px 40px; }
.wz { width: min(880px, 100%); }
.wz-intro { display: flex; gap: 16px; align-items: center; margin-bottom: 16px; }
.wz-logo { display: contents; }
.wz-logo :deep(svg) { width: 52px; height: 52px; flex: none; }
.wz-intro h1 { font-size: 22px; }
.wz-card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.wz-card .steps { padding: 14px 20px; border-bottom: 1px solid var(--line); background: var(--surface-2); }
.wz-card .steps .st span:last-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wz-body { padding: 22px 24px; min-height: 380px; }
.wz-body h2 { font-size: 17px; margin-bottom: 4px; }
.wz-body .lead { color: var(--ink-2); margin-bottom: 18px; max-width: 70ch; }
.wz-foot { display: flex; gap: 8px; align-items: center; padding: 12px 24px; border-top: 1px solid var(--line); }
.wz-foot .grow { flex: 1; }
.blocks { display: flex; flex-direction: column; gap: 16px; max-width: 640px; }
.admin-blocks { max-width: 520px; }
.lang-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.lang-cards .radio-card { flex-direction: column; gap: 6px; padding: 14px; position: relative; }
.lang-cards .ln { font: 600 16px var(--font-display); }
.lang-cards .ls { color: var(--ink-2); font-size: 12px; }
.lang-cards input { position: absolute; opacity: 0; }
.lang-cards .radio-card:has(input:focus-visible) { outline: 2px solid var(--focus); }
.radio-cards.two, .db-cards { grid-template-columns: 1fr 1fr; }
.rc-t .tag { margin-left: 6px; }
.hostport { display: grid; grid-template-columns: minmax(0, 1fr) 140px; gap: 12px; }
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
.cf-groups { display: flex; flex-direction: column; gap: 10px; }
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
@media (max-width: 900px) {
  .lang-cards, .radio-cards.two, .db-cards { grid-template-columns: 1fr; }
  .wz-card .steps .st span:last-child { display: none; }
}
@media (max-width: 620px) {
  .cf-strip { grid-template-columns: 1fr; }
  .cf-facts .seg { margin-left: 0; }
  .cf-r { grid-template-columns: minmax(0, 1fr) auto; }
  .cf-r .k, .cf-r .e { grid-column: 1 / -1; }
}
@media (max-width: 520px) {
  .hostport { grid-template-columns: 1fr; }
  .wz-body { padding: 18px 16px; }
  .wz-foot { padding: 12px 16px; }
}
</style>
