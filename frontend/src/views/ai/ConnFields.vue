<script setup lang="ts">
/** 接口表单的字段：类型、地址、API Key（只显示是否已设置）、默认模型、各用途模型；管理员接口另有名称与公共、启用开关。
 *  管理员的“添加 / 编辑接口”对话框与“我的 AI”的个人接口共用。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { PROVIDERS, TASKS, needsBaseUrl, usesKey, type ConnForm, type Problem } from './logic'

const props = defineProps<{
  form: ConnForm
  keySet: boolean
  problems: Partial<Record<'name' | 'base_url' | 'model' | 'api_key', Problem>>
  withName?: boolean
  withFlags?: boolean
  tid: string // data-testid 前缀
}>()
const keyInput = defineModel<string>('keyInput', { required: true })
const clearKey = defineModel<boolean>('clearKey', { required: true })
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`ai-settings.${k}`, p ?? {})
const LOGO: Record<string, string> = { anthropic: 'A', openai: 'OA', local: 'L' }
const err = (k: 'name' | 'base_url' | 'model' | 'api_key') => (props.problems[k] ? T(props.problems[k] as string) : '')
const urlPh = computed(() => (props.form.provider === 'local' ? 'http://127.0.0.1:11434/v1' : props.form.provider === 'openai' ? 'https://…/v1' : 'https://api.anthropic.com'))
const keyPh = computed(() => (props.keySet && !clearKey.value ? T('keySetPh') : usesKey(props.form.provider) ? T('keyPh') : T('keyLocalPh')))
</script>

<template>
  <div class="form-grid cf">
    <div v-if="withName" class="field">
      <label :for="`${tid}-name`">{{ T('name') }}</label>
      <input :id="`${tid}-name`" v-model="form.name" class="input" :class="{ 'is-error': err('name') }" maxlength="64" spellcheck="false" :data-testid="`${tid}-name`">
      <span v-if="err('name')" class="err"><Icon name="err" small />{{ err('name') }}</span>
      <span v-else class="hint">{{ T('nameHint') }}</span>
    </div>
    <div class="field" :class="{ span2: !withName }">
      <label :for="`${tid}-model`">{{ T('model') }}</label>
      <input :id="`${tid}-model`" v-model="form.model" class="input mono" :class="{ 'is-error': err('model') }" spellcheck="false" :data-testid="`${tid}-model`">
      <span v-if="err('model')" class="err"><Icon name="err" small />{{ err('model') }}</span>
    </div>
    <div class="field span2">
      <span class="field-label">{{ T('type') }}</span>
      <div class="ptypes" role="radiogroup" :data-testid="`${tid}-provider`">
        <label v-for="p in PROVIDERS" :key="p" class="radio-card">
          <span class="head">
            <input v-model="form.provider" type="radio" :name="`${tid}-provider`" :value="p" :data-testid="`${tid}-provider-${p}`">
            <span class="lg" :class="p">{{ LOGO[p] }}</span>
            <span class="rc-t">{{ T(`p_${p}`) }}</span>
          </span>
        </label>
      </div>
    </div>
    <div class="field span2">
      <label :for="`${tid}-url`">{{ T('baseUrl') }}</label>
      <input :id="`${tid}-url`" v-model="form.base_url" class="input mono" :class="{ 'is-error': err('base_url') }" :placeholder="urlPh" spellcheck="false" :data-testid="`${tid}-url`">
      <span v-if="err('base_url')" class="err"><Icon name="err" small />{{ err('base_url') }}</span>
      <span v-else class="hint">{{ needsBaseUrl(form.provider) ? T('baseUrlNeed') : T('baseUrlOpt') }}</span>
    </div>
    <div class="field span2">
      <label :for="`${tid}-key`">API Key</label>
      <div class="keyrow">
        <input :id="`${tid}-key`" v-model="keyInput" type="password" autocomplete="new-password" class="input" :class="{ 'is-error': err('api_key') }" :placeholder="keyPh" :data-testid="`${tid}-key`" @input="clearKey = false">
        <span v-if="keySet && !clearKey" class="tag pass nowrap" :data-testid="`${tid}-key-set`"><Icon name="lock" small />{{ T('keySetTag') }}</span>
        <span v-else-if="clearKey" class="tag t-amber nowrap">{{ T('keyWillClear') }}</span>
        <button v-if="keySet" type="button" class="btn" :data-testid="`${tid}-key-clear`" @click="clearKey = !clearKey; keyInput = ''">{{ clearKey ? T('keyKeep') : T('keyClear') }}</button>
      </div>
      <span v-if="err('api_key')" class="err"><Icon name="err" small />{{ err('api_key') }}</span>
      <span class="enc"><Icon name="lock" small />{{ T('keyNote') }}</span>
    </div>
    <div class="field span2">
      <span class="field-label">{{ T('taskModels') }}</span>
      <div class="task-models">
        <label v-for="k in TASKS" :key="k">
          <span>{{ T(`task_${k}`) }}</span>
          <input v-model="form[`model_${k}`]" class="input mono" :placeholder="T('useDefault')" spellcheck="false" :data-testid="`${tid}-model-${k}`">
        </label>
      </div>
    </div>
    <div v-if="withFlags" class="field span2 flags">
      <label class="check"><span class="switch"><input v-model="form.public" type="checkbox" :data-testid="`${tid}-public`"><span /></span><span>{{ T('publicLabel') }}</span></label>
      <label class="check"><span class="switch"><input v-model="form.enabled" type="checkbox" :data-testid="`${tid}-enabled`"><span /></span><span>{{ T('enabledLabel') }}</span></label>
    </div>
  </div>
</template>

<style scoped>
.keyrow { display: flex; gap: 6px; align-items: center; }
.keyrow .input { flex: 1; min-width: 0; font-family: var(--font-mono); letter-spacing: .04em; }
.enc { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--teal-ink); }
.ptypes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 6px; }
.ptypes .radio-card { padding: 8px 10px; align-items: center; }
.ptypes .head { display: flex; gap: 8px; align-items: center; }
.lg { width: 22px; height: 22px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; font: 700 9.5px var(--font-ui); color: var(--surface); flex: none; }
.lg.anthropic { background: var(--amber-ink); }
.lg.openai { background: var(--blue-ink); }
.lg.local { background: var(--ink-2); }
.task-models { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; margin-top: 6px; }
.task-models label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--ink-2); }
.task-models .input { height: 30px; font-size: 12px; }
.flags { display: flex; flex-direction: column; gap: 8px; }
@media (max-width: 760px) { .cf { grid-template-columns: minmax(0, 1fr); } .cf .span2 { grid-column: auto; } .ptypes, .task-models { grid-template-columns: minmax(0, 1fr); } }
</style>
