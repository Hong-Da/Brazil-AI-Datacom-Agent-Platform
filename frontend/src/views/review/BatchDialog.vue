<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, post, errorText } from '@/api'
import Icon from '@/components/Icon.vue'
import { APPROVABLE, sortedKinds } from './logic'

const props = defineProps<{ counts: Record<string, number>; initialKind: string }>()
const emit = defineEmits<{ close: []; done: [approved: number] }>()

const kinds = computed(() => sortedKinds(props.counts).filter((k) => APPROVABLE.has(k)))
const kind = ref(kinds.value.includes(props.initialKind) ? props.initialKind : kinds.value[0] ?? 'card')
const contains = ref('')
const rules = ref('')
const extractors = ref<{ name: string; family: string }[]>([])
const step = ref<'form' | 'confirm' | 'running' | 'result'>('form')
const result = ref<{ approved: number; failed: number } | null>(null)
const error = ref('')

onMounted(async () => {
  try { extractors.value = (await get<{ extractors: { name: string; family: string }[] }>('/kb/extractors')).extractors } catch { /* 没有规则列表时仍可按类型和关键字批量 */ }
})

async function run(): Promise<void> {
  step.value = 'running'
  error.value = ''
  try {
    result.value = await post<{ approved: number; failed: number }>('/review/batch', {
      kind: kind.value,
      contains: contains.value.trim() || null,
      rules: kind.value === 'card' && rules.value ? rules.value : null,
    })
    step.value = 'result'
    emit('done', result.value.approved)
  } catch (e) {
    error.value = errorText(e)
    step.value = 'confirm'
  }
}
</script>

<template>
  <div class="modal-back" data-testid="review-batch-dialog" @click.self="step !== 'running' && emit('close')">
    <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true">
      <div class="modal-h">
        <h2>{{ $t('review.batchTitle') }}</h2>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="$t('c.close')" :disabled="step === 'running'" @click="emit('close')"><Icon name="x" small /></button>
      </div>
      <div class="modal-b">
        <template v-if="step === 'form'">
          <p class="small muted">{{ $t('review.batchSub') }}</p>
          <div class="form-grid mt12">
            <div class="field"><label>{{ $t('review.type') }}</label>
              <select v-model="kind" class="select" data-testid="batch-kind">
                <option v-for="k in kinds" :key="k" :value="k">{{ $t(`review.kind_${k}`) }}（{{ counts[k] }}）</option>
              </select></div>
            <div v-if="kind === 'card'" class="field"><label>{{ $t('review.rulesLabel') }}</label>
              <select v-model="rules" class="select mono" data-testid="batch-rules">
                <option value="">{{ $t('review.anyRules') }}</option>
                <option v-for="x in extractors" :key="x.name" :value="x.name">{{ x.name }}</option>
              </select></div>
            <div class="field span2"><label>{{ $t('review.containsLabel') }}</label>
              <input v-model="contains" class="input mono" :placeholder="$t('review.containsPh')" data-testid="batch-contains" /></div>
          </div>
        </template>
        <template v-else-if="step === 'confirm' || step === 'running'">
          <div class="notice warn"><Icon name="warn" /><div class="grow small">{{ $t('review.batchWarn', { n: counts[kind] ?? 0 }) }}</div></div>
          <dl class="kv mt12 small">
            <dt>{{ $t('review.type') }}</dt><dd>{{ $t(`review.kind_${kind}`) }}</dd>
            <dt>{{ $t('review.containsLabel') }}</dt><dd class="mono">{{ contains.trim() || $t('review.anyText') }}</dd>
            <template v-if="kind === 'card'"><dt>{{ $t('review.rulesLabel') }}</dt><dd class="mono">{{ rules || $t('review.anyRules') }}</dd></template>
          </dl>
          <div v-if="step === 'running'" class="mt12"><div class="progress striped"><i style="width: 100%" /></div><p class="small faint mt8">{{ $t('review.batchRunning') }}</p></div>
          <div v-if="error" class="notice err mt12"><Icon name="err" /><div class="grow small">{{ error }}</div></div>
        </template>
        <template v-else-if="result">
          <div :class="['notice', result.failed ? 'warn' : 'ok']"><Icon :name="result.failed ? 'warn' : 'ok'" />
            <div class="grow small">{{ $t('review.batchResult', { ok: result.approved, failed: result.failed }) }}</div></div>
        </template>
      </div>
      <div class="modal-f">
        <template v-if="step === 'form'">
          <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="!kinds.length" data-testid="batch-next" @click="step = 'confirm'">{{ $t('c.next') }}</button>
        </template>
        <template v-else-if="step === 'confirm' || step === 'running'">
          <button class="btn" type="button" :disabled="step === 'running'" @click="step = 'form'">{{ $t('c.back') }}</button>
          <button class="btn btn-primary" type="button" :disabled="step === 'running'" data-testid="batch-confirm" @click="run">
            <Icon name="check" small />{{ $t('review.batchGo') }}
          </button>
        </template>
        <button v-else class="btn btn-primary" type="button" @click="emit('close')">{{ $t('c.close') }}</button>
      </div>
    </div>
  </div>
</template>
