<script setup lang="ts">
/** 新建配置检查项目：名称、说明、基线设备与版本（默认跟随最新）、默认脚本类型、顺序核查、AI 一起校验（AI 已配置时）。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import { errorText, get, post } from '@/api'
import type { Device } from '@/views/devices/logic'
import type { VersionInfo } from '@/views/compare/types'
import { fmtTime } from './logic'
import type { Kind, Project } from './types'

const props = defineProps<{ aiConfigured: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', p: Project): void }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})

const name = ref('')
const desc = ref('')
const devices = ref<Device[] | null>(null)
const devErr = ref('')
const devId = ref<number | null>(null)
const verMode = ref<'latest' | 'pin'>('latest')
const versions = ref<VersionInfo[]>([])
const verId = ref<number | null>(null)
const kind = ref<Kind>('change')
const order = ref(true)
const ai = ref(false)
const nameErr = ref(false)
const busy = ref(false)
const err = ref('')
const nameInput = ref<HTMLInputElement>()

async function loadDevices(): Promise<void> {
  devErr.value = ''
  try {
    devices.value = (await get<{ devices: Device[] }>('/devices')).devices
    if (devices.value.length && devId.value === null) devId.value = devices.value[0].id
  } catch (e) { devErr.value = errorText(e) }
}
watch(devId, async (id) => {
  versions.value = []
  verId.value = null
  if (id === null) return
  try {
    versions.value = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions
    verId.value = versions.value[0]?.id ?? null
  } catch { versions.value = [] }
})
const curDev = computed(() => devices.value?.find((d) => d.id === devId.value) ?? null)

async function create(): Promise<void> {
  if (!name.value.trim()) { nameErr.value = true; nameInput.value?.focus(); return }
  busy.value = true
  err.value = ''
  try {
    const p = await post<Project>('/check-projects', {
      name: name.value.trim(),
      description: desc.value,
      device_id: devId.value,
      version_id: verMode.value === 'pin' ? verId.value : null,
      default_kind: kind.value,
      order_check: order.value,
      ai_check: props.aiConfigured && ai.value,
      ai_rules: [],
    })
    emit('created', p)
  } catch (e) { err.value = errorText(e) } finally { busy.value = false }
}

function onKey(e: KeyboardEvent): void { if (e.key === 'Escape') emit('close') }
onMounted(() => { void loadDevices(); void nextTick(() => nameInput.value?.focus()) })
</script>

<template>
  <div class="modal-back" data-testid="cp-new-modal" @click.self="emit('close')" @keydown="onKey">
    <div class="modal np" role="dialog" aria-modal="true" aria-labelledby="npTitle">
      <div class="modal-h">
        <h2 id="npTitle">{{ T('newTitle') }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b" style="display: flex; flex-direction: column; gap: 14px">
        <div class="form-grid">
          <div class="field span2">
            <label for="npName">{{ T('name') }}</label>
            <input id="npName" ref="nameInput" v-model="name" class="input" :class="{ 'is-error': nameErr }" :placeholder="T('namePh')" data-testid="cp-new-name" @input="nameErr = false" @keydown.enter="create">
            <div v-if="nameErr" class="err"><Icon name="warn" small /><span>{{ T('nameRequired') }}</span></div>
          </div>
          <div class="field span2">
            <label for="npDesc">{{ T('desc') }}</label>
            <textarea id="npDesc" v-model="desc" class="textarea" rows="2" :placeholder="T('descPh')" />
          </div>
        </div>
        <div class="field">
          <span class="field-label">{{ T('baseDevice') }}</span>
          <div v-if="devErr" class="notice err"><Icon name="err" /><div class="grow">{{ devErr }}</div><button class="btn btn-sm" type="button" @click="loadDevices">{{ $t('c.retry') }}</button></div>
          <div v-else-if="devices === null" class="small faint">{{ $t('c.loading') }}</div>
          <div v-else-if="!devices.length" class="notice info"><Icon name="info" /><div>{{ T('noDevices') }} <router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link></div></div>
          <div v-else class="devopt" data-testid="cp-new-devices">
            <label v-for="d in devices" :key="d.id" class="radio-card">
              <input v-model="devId" type="radio" name="dev" :value="d.id" :data-testid="`cp-new-dev-${d.name}`">
              <div>
                <div class="rc-t"><DevChip :name="d.name" :vendor="d.vendor || d.profile" /></div>
                <div class="rc-d">{{ d.profile }} · {{ T('versionsN', { n: d.versions }) }}</div>
              </div>
            </label>
          </div>
        </div>
        <div v-if="curDev" class="field">
          <span class="field-label">{{ T('baseVersion') }}</span>
          <div class="vrow"><label class="check"><input v-model="verMode" type="radio" value="latest"><span>{{ T('latestLong') }}</span></label></div>
          <div class="vrow">
            <label class="check"><input v-model="verMode" type="radio" value="pin" :disabled="!versions.length"><span>{{ T('pinned') }}</span></label>
            <select v-model="verId" class="select" :disabled="verMode !== 'pin'" :aria-label="T('pinned')">
              <option v-for="v in versions" :key="v.id" :value="v.id">#{{ v.seq }} · {{ fmtTime(v.collected_at) || v.source_name }}{{ v.latest ? ` · ${T('latest')}` : '' }}</option>
            </select>
          </div>
        </div>
        <div class="form-grid">
          <div class="field">
            <span class="field-label">{{ T('defaultKind') }}</span>
            <div class="radio-cards">
              <label class="radio-card"><input v-model="kind" type="radio" value="change"><div><div class="rc-t">{{ T('kind.change') }}</div><div class="rc-d">{{ T('kindDesc.change') }}</div></div></label>
              <label class="radio-card"><input v-model="kind" type="radio" value="full"><div><div class="rc-t">{{ T('kind.full') }}</div><div class="rc-d">{{ T('kindDesc.full') }}</div></div></label>
            </div>
          </div>
          <div class="field">
            <span class="field-label">{{ T('checkOptions') }}</span>
            <label class="check" style="align-items: flex-start"><span class="switch"><input v-model="order" type="checkbox"><span /></span><span><span>{{ T('orderDefault') }}</span><br><small class="faint">{{ T('orderDefaultTip') }}</small></span></label>
            <label v-if="aiConfigured" class="check mt8" style="align-items: flex-start"><span class="switch"><input v-model="ai" type="checkbox"><span /></span><span><span>{{ T('aiCheck') }}</span><br><small class="faint">{{ T('aiCheckTip') }}</small></span></label>
          </div>
        </div>
        <div v-if="err" class="notice err"><Icon name="err" /><div>{{ err }}</div></div>
      </div>
      <div class="modal-f">
        <span class="small faint" style="margin-right: auto">{{ T('onlyYou') }}</span>
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="busy" data-testid="cp-new-create" @click="create">{{ T('createProject') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal.np { width: min(720px, 100%); max-height: calc(100vh - 40px); overflow: auto; }
.devopt { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; max-height: 240px; overflow: auto; }
.devopt .radio-card { padding: 8px 10px; }
.devopt .rc-d { font-size: 11.5px; }
.vrow { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.vrow + .vrow { margin-top: 6px; }
.vrow .select { width: 260px; }
</style>
