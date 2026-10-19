<script setup lang="ts">
/** 冗余清理：按 DevelopDocs/ui-preview/M2/cleanup.html。孤儿对象树（级联勾选）、删除脚本（兜底命令需人工核对，D-0017）、删除后复检。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { useTerms } from '@/stores/terms'
import { errorText, get, post } from '@/api'
import type { Device } from './devices/logic'
import CheckTabs from './check/CheckTabs.vue'
import TargetBar from './check/TargetBar.vue'
import { saveBlob, target, targetBody } from './check/report'
import { isComment, splitLines } from './check/logic'
import {
  allPicked, exitWord, filterCommands, isLocked, orphanTree, removedLines, scriptFile, scriptRows, scriptText, togglePick,
} from './check/cleanup'
import type { CleanupObject, CleanupResult } from './check/types'
import VendorBadge from '@/components/vendor-badge.vue'

const { t } = useI18n()
const terms = useTerms()
const route = useRoute()
const router = useRouter()

const devices = ref<Device[]>([])
const devicesLoaded = ref(false)
const result = ref<CleanupResult | null>(null)
const lines = ref<string[]>([])
const textFor = ref<number | null>(null)
const loading = ref(false)
const failMsg = ref('')
const picked = ref<Set<string>>(new Set())
const open = ref<Set<string>>(new Set())
const confirmed = ref(false)
const toast = ref<{ msg: string; err: boolean } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | undefined

function showToast(msg: string, err = false): void {
  toast.value = { msg, err }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = null), 2800)
}
onBeforeUnmount(() => clearTimeout(toastTimer))

const device = computed(() => devices.value.find((d) => d.id === target.deviceId) ?? null)
const objects = computed<CleanupObject[]>(() => result.value?.objects ?? [])
const byNode = computed(() => new Map(objects.value.map((o) => [o.node, o])))
const tree = computed(() => orphanTree(objects.value))
const nCascade = computed(() => objects.value.filter((o) => o.reason === 'cascade').length)
const nPicked = computed(() => objects.value.filter((o) => picked.value.has(o.node)).length)
const partial = computed(() => nPicked.value < objects.value.length)
const cmds = computed(() => (result.value ? filterCommands(result.value.commands, picked.value) : []))
const exit = computed(() => (result.value ? exitWord(result.value.family, result.value.commands) : 'exit'))
const rows = computed(() => scriptRows(cmds.value, exit.value))
const nFallback = computed(() => cmds.value.filter((c) => c.fallback).length)
const canExport = computed(() => cmds.value.length > 0 && (!nFallback.value || confirmed.value))
const fileName = computed(() => scriptFile(result.value?.device ?? device.value?.name ?? null))
const verify = computed(() => result.value?.verify ?? null)
const verifyLeft = computed(() => (verify.value ? verify.value.remaining_objects.length + verify.value.new_orphans.length : 0))
const rulesLabel = computed(() => (target.rulesAll ? `${target.rulesOn ?? 0} / ${target.rulesAll}` : null))

/** 节点名：当前显示风格的命令写法（REQ-026），规范编号放在悬停提示里 */
const label = (node: string) => (node ? terms.describe(node) : '')
const canonTip = (node: string) => `${t('hid.canonical')}: ${node}`
const kindOf = (o: CleanupObject) => o.schema || o.node.replace(/\[.*$/, '')
const kindCls = (o: CleanupObject) => {
  const s = kindOf(o)
  if (/policy|route_map/.test(s)) return 't-blue'
  if (/prefix/.test(s)) return 't-teal'
  if (/community/.test(s)) return 't-violet'
  return ''
}
const parentName = (o: CleanupObject) => label(o.via.find((v) => byNode.value.has(v)) ?? o.via[0] ?? '')
const locked = (o: CleanupObject) => isLocked(o, picked.value, objects.value)

async function loadDevices(): Promise<void> {
  try {
    devices.value = (await get<{ devices: Device[] }>('/devices')).devices
  } catch (e) {
    failMsg.value = errorText(e)
  } finally {
    devicesLoaded.value = true
  }
}

async function run(): Promise<void> {
  const body = targetBody()
  if (!body) return
  loading.value = true
  failMsg.value = ''
  try {
    const res = await post<CleanupResult>('/cleanup', body)
    // 依次请求：原文行用于展开对象的配置
    if ('device_id' in body) {
      if (textFor.value !== body.device_id) {
        const g = await get<{ text?: string }>(`/devices/${body.device_id}/graph?raw=true`)
        lines.value = splitLines(g.text ?? '')
        textFor.value = body.device_id
      }
    } else {
      lines.value = splitLines(body.text)
      textFor.value = null
    }
    result.value = res
    picked.value = allPicked(res.objects)
    open.value = new Set()
    confirmed.value = false
    target.orphans = res.objects.length
  } catch (e) {
    result.value = null
    failMsg.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function onTargetChange(): void {
  result.value = null
  target.findings = null
  target.orphans = null
  failMsg.value = ''
  if (target.mode === 'device' && target.deviceId != null) {
    router.replace({ query: { ...route.query, device: String(target.deviceId) } })
    run()
  }
}

function onPick(o: CleanupObject, e: Event): void {
  picked.value = togglePick(picked.value, o.node, (e.target as HTMLInputElement).checked, objects.value)
  confirmed.value = false
}
function toggleOpen(node: string): void {
  const s = new Set(open.value)
  if (s.has(node)) s.delete(node)
  else s.add(node)
  open.value = s
}

function text(): string {
  return result.value ? scriptText(result.value, picked.value) : ''
}
async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(text())
    showToast(t('c.copied'))
  } catch (e) {
    showToast(errorText(e), true)
  }
}
function download(): void {
  saveBlob(new Blob([text()], { type: 'text/plain;charset=utf-8' }), fileName.value)
  showToast(t('cleanup.downloaded', { f: fileName.value }))
}

onMounted(async () => {
  const q = Number(route.query.device)
  if (q > 0) { target.mode = 'device'; target.deviceId = q }
  await loadDevices()
  if (target.mode === 'device' && target.deviceId == null && devices.value.length) target.deviceId = devices.value[0].id
  if (targetBody()) await run()
})
</script>

<template>
  <main class="main">
    <div class="page">
      <div class="crumbs"><span>{{ $t('grp.dev') }}</span><span class="sep">/</span><router-link :to="{ name: 'check' }">{{ $t('nav.check') }}</router-link><span class="sep">/</span><span>{{ $t('nav.cleanup') }}</span></div>
      <div class="ck-head">
        <div class="ph-text">
          <h1>{{ $t('nav.cleanup') }}</h1>
          <p class="ph-sub">{{ $t('cleanup.sub') }}</p>
          <TargetBar :devices="devices" :profile="result?.profile ?? device?.profile" :family="result?.family" @change="onTargetChange" />
        </div>
        <div class="ph-actions">
          <button class="btn" type="button" :disabled="loading || !targetBody()" data-testid="btn-regen" @click="run">
            <Icon name="refresh" small />{{ $t('cleanup.regen') }}
          </button>
        </div>
      </div>

      <CheckTabs active="cleanup" :findings="target.findings" :rules="rulesLabel" :orphans="result ? objects.length : target.orphans" />

      <div v-if="failMsg" class="notice err" data-testid="cleanup-error">
        <Icon name="err" /><div class="grow"><b>{{ failMsg }}</b>
          <div class="row mt12"><button class="btn btn-sm" type="button" @click="run"><Icon name="refresh" small />{{ $t('c.retry') }}</button></div></div>
      </div>

      <div v-else-if="devicesLoaded && target.mode === 'device' && !devices.length" class="panel">
        <div class="empty"><h3>{{ $t('check.noDevices') }}</h3>
          <router-link class="btn btn-sm btn-primary" :to="{ name: 'devices' }">{{ $t('check.goImport') }}</router-link></div>
      </div>

      <div v-else-if="!result" class="panel">
        <div class="empty">
          <template v-if="loading"><p>{{ $t('c.loading') }}</p></template>
          <template v-else><Icon name="broom" /><h3>{{ $t('check.startTitle') }}</h3><p>{{ $t('check.startHint') }}</p>
            <button class="btn btn-sm btn-primary" type="button" :disabled="!targetBody()" @click="run"><Icon name="play" small />{{ $t('cleanup.regen') }}</button></template>
        </div>
      </div>

      <template v-else>
        <div v-if="result.skipped.length" class="notice info mb12" data-testid="cleanup-skipped">
          <Icon name="info" /><div class="grow small">{{ $t('cleanup.skipped', { n: result.skipped.length }) }}
            <span v-for="s in result.skipped" :key="s.node" class="tag mono skip-tag" :title="canonTip(s.node)">{{ label(s.node) }}</span></div>
        </div>

        <div v-if="!objects.length" class="panel" data-testid="cleanup-empty">
          <div class="empty">
            <svg class="art" viewBox="0 0 120 84" aria-hidden="true"><rect x="22" y="14" width="76" height="56" rx="6" fill="var(--surface-2)" stroke="var(--line-strong)" /><path d="M34 30h30M34 42h44M34 54h22" stroke="var(--line-strong)" stroke-width="3" stroke-linecap="round" /><circle cx="88" cy="60" r="14" fill="var(--teal-soft)" stroke="var(--teal)" stroke-width="2" /><path d="m81 60 5 5 9-10" fill="none" stroke="var(--teal-ink)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
            <h3>{{ $t('cleanup.emptyTitle') }}</h3>
            <p>{{ $t('cleanup.emptyBody') }}</p>
          </div>
        </div>

        <template v-else>
          <div class="cu-work">
            <section class="panel" aria-label="Orphans" data-testid="orphan-tree">
              <div class="panel-h">
                <h2>{{ $t('cleanup.orphans') }}</h2>
                <span class="meta">{{ $t('cleanup.selected', { n: nPicked, all: objects.length, c: nCascade }) }}</span>
              </div>
              <div v-if="nCascade" class="sc-note"><Icon name="info" small /><span>{{ $t('cleanup.cascadeNote') }}</span></div>
              <div>
                <div v-for="r in tree" :key="r.o.node" class="orow" :class="{ child: r.depth > 0, off: !picked.has(r.o.node) }" data-testid="orphan-row">
                  <div class="ohead" :style="r.depth > 1 ? { paddingLeft: `${12 + 28 * r.depth}px` } : undefined">
                    <input type="checkbox" :checked="picked.has(r.o.node)" :disabled="locked(r.o)" :aria-label="r.o.node" :data-testid="`pick-${r.o.node}`" @change="onPick(r.o, $event)" />
                    <button type="button" class="tw" :aria-expanded="open.has(r.o.node)" :title="$t('cleanup.showLines')" :aria-label="$t('cleanup.showLines')" @click="toggleOpen(r.o.node)"><Icon name="chevR" small /></button>
                    <div class="oname">
                      <span class="tag" :class="kindCls(r.o)" :title="kindOf(r.o)">{{ terms.name(kindOf(r.o)) }}</span>
                      <span class="nm" :title="canonTip(r.o.node)">{{ label(r.o.node) }}</span>
                      <span v-if="r.o.reason === 'cascade'" class="tag t-violet">{{ $t('cleanup.cascadeTag') }}</span>
                      <span v-else class="tag">{{ $t('cleanup.noRef') }}</span>
                    </div>
                    <span class="ometa">{{ r.o.lines.length }} {{ $t('c.lines') }}</span>
                    <div v-if="r.o.reason === 'cascade'" class="owhy" :class="{ block: locked(r.o) }">
                      {{ locked(r.o) ? $t('cleanup.lockedWhy', { p: parentName(r.o) }) : $t('cleanup.withParent', { p: parentName(r.o) }) }}
                    </div>
                  </div>
                  <div v-if="open.has(r.o.node)" class="olines">
                    <div class="code">
                      <div v-for="n in r.o.lines" :key="n" class="l" :class="{ 'c-cmt': isComment(lines[n - 1] ?? '') }"><span class="n">{{ n }}</span><span class="g"></span><span class="t">{{ lines[n - 1] ?? '' }}</span></div>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section class="panel" aria-label="Script" data-testid="cleanup-script">
              <div class="panel-h">
                <h2>{{ $t('cleanup.script') }}</h2>
                <span class="meta mono">{{ fileName }}</span>
              </div>
              <div class="sc-note"><Icon name="branch" small /><span>{{ $t('cleanup.scriptNote') }}</span></div>
              <div class="sc-note"><VendorBadge v-if="result.family" :of="result.family">{{ $t('cleanup.family') }}</VendorBadge><span class="tag mono">{{ result.family }}</span></div>
              <div class="script">
                <div v-if="!rows.length" class="empty"><p>{{ $t('cleanup.emptyScript') }}</p></div>
                <div v-for="(s, i) in rows" :key="i" class="sl" :class="s.type === 'frame' ? 'frame' : s.cmd.fallback ? 'fallback' : 'card'" data-testid="script-line">
                  <span class="no">{{ i + 1 }}</span>
                  <div class="bd">
                    <div class="cmd">{{ ' '.repeat(s.indent) }}{{ s.type === 'frame' ? s.text : s.cmd.text }}</div>
                    <div v-if="s.type === 'frame'" class="ann">{{ $t('cleanup.frame') }}</div>
                    <template v-else-if="s.cmd.fallback">
                      <div class="ann">
                        <span class="fbmark"><Icon name="warn" small />{{ $t('cleanup.fallback') }}</span>
                        <span v-if="s.cmd.card" class="card">{{ s.cmd.card }}</span>
                        <span>· {{ label(s.cmd.object) }} · {{ $t('cleanup.origLines', { list: s.cmd.lines.join(', ') }) }}</span>
                      </div>
                      <div class="why">{{ $t('cleanup.fallbackWhy', { card: s.cmd.card || '—' }) }}</div>
                    </template>
                    <div v-else class="ann">
                      <Icon name="book" small />{{ $t('cleanup.card') }} <span class="card">{{ s.cmd.card }}</span>
                      <span>· {{ label(s.cmd.object) }} · {{ $t('cleanup.origLines', { list: s.cmd.lines.join(', ') }) }}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div class="sc-foot">
                <p v-if="partial && cmds.length" class="small faint">{{ $t('cleanup.partialNote', { n: objects.length }) }}</p>
                <label v-if="nFallback" class="confirm" data-testid="confirm-fallback"><input v-model="confirmed" type="checkbox" /><span>{{ $t('cleanup.confirm', { n: nFallback }) }}</span></label>
                <div class="row">
                  <button class="btn" type="button" :disabled="!canExport" data-testid="btn-copy" @click="copy"><Icon name="copy" small />{{ $t('cleanup.copy') }}</button>
                  <button class="btn btn-primary" type="button" :disabled="!canExport" data-testid="btn-download" @click="download"><Icon name="download" small />{{ $t('cleanup.download') }}</button>
                  <span v-if="cmds.length && !canExport" class="why-disabled">{{ $t('cleanup.whyDisabled') }}</span>
                </div>
              </div>
            </section>
          </div>

          <section v-if="verify" class="panel mt12" aria-label="Recheck" data-testid="cleanup-verify">
            <div class="panel-h"><h2>{{ $t('cleanup.verify') }}</h2></div>
            <div class="panel-b">
              <p class="muted small">{{ $t('cleanup.verifyNote') }}</p>
              <div class="rc-grid mt12">
                <div><div class="k">{{ $t('cleanup.kOrphans') }}</div><div class="v" :class="{ ok: !verifyLeft }"><s>{{ objects.length }}</s><Icon name="chevR" small />{{ verifyLeft }}</div></div>
                <div><div class="k">{{ $t('cleanup.kLines') }}</div><div class="v">{{ removedLines(objects, allPicked(objects)) }}</div></div>
                <div><div class="k">{{ $t('cleanup.kDangling') }}</div><div class="v">{{ verify.dangling_before }}<Icon name="chevR" small />{{ verify.dangling_after }}</div></div>
                <div><div class="k">{{ $t('cleanup.kNewDangling') }}</div><div class="v" :class="{ ok: !verify.new_dangling.length }"><Icon v-if="!verify.new_dangling.length" name="ok" />{{ verify.new_dangling.length }}</div></div>
                <div><div class="k">{{ $t('cleanup.kRemaining') }}</div><div class="v" :class="{ ok: !verify.remaining_objects.length }"><Icon v-if="!verify.remaining_objects.length" name="ok" />{{ verify.remaining_objects.length }}</div></div>
              </div>
              <div v-if="verify.ok" class="notice info mt12"><Icon name="ok" /><div class="grow small">{{ $t('cleanup.verifyOk') }}</div></div>
              <div v-else class="notice err mt12"><Icon name="err" /><div class="grow small">
                <b>{{ $t('cleanup.verifyBad') }}</b>
                <ul class="vlist mono">
                  <li v-for="(d, i) in verify.new_dangling" :key="`d${i}`">{{ $t('cleanup.newDangling', { referrer: label(d.referrer), type: d.target_type, value: d.value }) }}</li>
                  <li v-for="n in verify.remaining_objects" :key="`r${n}`">{{ $t('cleanup.remainingObj', { node: label(n) }) }}</li>
                  <li v-for="n in verify.new_orphans" :key="`o${n}`">{{ $t('cleanup.newOrphan', { node: label(n) }) }}</li>
                </ul></div></div>
              <div v-if="partial" class="notice warn mt12"><Icon name="warn" /><div class="grow small">{{ $t('cleanup.leftNotice', { n: objects.length - nPicked }) }}</div></div>
              <div class="row mt12"><router-link class="btn btn-sm" :to="{ name: 'devices' }"><Icon name="upload" small />{{ $t('cleanup.importNew') }}</router-link></div>
            </div>
          </section>
        </template>
      </template>
    </div>
    <div v-if="toast" class="toast" role="status" data-testid="cleanup-toast"><Icon :name="toast.err ? 'err' : 'ok'" small />{{ toast.msg }}</div>
  </main>
</template>

<style scoped>
.ck-head { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
.ck-head .ph-text { flex: 1; min-width: 300px; }
.mb12 { margin-bottom: 12px; }
.skip-tag { margin: 2px 4px 0 0; }
.vlist { margin: 6px 0 0 18px; font-size: 12px; }

.cu-work { display: grid; gap: 12px; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); align-items: start; }
@media (max-width: 1100px) { .cu-work { grid-template-columns: minmax(0, 1fr); } }

.orow { border-bottom: 1px solid var(--line); }
.orow:last-child { border-bottom: 0; }
.ohead { display: grid; grid-template-columns: 18px 22px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 9px 12px; }
.orow.child .ohead { padding-left: 40px; position: relative; }
.orow.child .ohead::before { content: ""; position: absolute; left: 21px; top: 0; height: 50%; width: 12px; border-left: 1px solid var(--line-strong); border-bottom: 1px solid var(--line-strong); border-bottom-left-radius: 4px; }
.ohead input { accent-color: var(--teal); margin: 0; width: 14px; height: 14px; }
.ohead input:disabled { opacity: .6; cursor: not-allowed; }
.ohead .tw { border: 0; background: none; color: var(--ink-3); cursor: pointer; padding: 0; width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 4px; }
.ohead .tw:hover { background: var(--surface-3); color: var(--ink); }
.ohead .tw :deep(.ico) { transition: transform .15s; }
.ohead .tw[aria-expanded="true"] :deep(.ico) { transform: rotate(90deg); }
.oname { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; }
.oname .nm { font: 600 12.5px var(--font-mono); overflow-wrap: anywhere; }
.ometa { color: var(--ink-3); font-size: 12px; white-space: nowrap; }
.owhy { grid-column: 3 / -1; font-size: 12px; color: var(--ink-2); }
.owhy.block { color: var(--amber-ink); }
.orow.off .oname .nm { color: var(--ink-3); text-decoration: line-through; text-decoration-color: var(--line-strong); }
.olines { margin: 0 12px 10px 70px; border: 1px solid var(--line); border-radius: 5px; overflow: auto; }
.orow:not(.child) .olines { margin-left: 48px; }

.sc-note { display: flex; gap: 8px; align-items: center; padding: 8px 14px; border-bottom: 1px solid var(--line); font-size: 12px; color: var(--ink-2); background: var(--surface-2); }
.script { font: 12px/1.5 var(--font-mono); }
.sl { display: grid; grid-template-columns: 34px minmax(0, 1fr); border-bottom: 1px solid var(--line); }
.sl:last-child { border-bottom: 0; }
.sl .no { text-align: right; padding: 6px 8px 6px 0; color: var(--ink-3); background: var(--surface-2); border-right: 1px solid var(--line); user-select: none; }
.sl .bd { padding: 6px 12px; min-width: 0; }
.sl .cmd { white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink); }
.sl .ann { font: 11.5px/1.5 var(--font-ui); color: var(--ink-3); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 3px; }
.sl .ann .card { font: 11px var(--font-mono); color: var(--ink-2); }
.sl.frame .cmd { color: var(--ink-3); }
.sl.fallback { background: color-mix(in srgb, var(--amber-soft) 60%, transparent); }
.sl.fallback .no { box-shadow: inset 3px 0 0 var(--amber); background: var(--amber-soft); color: var(--amber-ink); font-weight: 600; }
.sl.fallback .why { font: 12px/1.5 var(--font-ui); color: var(--amber-ink); margin-top: 4px; }
.fbmark { display: inline-flex; align-items: center; gap: 4px; height: 18px; padding: 0 6px; border-radius: 4px; background: var(--amber); color: #3A2600; font: 600 11px var(--font-ui); }
.sc-foot { padding: 10px 14px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.sc-foot .row { flex-wrap: wrap; }
.confirm { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; border: 1px solid var(--amber-line); background: var(--amber-soft); border-radius: 6px; cursor: pointer; }
.confirm input { accent-color: var(--amber-ink); margin-top: 3px; }
.why-disabled { font-size: 12px; color: var(--ink-3); }

.rc-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 6px; }
.rc-grid > div { padding: 10px 14px; border-left: 1px solid var(--line); min-width: 0; }
.rc-grid > div:first-child { border-left: 0; }
.rc-grid .k { font-size: 12px; color: var(--ink-2); }
.rc-grid .v { font: 600 18px/1.3 var(--font-display); margin-top: 2px; display: flex; align-items: center; gap: 6px; }
.rc-grid .v :deep(.ico) { width: 18px; height: 18px; }
.rc-grid .v.ok { color: var(--teal-ink); }
.rc-grid .v s { color: var(--ink-3); font-weight: 400; font-size: 14px; }
@media (max-width: 1100px) { .rc-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .rc-grid > div { border-top: 1px solid var(--line); } }
</style>
