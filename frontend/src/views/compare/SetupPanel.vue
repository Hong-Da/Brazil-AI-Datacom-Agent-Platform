<script setup lang="ts">
/** 对比对象与选项：两台设备 / 同一设备两个版本 / 粘贴两段配置；跨厂商时显示接口映射表。 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { fmtTime, vendorLabel, type Device } from '@/views/devices/logic'
import InterfaceMap from './InterfaceMap.vue'
import type { MapRow } from './ifmap'
import type { Mode, Setup, SideSel } from './setup'
import type { VersionInfo } from './types'

const props = defineProps<{
  setup: Setup
  devices: Device[]
  versions: Record<number, VersionInfo[]>
  profiles: string[]
  domains: string[]
  mapRows: MapRow[]
  mapShown: boolean
  mapLoading: boolean
  aIfs: string[]
  bIfs: string[]
  running: boolean
  canRun: boolean
}>()
const emit = defineEmits<{
  (e: 'run'): void
  (e: 'swap'): void
  (e: 'mode', m: Mode): void
  (e: 'update:mapRows', v: MapRow[]): void
  (e: 'toggle-map'): void
}>()

const MODES: Mode[] = ['devices', 'versions', 'paste']
const dev = (id: number | null) => props.devices.find((d) => d.id === id) ?? null
const vers = (id: number | null) => (id === null ? [] : props.versions[id] ?? [])
const verLabel = (v: VersionInfo) => `#${v.seq} · ${fmtTime(v.collected_at, true)} · ${v.source_name}`
const crossVendor = computed(() => {
  const a = dev(props.setup.a.device)
  const b = dev(props.setup.b.device)
  return props.setup.mode === 'devices' && !!a && !!b && !!a.vendor && !!b.vendor && a.vendor !== b.vendor
})
const sameVersion = computed(() => props.setup.mode === 'versions' && props.setup.a.version !== null && props.setup.a.version === props.setup.b.version)
const oneVersion = computed(() => props.setup.mode === 'versions' && props.setup.a.device !== null && vers(props.setup.a.device).length === 1)

function sideDevice(k: 'a' | 'b'): Device | null {
  return dev(props.setup.mode === 'versions' ? props.setup.a.device : props.setup[k].device)
}
function sideLines(k: 'a' | 'b'): number | null {
  const s: SideSel = props.setup[k]
  const d = sideDevice(k)
  if (!d) return null
  const v = vers(d.id).find((x) => (s.version === null ? x.latest : x.id === s.version))
  return v?.lines ?? (s.version === null ? d.lines ?? null : null)
}
function setDevice(k: 'a' | 'b', v: string): void {
  const id = v ? Number(v) : null
  if (props.setup.mode === 'versions') {
    props.setup.a.device = id
    props.setup.b.device = id
    props.setup.a.version = null
    props.setup.b.version = null
  } else {
    props.setup[k].device = id
    props.setup[k].version = null
  }
}
function setVersion(k: 'a' | 'b', v: string): void {
  props.setup[k].version = v ? Number(v) : null
}
const mapLabel = (k: 'a' | 'b') => (props.setup.mode === 'paste' ? (k === 'a' ? 'A' : 'B') : sideDevice(k)?.name ?? '')
</script>

<template>
  <section class="panel setup" aria-label="Compare targets" data-testid="compare-setup">
    <div class="panel-h">
      <h2>{{ $t('compare.setupTitle') }}</h2>
      <div class="seg" role="group" data-testid="compare-mode">
        <button v-for="m in MODES" :key="m" type="button" :aria-pressed="setup.mode === m" :data-testid="'mode-' + m" @click="emit('mode', m)">{{ $t('compare.mode.' + m) }}</button>
      </div>
    </div>
    <div class="panel-b">
      <div class="pair">
        <template v-for="k in (['a', 'b'] as const)" :key="k">
          <div class="side" :data-testid="'side-' + k">
            <div class="side-h">
              <span class="badge">{{ k.toUpperCase() }}</span><b>{{ $t(k === 'a' ? 'compare.sideA' : 'compare.sideB') }}</b>
              <span v-if="setup.mode !== 'paste' && sideDevice(k)" class="ml-auto vendor">
                <i :class="sideDevice(k)!.vendor === 'huawei' ? 'hw' : 'cs'">{{ sideDevice(k)!.vendor === 'huawei' ? 'HW' : 'CS' }}</i>{{ vendorLabel(sideDevice(k)!.vendor) }}
              </span>
            </div>

            <template v-if="setup.mode === 'paste'">
              <textarea v-model="setup[k].text" class="textarea mono" spellcheck="false" :placeholder="$t('compare.pastePh')" :data-testid="'paste-' + k" />
              <div class="side-meta">
                <select v-model="setup[k].profile" class="select prof" :data-testid="'profile-' + k">
                  <option value="">{{ $t('compare.profileAuto') }}</option>
                  <option v-for="p in profiles" :key="p" :value="p">{{ p }}</option>
                </select>
                <span v-if="setup[k].text" class="small faint">{{ $t('compare.linesN', { n: setup[k].text.split('\n').length }) }}</span>
              </div>
            </template>

            <template v-else>
              <div class="side-sel">
                <select
                  v-if="setup.mode === 'devices' || k === 'a'" class="select" :value="setup[k].device ?? ''"
                  :aria-label="$t('compare.device')" :data-testid="'device-' + k" @change="setDevice(k, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">{{ $t('compare.pickDevice') }}</option>
                  <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}{{ setup.mode === 'versions' && d.versions > 1 ? ` (${$t('compare.versionsN', { n: d.versions })})` : '' }}</option>
                </select>
                <div v-else class="select static mono" :title="sideDevice(k)?.name">{{ sideDevice(k)?.name ?? '—' }}</div>
                <select
                  class="select" :value="setup[k].version ?? ''" :disabled="!sideDevice(k)"
                  :aria-label="$t('compare.version')" :data-testid="'version-' + k" @change="setVersion(k, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-if="setup.mode === 'devices'" value="">{{ $t('compare.latestVersion') }}</option>
                  <option v-else value="" disabled>{{ $t('compare.version') }}</option>
                  <option v-for="v in vers(sideDevice(k)?.id ?? null)" :key="v.id" :value="v.id">{{ verLabel(v) }}{{ v.latest ? ` · ${$t('compare.latestTag')}` : '' }}</option>
                </select>
              </div>
              <div v-if="sideDevice(k)" class="side-meta">
                <span class="tag mono">{{ sideDevice(k)!.sw_version || '—' }}</span>
                <span class="tag t-teal mono">{{ sideDevice(k)!.profile || '—' }}</span>
                <span v-if="sideLines(k) !== null" class="small faint">{{ $t('compare.linesN', { n: sideLines(k) }) }}</span>
              </div>
            </template>
          </div>
          <div v-if="k === 'a'" class="swapcol">
            <button class="btn btn-icon" :title="$t('compare.swap')" :aria-label="$t('compare.swap')" data-testid="swap" @click="emit('swap')"><Icon name="swap" small /></button>
          </div>
        </template>
      </div>

      <div v-if="setup.mode === 'paste'" class="small faint">{{ $t('compare.pasteHint') }}</div>
      <div v-if="oneVersion" class="notice info"><Icon name="info" /><div class="grow">{{ $t('compare.oneVersion') }}</div></div>
      <div v-else-if="sameVersion" class="notice warn"><Icon name="warn" /><div class="grow">{{ $t('compare.sameVersion') }}</div></div>

      <InterfaceMap
        v-if="crossVendor || (setup.mode === 'paste' && mapShown)"
        :rows="mapRows" :a-ifs="aIfs" :b-ifs="bIfs" :a-label="mapLabel('a')" :b-label="mapLabel('b')" :loading="mapLoading"
        @update:rows="emit('update:mapRows', $event)"
      />

      <div class="opts">
        <span class="fixed-rule" :title="$t('compare.opt.fixedTip')"><Icon name="lock" small /><span>{{ $t('compare.opt.fixed') }}</span></span>
        <span class="fixed-rule" :title="$t('compare.opt.semanticTip')"><Icon name="lock" small /><span>{{ $t('compare.opt.semantic') }}</span></span>
        <label class="check" :title="$t('compare.opt.thresholdTip')">
          <span>{{ $t('compare.opt.threshold') }}</span>
          <input v-model.number="setup.opts.threshold" class="input thr mono" type="number" min="0.5" max="1" step="0.05" data-testid="opt-threshold">
        </label>
        <label class="check"><input v-model="setup.opts.hideIdentity" type="checkbox" data-testid="opt-hide"><span>{{ $t('compare.opt.hide') }}</span></label>
        <label class="check"><input v-model="setup.opts.includeRaw" type="checkbox" data-testid="opt-raw"><span>{{ $t('compare.opt.raw') }}</span></label>
        <label class="check">
          <span>{{ $t('compare.opt.domain') }}</span>
          <select v-model="setup.opts.domain" class="select dom" data-testid="opt-domain">
            <option value="">{{ $t('compare.allDomains') }}</option>
            <option v-for="d in domains" :key="d" :value="d">{{ d }}</option>
          </select>
        </label>
        <button v-if="setup.mode === 'paste'" class="btn btn-sm" :aria-pressed="mapShown" @click="emit('toggle-map')"><Icon name="map" small />{{ $t('compare.map.open') }}</button>
        <span style="flex: 1" />
        <button class="btn btn-primary" :disabled="!canRun || running" data-testid="run-compare" @click="emit('run')">
          <Icon :name="running ? 'refresh' : 'play'" small /><span>{{ running ? $t('compare.running') : $t('compare.run') }}</span>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.setup .panel-b { display: flex; flex-direction: column; gap: 12px; }
.pair { display: grid; grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr); gap: 10px; align-items: stretch; }
.side { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; background: var(--surface-2); min-width: 0; }
.side-h { display: flex; align-items: center; gap: 8px; }
.side-h .badge { width: 22px; height: 22px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; font: 700 12px var(--font-ui); color: var(--ink); background: var(--surface); border: 1.5px solid var(--line-strong); flex: none; }
.side-h b { font-weight: 600; }
.side-sel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr); gap: 8px; }
.side-sel .static { display: flex; align-items: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: var(--surface-3); }
.side-meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.side textarea { min-height: 150px; font-size: 11.5px; white-space: pre; }
.prof { width: auto; height: 26px; }
.swapcol { display: flex; align-items: center; justify-content: center; }
.opts { display: flex; gap: 8px 18px; align-items: center; flex-wrap: wrap; }
.fixed-rule { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); border: 1px dashed var(--line-strong); border-radius: 4px; padding: 2px 8px; cursor: help; }
.fixed-rule :deep(.ico) { color: var(--teal-ink); }
.thr { width: 72px; height: 26px; }
.dom { width: auto; height: 26px; }
@media (max-width: 1100px) {
  .pair { grid-template-columns: minmax(0, 1fr); }
  .swapcol { transform: rotate(90deg); }
}
</style>
