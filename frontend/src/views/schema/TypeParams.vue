<script setup lang="ts">
/** Schema 节点表单里随数据类型变化的设置项（M6-9）：integer 取值范围、enum 可选值、object 键与有序、ref 引用目标、格式类型的说明。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { staleFields, type NodeForm } from './form'
import { fieldsFor, isFormatType } from './typefields'

const form = defineModel<NodeForm>('form', { required: true })
const props = defineProps<{
  errors: Record<string, string>
  /** 可作为引用目标的 object 节点 id */
  refOptions: string[]
  /** 打开表单时的类型；换了类型时提供“改回”按钮 */
  origType: string | null
}>()
const emit = defineEmits<{ undo: [] }>()
const { t } = useI18n()

const use = computed(() => fieldsFor(form.value.type))
const stale = computed(() => staleFields(form.value))
const draft = ref('')
const dupHint = ref(false)

function err(k: string): string {
  const key = props.errors[k]
  return key ? t(`schema-edit.${key}`) : ''
}

function addChoice(): void {
  const v = draft.value.trim().replace(/[,|]+$/, '').trim()
  if (!v) return
  if (form.value.choices.includes(v)) { dupHint.value = true; return }
  form.value.choices.push(v)
  draft.value = ''
  dupHint.value = false
}
function onChoiceKey(e: KeyboardEvent): void {
  if (e.key === 'Enter' || e.key === ',' || e.key === '|') { e.preventDefault(); addChoice() }
  else if (e.key === 'Backspace' && !draft.value && form.value.choices.length) form.value.choices.pop()
  else dupHint.value = false
}
function removeChoice(i: number): void {
  form.value.choices.splice(i, 1)
  dupHint.value = false
}
</script>

