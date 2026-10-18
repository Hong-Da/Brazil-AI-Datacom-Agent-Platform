<script setup lang="ts">
/** 工作区左侧：脚本列表（新建 / 改名 / 删除）与项目设置（基线设备与版本）。 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText, get } from '@/api'
import type { Device } from '@/views/devices/logic'
import type { VersionInfo } from '@/views/compare/types'
import { fmtTime } from './logic'
import type { Project, ScriptInfo } from './types'

const props = defineProps<{
  project: Project
  scripts: ScriptInfo[]
  cur: number | null
  dirty: Set<number>
  /** 当前脚本的实时检查计数（优先于保存时的记录） */
  live: { errors: number; warnings: number } | null
}>()
const emit = defineEmits<{
  (e: 'select', id: number): void
  (e: 'new'): void
  (e: 'rename', id: number, name: string): void
  (e: 'delete', s: ScriptInfo): void
  (e: 'baseline', deviceId: number | null, versionId: number | null): void
}>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})

function badge(s: ScriptInfo): { cls: string; n: string } | null {
  const c = s.id === props.cur && props.live ? props.live : s.last_check
  if (!c) return null
  if (c.errors) return { cls: 'e', n: String(c.errors) }
  if (c.warnings) return { cls: 'w', n: String(c.warnings) }
  return { cls: 'ok', n: '✓' }
}

/* 改名 */
const renaming = ref<number | null>(null)
const newName = ref('')
const renameInput = ref<HTMLInputElement[]>()
function startRename(s: ScriptInfo): void {
  renaming.value = s.id
  newName.value = s.name
  void nextTick(() => { renameInput.value?.[0]?.focus(); renameInput.value?.[0]?.select() })
}
function doneRename(ok: boolean): void {
  const id = renaming.value
  renaming.value = null
  const s = props.scripts.find((x) => x.id === id)
  if (ok && s && newName.value.trim() && newName.value.trim() !== s.name) emit('rename', s.id, newName.value.trim())
}

/* 基线 */
const devices = ref<Device[]>([])
const devErr = ref('')
const versions = ref<VersionInfo[]>([])
const devSel = ref<number | null>(props.project.device_id)
const pin = ref(props.project.version_id !== null)
const verSel = ref<number | null>(props.project.version_id)
async function loadDevices(): Promise<void> {
  try { devices.value = (await get<{ devices: Device[] }>('/devices')).devices } catch (e) { devErr.value = errorText(e) }
}
async function loadVersions(id: number | null): Promise<void> {
  versions.value = []
  if (id === null) return
  try { versions.value = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions } catch { /* 没有版本列表时只能跟随最新 */ }
  if (verSel.value === null || !versions.value.some((v) => v.id === verSel.value)) verSel.value = versions.value.find((v) => v.latest)?.id ?? versions.value[0]?.id ?? null
}
void loadDevices()
void loadVersions(devSel.value)
watch(() => [props.project.device_id, props.project.version_id], () => {
  devSel.value = props.project.device_id
  pin.value = props.project.version_id !== null
  if (props.project.version_id !== null) verSel.value = props.project.version_id
})
const latestVer = computed(() => versions.value.find((v) => v.latest) ?? versions.value[0] ?? null)

async function changeDevice(): Promise<void> {
  await loadVersions(devSel.value)
  pin.value = false
  emit('baseline', devSel.value, null)
}
function changePin(v: boolean): void {
  pin.value = v
  if (!v) emit('baseline', devSel.value, null)
  else {
    verSel.value = verSel.value ?? latestVer.value?.id ?? null
    if (verSel.value !== null) emit('baseline', devSel.value, verSel.value)
  }
}
function changeVer(): void { if (pin.value && verSel.value !== null) emit('baseline', devSel.value, verSel.value) }
</script>

