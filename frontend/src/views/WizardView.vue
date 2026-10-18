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
  blocksOf, displayHost, displayValue, initialValues, isChanged, labelKey, LANG_NOTES, pickErrors, visibleGroups,
  type Values, type WField, type WGroup,
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
    const data = await api<{ groups: WGroup[]; addresses: string[] }>('/setup')
    groups.value = data.groups
    addresses.value = data.addresses
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

async function next(): Promise<void> {
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
  step.value = Math.min(step.value + 1, lastStep.value)
}

function back(): void {
  submitError.value = ''
  step.value = Math.max(0, step.value - 1)
}

async function submit(): Promise<void> {
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
  if (v !== null) return v
  if (f.kind === 'dburl') return t('wizard.dbSqliteValue')
  if (f.kind === 'token') return t('wizard.tokenAutoValue')
  return t('wizard.notSet')
}

function summaryFields(g: WGroup): WField[] {
  if (g.fields.some((f) => f.key === 'ai.provider') && !values['ai.provider']) return []
  return g.fields
}

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

              <!-- 确认 -->
              <template v-else>
                <h2>{{ $t('wizard.confirmTitle') }}</h2>
                <p class="lead">{{ $t('wizard.confirmLead') }}</p>
                <div class="sum" data-testid="wizard-summary">
                  <section class="panel">
                    <div class="panel-h"><h3>{{ $t('wizard.stepLanguage') }}</h3><button type="button" class="btn btn-xs btn-ghost" @click="step = 0">{{ $t('c.edit') }}</button></div>
                    <div class="panel-b"><dl class="kv"><dt>{{ $t('wizard.language') }}</dt><dd>{{ langLabel }}</dd></dl></div>
                  </section>
                  <section v-for="(g, gi) in shown" :key="g.id" class="panel" :data-testid="`wizard-sum-${g.id}`">
                    <div class="panel-h"><h3>{{ g.title }}</h3><button type="button" class="btn btn-xs btn-ghost" @click="step = gi + 1">{{ $t('c.edit') }}</button></div>
                    <div class="panel-b">
                      <dl class="kv">
                        <template v-if="summaryFields(g).length">
                          <template v-for="f in summaryFields(g)" :key="f.key">
                            <dt>{{ label(f) }}</dt>
                            <dd>
                              <span :class="{ mono: f.kind !== 'choice' && displayValue(f, values[f.key]) !== null, faint: displayValue(f, values[f.key]) === null }">{{ summaryText(f) }}</span>
                              <span v-if="isChanged(f, values[f.key]) && !f.secret" class="tag t-amber chg">{{ $t('wizard.changed') }}</span>
                            </dd>
                          </template>
                        </template>
                        <template v-else>
                          <dt>{{ label(g.fields[0]) }}</dt>
                          <dd><span class="tag">{{ $t('wizard.aiOff') }}</span></dd>
                        </template>
                      </dl>
                    </div>
                  </section>
                  <section class="panel" data-testid="wizard-sum-admin">
                    <div class="panel-h"><h3>{{ $t('wizard.stepAdmin') }}</h3><button type="button" class="btn btn-xs btn-ghost" @click="step = adminStep">{{ $t('c.edit') }}</button></div>
                    <div class="panel-b"><dl class="kv"><dt>{{ $t('wizard.adminName') }}</dt><dd class="mono">{{ admin.username }}</dd><dt>{{ $t('wizard.adminPassword') }}</dt><dd>••••••••</dd></dl></div>
                  </section>
                </div>
              </template>

              <div v-if="submitError" class="notice err mt16" role="alert" data-testid="wizard-error"><Icon name="err" /><div class="grow small">{{ submitError }}</div></div>
            </div>

            <div class="wz-foot">
              <button v-if="step > 0" type="button" class="btn" data-testid="wizard-back" @click="back">{{ $t('c.back') }}</button>
              <span class="grow small faint">{{ step < lastStep ? $t('wizard.stepOf', { n: step + 1, total: lastStep + 1 }) : '' }}</span>
              <button v-if="step === lastStep" type="button" class="btn btn-primary" :disabled="submitting" data-testid="wizard-submit" @click="submit">
                <Icon name="check" small />{{ submitting ? $t('c.loading') : $t('wizard.save') }}
              </button>
              <button v-else type="button" class="btn btn-primary" data-testid="wizard-next" @click="next">
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
.sum { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.sum .panel-h { min-height: 38px; padding: 8px 12px; }
.sum .panel-b { padding: 10px 12px; }
.chg { margin-left: 6px; }
.done { padding: 20px 0 16px; }
.done-art { width: 64px; height: 64px; border-radius: 50%; background: var(--teal-soft); color: var(--teal-ink); display: flex; align-items: center; justify-content: center; }
.done-art :deep(.ico) { width: 30px; height: 30px; stroke-width: 2; }
.done-kv { max-width: 560px; margin: 0 auto; }
.done-actions { justify-content: center; margin-top: 20px; }
@media (max-width: 900px) {
  .lang-cards, .sum, .radio-cards.two, .db-cards { grid-template-columns: 1fr; }
  .wz-card .steps .st span:last-child { display: none; }
}
@media (max-width: 520px) {
  .hostport { grid-template-columns: 1fr; }
  .wz-body { padding: 18px 16px; }
  .wz-foot { padding: 12px 16px; }
}
</style>