<template>
  <div class="tparams" data-testid="se-tparams" :data-type="form.type">
    <!-- integer：取值范围两端 -->
    <div v-if="use.includes('range')" class="field">
      <label for="se-rmin">{{ $t('schema-edit.range') }}</label>
      <div class="rng">
        <input id="se-rmin" v-model="form.rangeMin" :class="['input', 'mono', { 'is-error': errors.range }]" inputmode="numeric"
          :placeholder="$t('schema-edit.rangeMin')" :aria-label="$t('schema-edit.rangeMin')" data-testid="se-f-range-min" />
        <span class="faint">–</span>
        <input v-model="form.rangeMax" :class="['input', 'mono', { 'is-error': errors.range }]" inputmode="numeric"
          :placeholder="$t('schema-edit.rangeMax')" :aria-label="$t('schema-edit.rangeMax')" data-testid="se-f-range-max" />
      </div>
      <span v-if="err('range')" class="err" data-testid="se-err-range"><Icon name="err" small />{{ err('range') }}</span>
      <span v-else class="hint">{{ $t('schema-edit.rangeHint') }}</span>
    </div>

    <!-- enum：可选值（标签式输入） -->
    <div v-if="use.includes('choices')" class="field">
      <label for="se-chin">{{ $t('schema-edit.choices') }} <span class="req">*</span></label>
      <div :class="['chips-in', { 'is-error': errors.choices }]" @click="($refs.chin as HTMLInputElement | undefined)?.focus()">
        <span v-for="(c, i) in form.choices" :key="c + i" class="chip-v mono" data-testid="se-f-choice">
          {{ c }}<button type="button" :aria-label="$t('schema-edit.choiceRemove', { v: c })" @click.stop="removeChoice(i)"><Icon name="x" small /></button>
        </span>
        <input id="se-chin" ref="chin" v-model="draft" class="mono" :placeholder="$t('schema-edit.choicesPh')" data-testid="se-f-choices"
          @keydown="onChoiceKey" @blur="addChoice" />
      </div>
      <span v-if="dupHint" class="err"><Icon name="err" small />{{ $t('schema-edit.err.choicesDup') }}</span>
      <span v-else-if="err('choices')" class="err" data-testid="se-err-choices"><Icon name="err" small />{{ err('choices') }}</span>
      <span v-else class="hint">{{ $t('schema-edit.choicesHint') }}</span>
    </div>

    <!-- object：键字段与有序 -->
    <div v-if="use.includes('key')" class="form-grid">
      <div class="field">
        <label for="se-key">{{ $t('schema-edit.key') }}</label>
        <input id="se-key" v-model="form.key" class="input mono" placeholder="name" data-testid="se-f-key" />
        <span class="hint">{{ $t('schema-edit.keyHint') }}</span>
      </div>
      <div class="field ord">
        <label class="check"><span class="switch"><input v-model="form.ordered" type="checkbox" data-testid="se-f-ordered" /><span></span></span>{{ $t('schema-edit.ordered') }}</label>
      </div>
    </div>

    <!-- ref：只能引用 object 节点 -->
    <div v-if="use.includes('ref')" class="field">
      <label for="se-ref">{{ $t('schema-edit.ref') }} <span class="req">*</span></label>
      <select id="se-ref" v-model="form.ref" :class="['select', 'mono', { 'is-error': errors.ref }]" data-testid="se-f-ref">
        <option value="">{{ $t('schema-edit.refNone') }}</option>
        <option v-for="id in refOptions" :key="id" :value="id">{{ id }}</option>
      </select>
      <span v-if="err('ref')" class="err" data-testid="se-err-ref"><Icon name="err" small />{{ err('ref') }}</span>
      <span v-else class="hint">{{ $t('schema-edit.refHint') }}</span>
    </div>

    <!-- 格式类型：只有说明 -->
    <div v-if="isFormatType(form.type)" class="fmt" data-testid="se-fmt">
      <Icon name="info" small />
      <div>
        <b>{{ $t(`schema-edit.fmt.${form.type}`) }}</b>
        <div class="small muted">{{ $t('schema-edit.fmtEgLabel') }} <code>{{ $t(`schema-edit.fmtEg.${form.type}`) }}</code>{{ $t('schema-edit.fmtNote') }}</div>
      </div>
    </div>
    <div v-else-if="!use.length" class="small faint" data-testid="se-tp-none">{{ $t('schema-edit.tpNone') }}</div>

    <div v-if="stale.length" class="notice warn mt12" data-testid="se-stale">
      <Icon name="warn" />
      <div class="grow small">
        {{ $t('schema-edit.stale', { type: form.type }) }}<b>{{ stale.map((k) => $t(`schema-edit.tf.${k}`)).join($t('schema-edit.listSep')) }}</b>
      </div>
      <button v-if="origType && origType !== form.type" type="button" class="btn btn-xs" data-testid="se-stale-undo" @click="emit('undo')">
        {{ $t('schema-edit.staleUndo', { type: origType }) }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.tparams { border: 1px dashed var(--line-strong); border-radius: 6px; padding: 10px 12px; background: var(--surface-2); display: flex; flex-direction: column; gap: 10px; }
.rng { display: flex; align-items: center; gap: 8px; }
.rng .input { width: 130px; }
.chips-in { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-height: 34px; padding: 4px 6px; border: 1px solid var(--line-strong); border-radius: var(--r-ctl); background: var(--surface); cursor: text; }
.chips-in:focus-within { outline: 2px solid var(--focus); outline-offset: -1px; }
.chips-in.is-error { border-color: var(--red); }
.chips-in input { border: 0; outline: 0; background: transparent; color: var(--ink); flex: 1; min-width: 140px; font-size: 13px; height: 24px; }
.chip-v { display: inline-flex; align-items: center; gap: 2px; padding: 0 2px 0 8px; height: 24px; border-radius: 4px; background: var(--blue-soft); color: var(--blue-ink); border: 1px solid var(--blue-line); font-size: 12px; }
.chip-v button { border: 0; background: transparent; color: inherit; cursor: pointer; display: inline-flex; padding: 2px; }
.ord { justify-content: flex-end; }
.fmt { display: flex; gap: 10px; align-items: flex-start; color: var(--ink); }
.fmt code { font-family: var(--font-mono); }
.req { color: var(--red-ink); }
.notice { align-items: center; }
</style>
