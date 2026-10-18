<script setup lang="ts">
/**
 * 校验配置页签：选设备 / 版本或粘贴配置 → POST /templates/check → 符合与否、逐项原因、提取的变量与块实例、配置原文中的标记。
 * 模板正在编辑且有未保存的修改时，用编辑中的模板文件校验。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import M3Code from '@/components/m3-code.vue'
import TermName from '@/components/term-name.vue'
import { errorText, get, post } from '@/api'
import { saveText, toCsv } from '@/views/profiles/csv'
import type { Device } from '@/views/devices/logic'
import type { VersionInfo } from '@/views/compare/types'
import { splitLines, type CodeLine } from '@/views/m3/code'
import { msg, show } from '@/views/m3/texts'
import { badVars, bodyLines, findClass, findingText, flattenRow, instanceRows, kindCounts, lineMarks, paramColumns, type FindClass } from './logic'
import type { CheckResult, Finding, TemplateDetail } from './types'

const props = defineProps<{ detail: TemplateDetail; devices: Device[]; yaml: string; dirty: boolean }>()
const router = useRouter()
const { t, locale } = useI18n()
const lang = computed(() => String(locale.value))

const mode = ref<'device' | 'paste'>('device')
const deviceId = ref<number | null>(null)
const versionId = ref<number | null>(null)
const versions = ref<VersionInfo[]>([])
const pasteText = ref('')
const pasteLabel = ref('')

/** 默认选同一平台族的第一台设备 */
const famDevices = computed(() => props.devices.filter((d) => d.profile && (props.detail.profiles.length ? props.detail.profiles.includes(d.profile) : true)))
watch(() => [props.detail.id, props.devices.length], () => {
  if (deviceId.value === null || !props.devices.some((d) => d.id === deviceId.value)) {
    const fam = props.detail.family.split('-')[0]
    deviceId.value = (props.devices.find((d) => d.vendor === fam) ?? famDevices.value[0] ?? props.devices[0])?.id ?? null
  }
}, { immediate: true })
watch(deviceId, async (id) => {
  versions.value = []
  versionId.value = null
  if (id === null) return
  try {
    versions.value = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions
  } catch { /* 用最新版本 */ }
}, { immediate: true })

const running = ref(false)
const err = ref('')
const res = ref<CheckResult | null>(null)
const text = ref('')
const kf = ref<FindClass | ''>('')
const selF = ref<number | null>(null)
const selInst = ref<string | null>(null)
watch(() => props.detail.id, () => { res.value = null; err.value = '' })

async function run(): Promise<void> {
  running.value = true
  err.value = ''
  selF.value = null
  selInst.value = null
  const body: Record<string, unknown> = props.dirty ? { template: props.yaml } : { template_id: props.detail.id }
  try {
    if (mode.value === 'device') {
      if (deviceId.value === null) return
      body.device_id = deviceId.value
      if (versionId.value !== null) body.version_id = versionId.value
      const vid = versionId.value ?? versions.value.find((v) => v.latest)?.id ?? null
      const [r, src] = await Promise.all([
        post<CheckResult>('/templates/check', body),
        vid !== null ? get<{ text: string }>(`/devices/${deviceId.value}/versions/${vid}/text`).catch(() => ({ text: '' })) : Promise.resolve({ text: '' }),
      ])
      res.value = r
      text.value = src.text
    } else {
      body.text = pasteText.value
      if (pasteLabel.value.trim()) body.label = pasteLabel.value.trim()
      res.value = await post<CheckResult>('/templates/check', body)
      text.value = pasteText.value
    }
  } catch (e) {
    err.value = errorText(e)
    res.value = null
  } finally {
    running.value = false
  }
}

const findings = computed(() => res.value?.findings ?? [])
const counts = computed(() => kindCounts(findings.value))
const shownF = computed(() => findings.value.map((f, i) => ({ f, i })).filter((x) => !kf.value || findClass(x.f) === kf.value))
const bad = computed(() => badVars(findings.value))
const tplLines = computed(() => bodyLines(props.detail.body))
const tplText = (n: number) => tplLines.value[n - 1]?.text ?? ''
const instances = computed(() => instanceRows(res.value?.blocks ?? {}))
const baseVars = computed(() => Object.entries(res.value?.variables ?? {}))

