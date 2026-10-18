<script setup lang="ts">
/** 检查目标：已导入的设备（取最新版本）或粘贴的配置文本。状态放在 report.ts 的 target，两页共用。 */
import { computed } from 'vue'
import type { Device } from '../devices/logic'
import { target } from './report'

const props = defineProps<{ devices: Device[]; profile?: string | null; kbVersion?: string | null; family?: string | null }>()
const emit = defineEmits<{ change: [] }>()

const dev = computed(() => props.devices.find((d) => d.id === target.deviceId) ?? null)
const vendor = computed(() => {
  const v = (dev.value?.vendor || props.family || props.profile || '').toLowerCase()
  if (v.startsWith('huawei')) return { cls: 'hw', abbr: 'HW', name: 'Huawei' }
  if (v.startsWith('cisco')) return { cls: 'cs', abbr: 'CS', name: 'Cisco' }
  return null
})

function setMode(m: 'device' | 'text'): void {
  if (target.mode === m) return
  target.mode = m
  emit('change')
}
function pick(e: Event): void {
  const v = (e.target as HTMLSelectElement).value
  target.deviceId = v ? Number(v) : null
  emit('change')
}
</script>

<template>
  <div class="ck-target" data-testid="check-target">
    <span class="seg" role="group">
      <button type="button" :aria-pressed="target.mode === 'device'" data-testid="mode-device" @click="setMode('device')">{{ $t('check.modeDevice') }}</button>
      <button type="button" :aria-pressed="target.mode === 'text'" data-testid="mode-text" @click="setMode('text')">{{ $t('check.modeText') }}</button>
    </span>
    <select v-if="target.mode === 'device'" class="select" :value="target.deviceId ?? ''" :aria-label="$t('check.deviceLabel')" data-testid="device-select" @change="pick">
      <option value="" disabled>{{ $t('check.pickDevice') }}</option>
      <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }} · {{ $t('check.latestVersion') }}</option>
    </select>
    <span v-if="vendor" class="vendor"><i :class="vendor.cls">{{ vendor.abbr }}</i>{{ vendor.name }}</span>
    <span v-if="profile" class="tag t-teal mono">{{ profile }}</span>
    <span v-if="kbVersion" class="tag mono">KB {{ kbVersion }}</span>
  </div>
  <div v-if="target.mode === 'text'" class="ck-text">
    <textarea v-model="target.text" class="textarea mono" rows="6" :aria-label="$t('check.textLabel')" :placeholder="$t('check.textPh')" data-testid="config-text" />
    <p class="small faint">{{ $t('check.textHint') }}</p>
  </div>
</template>

<style scoped>
.ck-target { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.ck-target .select { width: auto; height: 28px; max-width: 100%; }
.ck-target .seg button { height: 28px; }
.ck-text { margin-top: 8px; max-width: 900px; display: flex; flex-direction: column; gap: 4px; }
</style>
