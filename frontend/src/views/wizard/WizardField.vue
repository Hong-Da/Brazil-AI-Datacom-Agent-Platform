<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { coerce, labelKey, type WField } from './wizard'

const props = defineProps<{
  field: WField
  modelValue: string | number | undefined
  error?: string
  ok?: string
  addresses?: string[]
  placeholder?: string
  hint?: string
  choices?: string[]
  optionLabel?: (c: string) => string
}>()
const emit = defineEmits<{ 'update:modelValue': [v: string | number]; commit: [] }>()
const { t, te } = useI18n()

const id = computed(() => `wf-${props.field.key.replace(/\./g, '-')}`)
const label = computed(() => (te(labelKey(props.field.key)) ? t(labelKey(props.field.key)) : props.field.desc))
// 有短标签时，后端的说明文字作为提示显示在输入框下方
const hintText = computed(() => props.hint ?? (te(labelKey(props.field.key)) && props.field.desc !== label.value ? props.field.desc : ''))
const reveal = ref(false)
const password = computed(() => props.field.secret && props.field.kind !== 'dburl')
const text = computed(() => (props.modelValue === undefined || props.modelValue === null ? '' : String(props.modelValue)))

function onInput(e: Event): void {
  emit('update:modelValue', coerce(props.field, (e.target as HTMLInputElement).value))
}
function optLabel(c: string): string {
  if (props.optionLabel) return props.optionLabel(c)
  if (props.field.kind === 'bool') return t(c === 'true' ? 'wizard.on' : 'wizard.off') // 开关：true / false
  return c || t('wizard.none')
}
</script>

<template>
  <div class="field">
    <label :for="id">{{ label }}</label>
    <select v-if="field.kind === 'choice' || field.kind === 'bool'" :id="id" class="select" :value="text" :data-testid="`field-${field.key}`"
      @change="onInput($event); emit('commit')">
      <option v-for="c in choices ?? field.choices" :key="c" :value="c">{{ optLabel(c) }}</option>
    </select>
    <div v-else class="wf-input">
      <input :id="id" :class="['input', 'mono', { 'is-error': error, 'is-ok': !error && ok }]" :value="text"
        :type="password && !reveal ? 'password' : 'text'" :list="field.kind === 'host' && addresses?.length ? `${id}-list` : undefined"
        :inputmode="field.kind === 'int' || field.kind === 'port' ? 'numeric' : undefined" :placeholder="placeholder"
        autocomplete="off" spellcheck="false" :aria-invalid="!!error" :data-testid="`field-${field.key}`"
        @input="onInput" @change="emit('commit')" />
      <button v-if="password" type="button" class="btn btn-sm btn-ghost btn-icon reveal" :aria-pressed="reveal"
        :title="$t(reveal ? 'wizard.hide' : 'wizard.show')" :aria-label="$t(reveal ? 'wizard.hide' : 'wizard.show')" @click="reveal = !reveal">
        <Icon name="eye" small />
      </button>
      <datalist v-if="field.kind === 'host' && addresses?.length" :id="`${id}-list`">
        <option v-for="a in addresses" :key="a" :value="a" />
      </datalist>
    </div>
    <span v-if="error" class="err" role="alert"><Icon name="err" small />{{ error }}</span>
    <span v-else-if="ok" class="okmsg"><Icon name="ok" small />{{ ok }}</span>
    <span v-if="hintText" class="hint">{{ hintText }}</span>
  </div>
</template>

<style scoped>
.wf-input { position: relative; display: flex; align-items: center; }
.wf-input .input { width: 100%; }
.wf-input .reveal { position: absolute; right: 3px; }
.wf-input .reveal[aria-pressed="true"] { color: var(--teal-ink); }
.wf-input:has(.reveal) .input { padding-right: 34px; }
</style>