const selLines = computed<number[]>(() => {
  if (selF.value !== null) return findings.value[selF.value]?.lines ?? []
  if (selInst.value) return instances.value.find((x) => `${x.block}#${x.i}` === selInst.value)?.lines ?? []
  return []
})
const code = computed<CodeLine[]>(() => {
  const marks = lineMarks(findings.value)
  const linked = new Set(selLines.value)
  const inst = new Set(instances.value.flatMap((x) => x.lines))
  return splitLines(text.value).map((s, i) => ({
    no: i + 1, text: s,
    cls: [marks.get(i + 1) ?? (inst.has(i + 1) ? 'c-inst' : ''), linked.has(i + 1) ? 'linked' : '', /^\s*[!#]/.test(s) ? 'c-cmt' : ''].join(' '),
  }))
})
const pane = ref<InstanceType<typeof M3Code>>()
watch(selLines, (ls) => { if (ls.length) setTimeout(() => pane.value?.scrollToIndex(Math.min(...ls) - 1)) })

function pickLine(i: number): void {
  const n = i + 1
  const k = findings.value.findIndex((f) => f.lines.includes(n))
  if (k >= 0) {
    selF.value = k
    selInst.value = null
    return
  }
  const inst = instances.value.find((x) => x.lines.includes(n))
  selF.value = null
  selInst.value = inst ? `${inst.block}#${inst.i}` : null
}
function toggleKf(k: FindClass): void {
  kf.value = kf.value === k ? '' : k
}
const KLABEL: Record<FindClass, string> = { missing: 'templates.kMissing', violation: 'templates.kViolation', extra: 'templates.kExtra', info: 'templates.kInfo' }
const kindName = (f: Finding) => t(`templates.fk.${f.kind}`)

// ---------------- 变量导出与加入批量生成 ----------------
const cols = computed(() => paramColumns(props.detail.vars, props.detail.blocks))
const flat = computed(() => (res.value ? flattenRow(res.value.row, cols.value, props.detail.blocks) : {}))
function exportCsv(): void {
  if (!res.value) return
  saveText(`vars-${res.value.device}.csv`, toCsv([cols.value, cols.value.map((c) => flat.value[c] ?? '')]))
}
function toGenerate(): void {
  if (!res.value) return
  try { sessionStorage.setItem('lmesh-gen-import', JSON.stringify({ template: props.detail.id, row: flat.value })) } catch { /* 不可用时只跳转 */ }
  void router.push({ name: 'generate', query: { template: props.detail.id, from: 'check' } })
}
</script>

<template>
  <div>
    <div class="chk-setup" data-testid="tpl-check-setup">
      <span class="small muted">{{ $t('templates.ckTarget') }}</span>
      <div class="seg" role="group">
        <button type="button" :aria-pressed="mode === 'device'" @click="mode = 'device'">{{ $t('templates.ckDevice') }}</button>
        <button type="button" :aria-pressed="mode === 'paste'" data-testid="tpl-ck-paste" @click="mode = 'paste'">{{ $t('templates.ckPaste') }}</button>
      </div>
      <template v-if="mode === 'device'">
        <select v-model="deviceId" class="select" data-testid="tpl-ck-device" :aria-label="$t('templates.ckDevice')">
          <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }} · {{ d.profile }}</option>
        </select>
        <select v-model="versionId" class="select" data-testid="tpl-ck-version" :aria-label="$t('templates.ckVersion')">
          <option :value="null">{{ $t('templates.latest') }}</option>
          <option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.seq }} · {{ v.source_name }}</option>
        </select>
      </template>
      <input v-else v-model="pasteLabel" class="input" style="width: 180px" :placeholder="$t('templates.ckLabel')">
      <span v-if="dirty" class="tag t-amber">{{ $t('templates.ckUnsaved') }}</span>
      <span class="ml-auto" />
      <button class="btn btn-primary btn-sm" type="button" :disabled="running || (mode === 'device' ? deviceId === null : !pasteText.trim())" data-testid="tpl-ck-run" @click="run"><Icon name="play" small />{{ running ? $t('templates.ckRunning') : $t('templates.ckRun') }}</button>
    </div>
    <textarea v-if="mode === 'paste'" v-model="pasteText" class="input mono paste" rows="8" :placeholder="$t('templates.ckPastePh')" data-testid="tpl-ck-text" />

    <div v-if="err" class="notice err" style="margin-bottom: 12px" data-testid="tpl-ck-error"><Icon name="err" /><div class="grow">{{ err }}</div></div>
    <div v-if="!res && !err" class="empty"><Icon name="shield" /><h3>{{ $t('templates.ckEmpty') }}</h3><p>{{ $t('templates.ckEmptyText') }}</p></div>

    <template v-if="res">
      <div class="ksum" data-testid="tpl-ck-sum">
        <span class="verdict" :class="res.compliant ? 'good' : 'bad'" data-testid="tpl-ck-verdict"><Icon :name="res.compliant ? 'ok' : 'err'" />{{ res.compliant ? $t('templates.compliant') : $t('templates.notCompliant') }}</span>
        <span class="small muted">{{ $t('templates.matchedN', { n: res.summary.matched, m: res.summary.patterns }) }}</span>
        <button v-for="k in (['violation', 'missing', 'extra', 'info'] as FindClass[])" :key="k" type="button" :aria-pressed="kf === k" :data-testid="`tpl-kf-${k}`" @click="toggleKf(k)">
          <span class="rk" :class="k">{{ $t(KLABEL[k]) }}</span><b>{{ counts[k] }}</b>
        </button>
        <span class="ml-auto small faint">{{ res.device }} · {{ res.profile }} · {{ res.template.id }} v{{ res.template.version }}</span>
      </div>
      <div v-for="(n, i) in [...res.notes, ...res.warnings]" :key="i" class="notice info" style="margin-bottom: 10px"><Icon name="info" /><div>{{ msg(String(n.key), n, lang) }}</div></div>

      <div class="ck">
        <div class="stack" style="gap: 12px">
          <div class="m3box">
            <div class="m3box-h"><h3>{{ $t('templates.findings') }}</h3><span class="faint">{{ findings.length }}</span></div>
            <div v-if="!findings.length" class="notice ok" style="margin: 10px"><Icon name="ok" /><div>{{ $t('templates.allMatch', { n: res.summary.matched }) }}</div></div>
            <div
              v-for="x in shownF" :key="x.i" class="ki" :class="[findClass(x.f), { 'is-sel': selF === x.i }]" data-testid="tpl-finding"
              @click="selF = selF === x.i ? null : x.i; selInst = null"
            >
              <div class="kh">
                <span class="rk" :class="findClass(x.f)">{{ kindName(x.f) }}</span>
                <span v-if="x.f.var" class="vx">{{ x.f.var }}</span>
                <span v-if="x.f.block" class="small faint">{{ x.f.block }}<template v-if="x.f.instance"> #{{ x.f.instance }}</template></span>
                <span class="ml-auto small faint">{{ x.f.schema }}</span>
              </div>
              <div class="km">{{ findingText(x.f, lang) }}</div>
              <div v-if="x.f.actual_node || x.f.node" class="kn"><TermName :id="x.f.actual_node || x.f.parent || x.f.node || ''" /></div>
              <template v-if="selF === x.i">
                <div v-if="x.f.node" class="kr">{{ $t('templates.pattern') }}: {{ x.f.node }}</div>
                <div v-if="x.f.parent" class="kr">{{ $t('templates.under') }}: {{ x.f.parent }}</div>
                <div v-for="n in x.f.template_lines" :key="n" class="kr">{{ $t('templates.tplLine', { n }) }}: {{ tplText(n) }}</div>
                <div v-if="x.f.lines.length" class="kr">{{ $t('templates.cfgLines') }}: {{ x.f.lines.join(', ') }}</div>
              </template>
            </div>
          </div>

          <div class="m3box">
            <div class="m3box-h">
              <h3>{{ $t('templates.extracted') }}</h3>
              <span class="ml-auto" />
              <button class="btn btn-xs" type="button" data-testid="tpl-xv-csv" @click="exportCsv"><Icon name="download" small />CSV</button>
              <button class="btn btn-xs" type="button" data-testid="tpl-to-gen" @click="toGenerate"><Icon name="rows" small />{{ $t('templates.toGen') }}</button>
            </div>
            <div class="tbl-wrap">
              <table class="tbl compact xv-t" data-testid="tpl-xv">
                <thead><tr><th>{{ $t('templates.vName') }}</th><th>{{ $t('templates.value') }}</th><th /></tr></thead>
                <tbody>
                  <tr v-for="[k, v] in baseVars" :key="k">
                    <td><span class="vname">{{ k }}</span></td>
                    <td><span class="val" :class="{ bad: bad.has(k) }">{{ v === null ? $t('templates.unresolved') : show(v) }}</span></td>
                    <td><span v-if="v === null" class="rk missing">{{ $t('templates.kMissing') }}</span><span v-else-if="bad.has(k)" class="rk violation">{{ $t('templates.kViolation') }}</span></td>
                  </tr>
                  <tr v-for="r in instances" :key="`${r.block}#${r.i}`" :class="{ 'is-sel': selInst === `${r.block}#${r.i}` }" @click="selInst = selInst === `${r.block}#${r.i}` ? null : `${r.block}#${r.i}`; selF = null">
                    <td><span class="vname">{{ r.block }}</span> <span class="tag mono" style="height: 18px">#{{ r.i }}</span></td>
                    <td><span class="val">{{ r.vals.map(([k, v]) => `${k}=${v === null ? '∅' : show(v)}`).join('  ') }}</span></td>
                    <td><span v-if="r.vals.some(([k]) => bad.has(`${r.block}.${k}`))" class="rk violation">{{ $t('templates.kViolation') }}</span></td>
                  </tr>
                  <tr v-if="!baseVars.length && !instances.length"><td colspan="3" class="faint small">{{ $t('templates.noVars') }}</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="m3box cfgbox">
          <div class="m3box-h"><h3>{{ res.device }}</h3><span class="faint">{{ res.profile }}</span></div>
          <M3Code v-if="code.length" ref="pane" :lines="code" testid="tpl-ck-code" class="ckcode" @pick="pickLine" />
          <div v-else class="empty small">{{ $t('templates.noText') }}</div>
          <div class="m3box-f">
            <span class="rk violation">{{ $t('templates.kViolation') }}</span><span class="rk extra">{{ $t('templates.kExtra') }}</span>
            <span class="faint">{{ $t('templates.lgMissing') }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.chk-setup { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.chk-setup .select { width: auto; max-width: 320px; }
.paste { width: 100%; resize: vertical; min-height: 140px; font-size: 12px; margin-bottom: 12px; }
.ksum { display: flex; gap: 6px 14px; align-items: center; flex-wrap: wrap; padding: 10px 12px; border: 1px solid var(--line); border-radius: 6px; margin-bottom: 12px; }
.ksum .verdict { font: 600 15px var(--font-display); display: inline-flex; align-items: center; gap: 8px; margin-right: 8px; }
.ksum .verdict.bad { color: var(--red-ink); }
.ksum .verdict.good { color: var(--teal-ink); }
.ksum button { all: unset; cursor: pointer; display: inline-flex; gap: 6px; align-items: center; font-size: 12px; color: var(--ink-2); padding: 2px 4px; border-radius: 4px; }
.ksum button[aria-pressed="true"] { background: var(--surface-3); color: var(--ink); }
.ksum button:focus-visible { outline: 2px solid var(--focus); }
.ksum b { font: 600 15px var(--font-display); color: var(--ink); }
.ck { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 12px; align-items: start; }
@media (max-width: 1400px) { .ck { grid-template-columns: minmax(0, 1fr); } }
.ki { padding: 9px 12px 9px 14px; border-bottom: 1px solid var(--line); cursor: pointer; position: relative; }
.ki::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bar); }
.ki.violation { --bar: var(--red); }
.ki.missing { --bar: #D9962B; }
.ki.extra { --bar: var(--blue); }
.ki.info { --bar: var(--line-strong); }
.ki:hover { background: var(--surface-2); }
.ki.is-sel { background: var(--blue-soft); box-shadow: inset 0 0 0 1.5px var(--sel-ring); }
.kh { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.km { margin-top: 5px; font-size: 12.5px; overflow-wrap: anywhere; }
.kn { font: 11.5px var(--font-mono); color: var(--ink-3); margin-top: 3px; overflow-wrap: anywhere; }
.kr { font: 11.5px var(--font-mono); color: var(--ink-2); margin-top: 5px; background: var(--surface-2); border-radius: 4px; padding: 3px 6px; overflow-wrap: anywhere; white-space: pre-wrap; }
.xv-t td { vertical-align: middle; }
.xv-t tr.is-sel td { background: var(--var-soft); }
.xv-t .val { font: 12px var(--font-mono); overflow-wrap: anywhere; }
.xv-t .val.bad { color: var(--red-ink); text-decoration: underline wavy color-mix(in srgb, var(--red) 60%, transparent); text-underline-offset: 3px; }
.cfgbox { position: sticky; top: 0; }
.ckcode { max-height: 720px; }
</style>
