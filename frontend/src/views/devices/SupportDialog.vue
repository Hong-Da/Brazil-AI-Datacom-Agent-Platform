<script setup lang="ts">
/**
 * 设备页“申请支持此型号”（REQ-044）：POST /devices/{id}/support-request {model, reason}；后端附上设备信息与
 * 未识别行的前 20 种写法，进审核队列（类型“建议”），提出人在“我的建议”里看到处理结果。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import { pct } from './model'
import type { ProjectDevice } from './project'

const props = defineProps<{ device: ProjectDevice }>()
const emit = defineEmits<{ close: []; done: [msg: string] }>()
const { t } = useI18n()
const model = ref('')
const reason = ref('')
const saving = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  if (!model.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    const r = await post<{ id: number }>(`/devices/${props.device.id}/support-request`, { model: model.value.trim(), reason: reason.value.trim() })
    emit('done', t('model.supDone', { id: r.id }))
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && !saving.value) emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-back" data-testid="support-dialog" @click.self="!saving && emit('close')">
    <div class="modal" style="width: min(640px, 100%)" role="dialog" aria-modal="true" aria-labelledby="sdT">
      <div class="modal-h">
        <h2 id="sdT">{{ $t('model.supTitle') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" :disabled="saving" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b">
        <dl class="kv">
          <dt>{{ $t('model.ms.device') }}</dt><dd>{{ device.name }}</dd>
          <dt>{{ $t('model.ms.vendorVer') }}</dt><dd>{{ device.vendor || $t('devices.vendorUnknown') }} · {{ device.sw_version || '—' }}</dd>
          <dt>{{ $t('model.ms.profileThen') }}</dt><dd>{{ device.profile || '—' }} · {{ $t(`model.src.${device.profile_source || 'auto'}`) }}</dd>
          <dt>{{ $t('model.ms.unknown') }}</dt><dd>{{ device.unknown ?? '—' }} ({{ pct(device.unknown_ratio) }})</dd>
        </dl>
        <div class="field mt12">
          <label for="sdModel">{{ $t('model.fModel') }}</label>
          <input id="sdModel" v-model="model" class="input" :placeholder="$t('model.fModelPh')" maxlength="200" data-testid="support-model">
        </div>
        <div class="field mt8">
          <label for="sdReason">{{ $t('model.fReason') }}</label>
          <textarea id="sdReason" v-model="reason" class="textarea" rows="3" maxlength="4000" data-testid="support-reason" />
        </div>
        <p class="small faint mt8">{{ $t('model.supNote') }}</p>
        <div v-if="error" class="notice err mt8"><Icon name="err" /><div class="grow">{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" :disabled="saving" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="saving || !model.trim()" data-testid="support-submit" @click="submit"><Icon name="send" small />{{ $t('model.supGo') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kv { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 14px; margin: 0; font-size: 13px; }
.kv dt { color: var(--ink-3); }
.kv dd { margin: 0; font-family: var(--font-mono); font-size: 12.5px; }
</style>
