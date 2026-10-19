<script setup lang="ts">
/**
 * 对知识库提建议（REQ-036，预览 DevelopDocs/ui-preview/M6/kb.html 的“提建议”对话框）：POST /kb/suggestions，
 * 带上当前项目（只作参考）。提交后进入审核队列（类型 suggestion），由维护员处理。
 */
import { onMounted, reactive, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import { useProject } from '@/stores/project'
import { buildPayload, SUGGEST_KINDS, type SuggestKind } from '@/views/kbsugg/logic'

const props = defineProps<{ target: string; current?: string | null; kind?: SuggestKind }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'submitted', id: number): void }>()
const project = useProject()

const form = reactive({
  target: props.target,
  kind: props.kind ?? ('default' as SuggestKind),
  current: props.current ?? '',
  proposed: '',
  reason: '',
})
const busy = ref(false)
const error = ref('')
const reasonEl = ref<HTMLTextAreaElement | null>(null)
onMounted(() => reasonEl.value?.focus())

async function submit(): Promise<void> {
  const { body, missing } = buildPayload(form, project.slug)
  if (!body) { error.value = missing.length ? 'required' : ''; return }
  busy.value = true
  error.value = ''
  try {
    const r = await post<{ id: number }>('/kb/suggestions', body)
    emit('submitted', r.id)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="kb-suggest-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" style="width: min(600px, 100%)" role="dialog" aria-modal="true" aria-labelledby="kbsgT">
      <div class="modal-h">
        <h2 id="kbsgT">{{ $t('kbsugg.title') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b">
        <div class="form-grid">
          <div class="field span2">
            <label for="kbsgTarget">{{ $t('kbsugg.target') }}</label>
            <input id="kbsgTarget" v-model="form.target" class="input mono" data-testid="kb-suggest-target">
          </div>
          <div class="field">
            <label for="kbsgKind">{{ $t('kbsugg.kind') }}</label>
            <select id="kbsgKind" v-model="form.kind" class="select" data-testid="kb-suggest-kind">
              <option v-for="k in SUGGEST_KINDS" :key="k" :value="k">{{ $t(`kbsugg.kind.${k}`) }}</option>
            </select>
          </div>
          <div class="field">
            <label for="kbsgCur">{{ $t('kbsugg.current') }}</label>
            <input id="kbsgCur" v-model="form.current" class="input mono">
          </div>
          <div class="field span2">
            <label for="kbsgNew">{{ $t('kbsugg.proposed') }}</label>
            <input id="kbsgNew" v-model="form.proposed" class="input mono" data-testid="kb-suggest-proposed">
          </div>
          <div class="field span2">
            <label for="kbsgWhy">{{ $t('kbsugg.reason') }} *</label>
            <textarea id="kbsgWhy" ref="reasonEl" v-model="form.reason" class="textarea" rows="3" :placeholder="$t('kbsugg.reasonPh')" data-testid="kb-suggest-reason" />
          </div>
        </div>
        <div v-if="error" class="notice err mt12" data-testid="kb-suggest-error"><Icon name="err" /><div>{{ error === 'required' ? $t('kbsugg.required') : error }}</div></div>
      </div>
      <div class="modal-f">
        <span class="small faint" style="margin-right: auto">{{ $t('kbsugg.queueNote') }}</span>
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="busy" data-testid="kb-suggest-submit" @click="submit">{{ busy ? $t('kbsugg.submitting') : $t('kbsugg.submit') }}</button>
      </div>
    </div>
  </div>
</template>
