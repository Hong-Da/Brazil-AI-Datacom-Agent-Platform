<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api'
import { LANGS, type Lang } from '@/i18n'
import { usePrefs } from '@/stores/prefs'
import { markConfigured } from '@/router'
import ThemeSwitch from '@/layouts/ThemeSwitch.vue'

interface WField {
  key: string
  kind: string
  default: string | number
  choices: string[]
  min: number | null
  max: number | null
  secret: boolean
  desc: string
}
interface WGroup { id: string; title: string; fields: WField[] }
interface SetupResult { api_token: string; token_generated: boolean; url: string; restart_required: boolean; changed: string[] }

const prefs = usePrefs()
const router = useRouter()
const groups = ref<WGroup[]>([])
const addresses = ref<string[]>([])
const values = reactive<Record<string, string | number>>({})
const errors = reactive<Record<string, string>>({})
const step = ref(0) // 0 = 语言；1..n = 分组；n+1 = 汇总
const loading = ref(true)
const loadError = ref('')
const submitting = ref(false)
const result = ref<SetupResult | null>(null)

const visibleGroups = computed(() => groups.value.map((g) => ({ ...g, fields: g.fields.filter((f) => f.key !== 'ui.language') })).filter((g) => g.fields.length))
const lastStep = computed(() => visibleGroups.value.length + 1)
const current = computed(() => visibleGroups.value[step.value - 1])
const changed = computed(() =>
  groups.value.flatMap((g) => g.fields).filter((f) => String(values[f.key] ?? '') !== String(f.default ?? '')),
)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api<{ groups: WGroup[]; addresses: string[] }>('/setup')
    const keep = { ...values }
    groups.value = data.groups
    addresses.value = data.addresses
    for (const g of data.groups) for (const f of g.fields) values[f.key] = keep[f.key] ?? f.default
    values['ui.language'] = prefs.lang
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
watch(() => prefs.lang, () => { values['ui.language'] = prefs.lang; void load() })

/** 输入即校验：把当前全部取值交给服务端 dry_run，只显示本组字段的错误。 */
async function validate(keys: string[]): Promise<boolean> {
  for (const k of keys) delete errors[k]
  try {
    await api('/setup', { method: 'POST', body: JSON.stringify({ language: prefs.lang, values, dry_run: true }) })
    return true
  } catch (e) {
    if (e instanceof ApiError && e.data && typeof e.data === 'object' && 'errors' in e.data) {
      const errs = (e.data as { errors: Record<string, string> }).errors
      let mine = false
      for (const [k, v] of Object.entries(errs)) if (keys.includes(k)) { errors[k] = v; mine = true }
      return !mine
    }
    loadError.value = (e as Error).message
    return false
  }
}

async function next(): Promise<void> {
  if (current.value && !(await validate(current.value.fields.map((f) => f.key)))) return
  step.value = Math.min(step.value + 1, lastStep.value)
}

