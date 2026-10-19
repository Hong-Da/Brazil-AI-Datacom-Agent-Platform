<script setup lang="ts">
/**
 * 把设备复制到我的另一个项目（REQ-035）：目标项目是我能修改的项目（属主或可编辑成员），
 * 调 POST /projects/<目标>/devices/copy-in；只复制当前版本，同名时后端自动改名。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, post } from '@/api'
import { useProject, type ProjectRow } from '@/stores/project'

const props = defineProps<{ deviceId: number; deviceName: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'done', msg: string): void }>()
const { t } = useI18n()
const project = useProject()

const targets = ref<ProjectRow[]>([])
const target = ref('')
const name = ref('')
const busy = ref(false)
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const l = await project.loadLists()
    targets.value = [...l.mine, ...l.shared].filter((p) => p.slug !== project.slug && (p.role === 'owner' || p.role === 'edit'))
    target.value = targets.value[0]?.slug ?? ''
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
})
const ok = computed(() => !!target.value && !busy.value)

async function submit(): Promise<void> {
  if (!ok.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await post<{ name?: string; renamed?: boolean }>(`/projects/${encodeURIComponent(target.value)}/devices/copy-in`, {
      device_id: props.deviceId,
      name: name.value.trim() || null,
    })
    const newName = r.name ?? props.deviceName
    const p = targets.value.find((x) => x.slug === target.value)
    emit('done', t('devices.copiedTo', { d: newName, p: p?.name ?? target.value }))
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="copyto-modal" @click.self="emit('close')">
    <div class="modal" style="width: min(480px, 100%)" role="dialog" aria-modal="true" aria-labelledby="ctT">
      <div class="modal-h">
        <h2 id="ctT">{{ $t('devices.copyToTitle', { d: deviceName }) }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b" style="display: flex; flex-direction: column; gap: 12px">
        <p v-if="loading" class="faint">{{ $t('c.loading') }}</p>
        <div v-else-if="!targets.length" class="notice info"><Icon name="info" /><div>{{ $t('devices.copyToNone') }}</div></div>
        <template v-else>
          <label class="field">
            <span class="field-label">{{ $t('devices.copyToProject') }}</span>
            <select v-model="target" class="select" data-testid="copyto-target">
              <option v-for="p in targets" :key="p.slug" :value="p.slug">{{ p.name }} ({{ p.slug }})</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">{{ $t('devices.copyToName') }}</span>
            <input v-model="name" class="input" :placeholder="deviceName" data-testid="copyto-name">
          </label>
          <p class="small faint">{{ $t('devices.copyToNote') }}</p>
        </template>
        <div v-if="error" class="notice err"><Icon name="err" /><div>{{ error }}</div></div>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="!ok" data-testid="copyto-ok" @click="submit"><Icon name="copy" small />{{ $t('devices.copyToOk') }}</button>
      </div>
    </div>
  </div>
</template>
