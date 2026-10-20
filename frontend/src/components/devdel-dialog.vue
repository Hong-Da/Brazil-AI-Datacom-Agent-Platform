<script setup lang="ts">
/**
 * 删除设备 / 删除单个配置版本的确认框（REQ-038，预览 DevelopDocs/ui-preview/M6/devices.html 的删除确认框）：
 * 打开时取 GET /devices/{id}/delete-preview，列出连带删除的内容与受影响的配置检查项目和脚本；
 * 有项目以它为基线时需要勾选“仍然删除”（force）；最后一个版本不能单独删除。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { del, errorText, get } from '@/api'
import { canConfirm, deletePath, planDelete, projectList, type DeletePreview } from '@/views/devices/deleteLogic'
import NetChip from '@/components/net-chip.vue'
import type { NetBrief } from '@/views/networks/logic'

const props = defineProps<{ deviceId: number; versionId?: number | null }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'deleted', result: Record<string, unknown>, message: string): void }>()
const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`devdel.${k}`, p ?? {})

const vid = computed(() => props.versionId ?? null)
const pv = ref<DeletePreview | null>(null)
const loadError = ref('')
const error = ref('')
const busy = ref(false)
const force = ref(false)

async function load(): Promise<void> {
  loadError.value = ''
  try {
    pv.value = await get<DeletePreview>(`/devices/${props.deviceId}/delete-preview`)
  } catch (e) {
    loadError.value = errorText(e)
  }
}
onMounted(load)

const plan = computed(() => (pv.value ? planDelete(pv.value, vid.value) : null))
const title = computed(() => {
  const name = pv.value?.device.name ?? `#${props.deviceId}`
  return vid.value === null ? T('titleDevice', { name }) : T('titleVersion', { name, seq: plan.value?.version?.seq ?? vid.value })
})
const ok = computed(() => !!plan.value && canConfirm(plan.value, force.value) && !busy.value)
// M9：设备在哪些网络里（删除设备后从这些网络里一起移出）
const nets = computed(() => (pv.value as (DeletePreview & { networks?: NetBrief[] }) | null)?.networks ?? [])

async function confirm(): Promise<void> {
  if (!plan.value || !pv.value || !ok.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await del<Record<string, unknown>>(deletePath(props.deviceId, vid.value, force.value))
    const cleared = (r.baseline_cleared as unknown[] | undefined)?.length ?? 0
    let msg = vid.value === null
      ? T('deletedDevice', { name: pv.value.device.name, n: pv.value.counts.versions })
      : T('deletedVersion', { seq: plan.value.version?.seq ?? '', latest: String(r.latest_version_id ?? '') })
    if (cleared && vid.value === null) msg += `；${T('clearedProjects', { n: cleared })}`
    emit('deleted', r, msg)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-back" data-testid="devdel-modal" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal devdel" role="dialog" aria-modal="true" aria-labelledby="devdelT">
      <div class="modal-h">
        <h2 id="devdelT">{{ title }}</h2>
        <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <div class="modal-b">
        <div v-if="loadError" class="notice err"><Icon name="err" /><div class="grow">{{ loadError }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
        <p v-else-if="!plan" class="faint">{{ $t('c.loading') }}</p>
        <template v-else>
          <div v-if="plan.lastVersion" class="notice warn" data-testid="devdel-last"><Icon name="warn" /><div>{{ T('lastVersion') }}</div></div>
          <template v-else>
            <div class="impact" data-testid="devdel-impact">
              <div v-for="r in plan.rows" :key="r.label" :class="r.kind">
                <Icon :name="r.kind === 'del' ? 'trash' : r.icon" small />
                <span>{{ T(r.label) }}</span>
                <b>{{ r.n ?? '' }}</b>
              </div>
            </div>
            <div v-if="plan.blockers.length" class="notice warn mt12" data-testid="devdel-baseline">
              <Icon name="warn" />
              <div class="grow">
                <div>{{ plan.mode === 'device' ? T('baselineDevice', { n: plan.blockers.length, s: plan.blockers.reduce((a, p) => a + p.scripts.length, 0) }) : T('baselineVersion', { n: plan.blockers.length }) }}</div>
                <div class="mono small plist">{{ projectList(plan.blockers) }}</div>
                <div class="small">{{ plan.mode === 'device' ? T('baselineAfterDevice') : T('baselineAfterVersion') }}</div>
                <label class="check mt8"><input v-model="force" type="checkbox" data-testid="devdel-force"> <span>{{ plan.mode === 'device' ? T('forceDevice') : T('forceVersion') }}</span></label>
              </div>
            </div>
            <div v-if="plan.moved.length && plan.nextLatest" class="notice info mt12" data-testid="devdel-moved">
              <Icon name="info" />
              <div class="grow">
                <div>{{ T('moved', { n: plan.moved.length, seq: plan.nextLatest.seq }) }}</div>
                <div class="mono small plist">{{ projectList(plan.moved) }}</div>
              </div>
            </div>
            <div v-if="vid === null && nets.length > 1" class="notice warn mt12" data-testid="devdel-networks">
              <Icon name="warn" />
              <div class="grow small">
                <b>{{ $t('net.d.delIn') }}</b>
                <div class="nw-chips" style="margin: 6px 0"><NetChip v-for="n in nets" :key="n.id" :net="n" /></div>
                {{ $t('net.d.delNote') }}
              </div>
            </div>
            <p class="small faint mt8">{{ T('logged') }}</p>
          </template>
          <div v-if="error" class="notice err mt12" data-testid="devdel-error"><Icon name="err" /><div class="grow">{{ error }}</div></div>
        </template>
      </div>
      <div class="modal-f">
        <button class="btn" type="button" @click="emit('close')">{{ $t('c.cancel') }}</button>
        <button v-if="!plan?.lastVersion" class="btn btn-danger-solid" type="button" :disabled="!ok" data-testid="devdel-ok" @click="confirm">
          <Icon name="trash" small />{{ busy ? T('deleting') : vid === null ? T('deleteDevice') : T('deleteVersion') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.devdel { width: min(560px, 100%); }
.impact { border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.impact > div { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 7px 10px; border-top: 1px solid var(--line); font-size: 12.5px; }
.impact > div:first-child { border-top: 0; }
.impact :deep(.ico) { color: var(--ink-3); }
.impact .del :deep(.ico) { color: var(--red-ink); }
.impact .keep :deep(.ico) { color: var(--teal-ink); }
.impact b { font-weight: 600; font-variant-numeric: tabular-nums; }
.plist { margin: 4px 0; word-break: break-word; }
.btn-danger-solid:disabled { opacity: .5; cursor: not-allowed; }
</style>