async function submit(): Promise<void> {
  submitting.value = true
  try {
    result.value = await api<SetupResult>('/setup', { method: 'POST', body: JSON.stringify({ language: prefs.lang, values }) })
    prefs.token = result.value.api_token
    try { localStorage.setItem('lmesh-token', result.value.api_token) } catch { /* 忽略 */ }
    markConfigured()
  } catch (e) {
    loadError.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}

function display(f: WField): string {
  const v = values[f.key]
  if (f.secret) return v ? '••••••' : '—'
  return v === '' || v === undefined ? '—' : String(v)
}

function setLang(code: Lang): void { prefs.lang = code }
</script>

<template>
  <div class="wizard">
    <header class="head">
      <img src="/favicon.svg" width="36" height="36" alt="" />
      <div>
        <h1>{{ $t('wizard.title') }}</h1>
        <p class="dim">{{ $t('wizard.subtitle') }}</p>
      </div>
      <div class="spacer" />
      <ThemeSwitch />
    </header>

    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" class="gap" />

    <el-card v-if="result" class="body" data-testid="wizard-done">
      <h2>{{ $t('wizard.doneTitle') }}</h2>
      <p>{{ $t('wizard.doneUrl') }} <a :href="result.url" class="mono">{{ result.url }}</a></p>
      <el-alert v-if="result.restart_required" type="warning" :title="$t('wizard.restart')" show-icon :closable="false" />
      <template v-if="result.token_generated">
        <p>{{ $t('wizard.tokenOnce') }}</p>
        <el-input :model-value="result.api_token" readonly class="mono" data-testid="wizard-token" />
      </template>
      <el-button type="primary" class="gap" @click="router.replace('/')">{{ $t('wizard.enter') }}</el-button>
    </el-card>

    <el-card v-else v-loading="loading" class="body">
      <el-steps :active="step" finish-status="success" simple class="steps">
        <el-step :title="$t('wizard.language')" />
        <el-step v-for="g in visibleGroups" :key="g.id" :title="g.title" />
        <el-step :title="$t('wizard.summary')" />
      </el-steps>

      <div v-if="step === 0" class="langs" data-testid="wizard-lang">
        <p>{{ $t('wizard.chooseLanguage') }}</p>
        <el-radio-group :model-value="prefs.lang" @update:model-value="(v: string | number | boolean | undefined) => setLang(v as Lang)">
          <el-radio-button v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</el-radio-button>
        </el-radio-group>
      </div>

      <el-form v-else-if="current" label-position="top" class="form" @submit.prevent>
        <el-form-item v-for="f in current.fields" :key="f.key" :label="f.desc" :error="errors[f.key]">
          <el-select v-if="f.kind === 'host'" v-model="values[f.key]" filterable allow-create :data-testid="`field-${f.key}`" @change="validate([f.key])">
            <el-option v-for="a in addresses" :key="a" :value="a" :label="a" />
          </el-select>
          <el-select v-else-if="f.kind === 'choice'" v-model="values[f.key]" :data-testid="`field-${f.key}`" @change="validate([f.key])">
            <el-option v-for="c in f.choices" :key="c" :value="c" :label="c || $t('wizard.none')" />
          </el-select>
          <el-input-number v-else-if="f.kind === 'int' || f.kind === 'port'" v-model="values[f.key] as number" :min="f.min ?? undefined" :max="f.max ?? undefined"
            :data-testid="`field-${f.key}`" @change="validate([f.key])" />
          <el-input v-else v-model="values[f.key] as string" :type="f.secret ? 'password' : 'text'" :show-password="f.secret"
            :placeholder="f.kind === 'token' ? $t('wizard.tokenAuto') : f.kind === 'dburl' ? $t('wizard.dbSqlite') : ''"
            :data-testid="`field-${f.key}`" @blur="validate([f.key])" />
          <div v-if="f.key === 'server.host' && values[f.key] !== '127.0.0.1'" class="note">{{ $t('wizard.lanNote') }}</div>
        </el-form-item>
      </el-form>

      <div v-else class="summary" data-testid="wizard-summary">
        <p>{{ $t('wizard.summaryHint') }}</p>
        <el-table :data="groups.flatMap((g) => g.fields)" size="small" border>
          <el-table-column prop="key" :label="$t('wizard.key')" width="200" />
          <el-table-column :label="$t('wizard.value')">
            <template #default="{ row }">
              <span class="mono">{{ display(row) }}</span>
              <el-tag v-if="changed.includes(row)" size="small" type="warning" class="tag">{{ $t('wizard.changed') }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="actions">
        <el-button :disabled="step === 0" @click="step--">{{ $t('wizard.prev') }}</el-button>
        <el-button v-if="step < lastStep" type="primary" data-testid="wizard-next" @click="next">{{ $t('wizard.next') }}</el-button>
        <el-button v-else type="primary" :loading="submitting" data-testid="wizard-submit" @click="submit">{{ $t('wizard.confirm') }}</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.wizard { max-width: 860px; margin: 0 auto; padding: 24px 16px; }
.head { display: flex; align-items: center; gap: 12px; }
.head h1 { margin: 0; font-size: 22px; }
.dim { color: var(--lm-text-dim); margin: 2px 0 0; }
.spacer { flex: 1; }
.body { margin-top: 16px; }
.steps { margin-bottom: 20px; }
.langs { padding: 8px 0 16px; }
.form :deep(.el-select), .form :deep(.el-input) { width: 100%; max-width: 520px; }
.note { color: var(--lm-highlight); font-size: 12px; margin-top: 4px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.gap { margin-top: 12px; }
.tag { margin-left: 8px; }
</style>