<template>
  <div class="col">
    <section class="panel" style="flex: 1">
      <div class="panel-h">
        <h3>{{ T('scripts') }} <span class="faint">{{ scripts.length }}</span></h3>
        <button class="btn btn-sm btn-icon btn-ghost" type="button" :title="T('newScript')" :aria-label="T('newScript')" data-testid="cp-new-script" @click="emit('new')"><Icon name="plus" small /></button>
      </div>
      <div class="sb">
        <div class="scl" data-testid="cp-scripts">
          <div v-if="!scripts.length" class="small faint" style="padding: 10px">{{ T('noScripts') }}</div>
          <div
            v-for="s in scripts" :key="s.id" class="sci" :class="{ 'is-cur': s.id === cur }" tabindex="0" :data-testid="`cp-script-${s.id}`"
            @click="renaming !== s.id && emit('select', s.id)" @keydown.enter.self="emit('select', s.id)"
          >
            <Icon name="file" small />
            <span class="nm">
              <input v-if="renaming === s.id" ref="renameInput" v-model="newName" class="input rn" data-testid="cp-rename-input" @click.stop @keydown.enter="doneRename(true)" @keydown.esc="doneRename(false)" @blur="doneRename(true)">
              <template v-else>{{ s.name }}<span v-if="dirty.has(s.id)" class="dirty" :title="T('unsaved')" /></template>
            </span>
            <span v-if="badge(s)" class="badge" :class="badge(s)!.cls">{{ badge(s)!.n }}</span><span v-else />
            <div class="meta"><span class="typetag" :class="s.kind">{{ s.kind }}</span><span>{{ T('linesN', { n: s.lines }) }}</span><span>#{{ s.revisions }}</span></div>
            <span class="acts">
              <button class="btn btn-xs btn-ghost btn-icon" type="button" :title="T('rename')" :aria-label="T('rename')" data-testid="cp-rename" @click.stop="startRename(s)"><Icon name="pencil" small /></button>
              <button class="btn btn-xs btn-ghost btn-icon" type="button" :title="$t('c.delete')" :aria-label="$t('c.delete')" data-testid="cp-delete-script" @click.stop="emit('delete', s)"><Icon name="trash" small /></button>
            </span>
          </div>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-h"><h3>{{ T('settings') }}</h3></div>
      <div class="pset" data-testid="cp-settings">
        <div class="field">
          <label class="row-k" for="cpDev">{{ T('baseDevice') }}</label>
          <select id="cpDev" v-model="devSel" class="select" @change="changeDevice">
            <option :value="null">{{ T('noBaseline') }}</option>
            <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }} · {{ d.profile }}</option>
          </select>
          <div v-if="devErr" class="small" style="color: var(--red-ink)">{{ devErr }}</div>
        </div>
        <div v-if="devSel !== null" class="radio-line">
          <span class="row-k">{{ T('baseVersion') }}</span>
          <label><input type="radio" name="bv" :checked="!pin" @change="changePin(false)"><span><span>{{ T('latest') }}</span><small v-if="latestVer">#{{ latestVer.seq }} · {{ fmtTime(latestVer.collected_at) }}</small></span></label>
          <label><input type="radio" name="bv" :checked="pin" :disabled="!versions.length" @change="changePin(true)"><span><span>{{ T('pinned') }}</span><small>{{ T('pinnedTip') }}</small></span></label>
          <select v-model="verSel" class="select" :disabled="!pin" :aria-label="T('pinned')" @change="changeVer">
            <option v-for="v in versions" :key="v.id" :value="v.id">#{{ v.seq }} · {{ fmtTime(v.collected_at) || v.source_name }}</option>
          </select>
        </div>
        <dl class="kvs">
          <dt>{{ T('platform') }}</dt><dd class="mono">{{ project.device?.profile || project.profile || '—' }}</dd>
          <dt>{{ T('owner') }}</dt><dd>{{ project.owner?.username || T('ownerToken') }}</dd>
          <dt>{{ T('created') }}</dt><dd>{{ fmtTime(project.created_at) }}</dd>
        </dl>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pset .kvs { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 10px; font-size: 12px; margin: 0; }
.pset .kvs dt { color: var(--ink-3); }
.pset .kvs dd { margin: 0; color: var(--ink); overflow-wrap: anywhere; }
.pset .select { width: 100%; }
</style>
