<script setup lang="ts">
/**
 * 项目脚本（M6，预览 DevelopDocs/ui-preview/M6/scripts.html）：原“配置检查项目”并入项目后的入口。
 * GET /projects/{p}/scripts 平铺列出本项目的脚本；编辑器、修订、重排、对比沿用配置检查项目页（check-project 路由）。
 * 新建脚本 POST /projects/{p}/scripts（同时建一个保存基线与检查设置的组），基线只能选本项目的设备。只读成员只能查看。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import ProjSource from '@/components/proj-source.vue'
import { errorText, get, post } from '@/api'
import { useProject } from '@/stores/project'
import type { VersionInfo } from '@/views/compare/types'
import { fmtTime } from '@/views/check-projects/logic'
import type { AiRules } from '@/views/check-projects/types'
import { baseMark, checkState, filterScripts, nextScriptName, NOTE_KEY, starterChange, type Kind, type ProjDevice, type ScriptFilter, type ScriptRow } from './scripts/logic'
import '@/styles/req031.css'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`scripts.${k}`, p ?? {})
const router = useRouter()
const project = useProject()
const canWrite = computed(() => project.canWrite)

const rows = ref<ScriptRow[] | null>(null)
const devices = ref<ProjDevice[]>([])
const loadErr = ref('')
const ai = ref<AiRules>({ configured: false, rules: [] })
const verSeq = ref<Record<number, number>>({})
const f = ref<ScriptFilter>({ kind: '', device: null })

function readNote(): boolean { try { return localStorage.getItem(NOTE_KEY) === '1' } catch { return false } }
const noteClosed = ref(readNote())
function closeNote(): void {
  noteClosed.value = true
  try { localStorage.setItem(NOTE_KEY, '1') } catch { /* 忽略 */ }
}

const devMap = computed(() => new Map(devices.value.map((d) => [d.id, d])))
const shown = computed(() => filterScripts(rows.value ?? [], f.value))
const baseDevices = computed(() => {
  const m = new Map<number, string>()
  for (const r of rows.value ?? []) if (r.baseline?.device) m.set(r.baseline.device.id, r.baseline.device.name)
  return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]))
})

async function load(): Promise<void> {
  loadErr.value = ''
  const slug = project.slug
  if (!slug) return
  try {
    const [s, d, a] = await Promise.all([
      get<{ scripts: ScriptRow[] }>(`/projects/${encodeURIComponent(slug)}/scripts`),
      get<{ devices: ProjDevice[] }>('/devices').catch(() => ({ devices: [] as ProjDevice[] })),
      get<AiRules>('/check-projects/ai-rules').catch(() => ({ configured: false, rules: [] })),
    ])
    rows.value = s.scripts
    devices.value = d.devices
    ai.value = a
    void loadPinned(s.scripts)
  } catch (e) { loadErr.value = errorText(e) }
}

/** 脚本自己指定了基线版本时：取设备的版本列表，显示版本序号。 */
async function loadPinned(list: ScriptRow[]): Promise<void> {
  const ids = [...new Set(list.filter((r) => r.baseline?.version_id != null && r.baseline.device).map((r) => r.baseline!.device!.id))]
  // 项目固定了版本的公共设备（接口没给序号时）也要查序号
  for (const r of list) {
    const d = r.baseline?.device ? devMap.value.get(r.baseline.device.id) : undefined
    if (d?.policy === 'pin' && d.pinned_seq == null && !ids.includes(d.id)) ids.push(d.id)
  }
  for (const id of ids) {
    try {
      const vs = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions
      verSeq.value = { ...verSeq.value, ...Object.fromEntries(vs.map((v) => [v.id, v.seq])) }
    } catch { /* 显示不了序号时只标“固定” */ }
  }
}

/** 基线设备的来源与版本标记（私有 vN / 公共跟随 / 固定 vN）。 */
function markOf(r: ScriptRow): ReturnType<typeof baseMark> {
  const id = r.baseline?.device?.id
  return id === undefined ? null : baseMark(r, devMap.value.get(id), verSeq.value)
}

function openEditor(r: ScriptRow, view?: string): void {
  void router.push({ name: 'check-project', params: { id: r.group.id }, query: { script: String(r.id), ...(view ? { view } : {}) } })
}

/* ---------------------------------------------------------------- 新建脚本 */
const showNew = ref(false)
const nsName = ref('')
const nsKind = ref<Kind>('change')
const nsDev = ref<number | null>(null)
const nsVer = ref<number | null>(null)
const nsVers = ref<VersionInfo[]>([])
const nsOrder = ref(true)
const nsAi = ref(false)
const nsErr = ref('')
const nsBusy = ref(false)
const nsDevice = computed(() => (nsDev.value === null ? undefined : devMap.value.get(nsDev.value)))
const followLabel = computed(() => {
  const d = nsDevice.value
  if (!d) return ''
  if (d.source === 'public') {
    const seq = d.pinned_seq ?? nsVers.value.find((v) => v.id === d.pinned_version_id)?.seq ?? '?'
    return T('followProject', { v: d.policy === 'pin' ? T('pinnedAt', { n: seq }) : T('followLatestNow', { n: d.versions }) })
  }
  return T('latestNow', { n: d.versions })
})

function openNew(): void {
  nsName.value = nextScriptName(rows.value ?? [])
  nsKind.value = 'change'
  nsDev.value = devices.value[0]?.id ?? null
  nsVer.value = null
  nsOrder.value = true
  nsAi.value = false
  nsErr.value = ''
  showNew.value = true
}
watch(nsDev, async (id) => {
  nsVer.value = null
  nsVers.value = []
  if (id === null) return
  try { nsVers.value = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions } catch { /* 只能跟随项目版本 */ }
})

async function createScript(): Promise<void> {
  const name = nsName.value.trim()
  if (!name) { nsErr.value = T('nameRequired'); return }
  const slug = project.slug
  if (!slug) return
  nsBusy.value = true
  nsErr.value = ''
  try {
    const d = nsDevice.value
    let content = ''
    if (nsKind.value === 'change') content = starterChange(d?.vendor || d?.profile || '')
    else if (d) {
      // 完整配置从基线版本的配置复制一份（不指定版本时为项目中的当前版本）
      const vid = nsVer.value ?? d.latest_version_id
      if (vid !== null) content = (await get<{ text: string }>(`/devices/${d.id}/versions/${vid}/text`)).text ?? ''
    }
    const r = await post<{ group: { id: number }; script: { id: number } }>(`/projects/${encodeURIComponent(slug)}/scripts`, {
      name, kind: nsKind.value, device_id: nsDev.value, version_id: nsVer.value, content,
      order_check: nsOrder.value, ai_check: ai.value.configured && nsAi.value,
    })
    showNew.value = false
    void router.push({ name: 'check-project', params: { id: r.group.id }, query: { script: String(r.script.id) } })
  } catch (e) { nsErr.value = errorText(e) } finally { nsBusy.value = false }
}

onMounted(load)
watch(() => project.slug, (v, old) => { if (v && v !== old) { rows.value = null; f.value = { kind: '', device: null }; void load() } })
</script>

<template>
  <main class="main">
    <div class="page r31">
      <div class="crumbs"><span>{{ project.info?.name }}</span><span class="sep">/</span><span>{{ $t('nav.scripts') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.scripts') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions">
          <button v-if="canWrite" class="btn btn-primary" type="button" data-testid="scripts-new" @click="openNew"><Icon name="plus" small /><span>{{ T('new') }}</span></button>
        </div>
      </div>

      <div v-if="!noteClosed" class="notice info" style="margin-bottom: 12px" data-testid="scripts-merge-note">
        <Icon name="info" />
        <div class="grow"><b>{{ T('mergeTitle') }}</b> · <span>{{ T('mergeText') }}</span></div>
        <button class="btn btn-sm btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" :title="$t('c.close')" data-testid="scripts-merge-close" @click="closeNote"><Icon name="x" small /></button>
      </div>

      <div v-if="loadErr" class="notice err"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <section v-else-if="rows === null" class="panel"><div class="empty">{{ $t('c.loading') }}</div></section>

      <section v-else class="panel">
        <div class="panel-h toolbar" style="padding: 8px 12px">
          <div class="seg" role="group" data-testid="scripts-kind">
            <button type="button" :aria-pressed="f.kind === ''" @click="f.kind = ''">{{ T('all') }}</button>
            <button type="button" :aria-pressed="f.kind === 'change'" @click="f.kind = 'change'">{{ T('kindChange') }}</button>
            <button type="button" :aria-pressed="f.kind === 'full'" @click="f.kind = 'full'">{{ T('kindFull') }}</button>
          </div>
          <select v-model="f.device" class="select" style="width: auto" :aria-label="T('col.base')" data-testid="scripts-device">
            <option :value="null">{{ T('allDevices') }}</option>
            <option v-for="[id, name] in baseDevices" :key="id" :value="id">{{ name }}</option>
          </select>
          <span class="grow" />
          <span class="small faint">{{ T('permNote') }}</span>
        </div>
        <div class="tbl-wrap">
          <table class="tbl pj-tbl" data-testid="scripts-table">
            <thead><tr>
              <th>{{ T('col.script') }}</th>
              <th>{{ T('col.type') }}</th>
              <th>{{ T('col.base') }}</th>
              <th>{{ T('col.check') }}</th>
              <th>{{ T('col.order') }}</th>
              <th v-if="ai.configured">{{ T('col.ai') }}</th>
              <th class="num">{{ T('col.revs') }}</th>
              <th>{{ T('col.edited') }}</th>
              <th />
            </tr></thead>
            <tbody>
              <tr v-for="r in shown" :key="r.id" :data-testid="`scripts-row-${r.id}`">
                <td class="pj-name">
                  <a href="#" class="mono" @click.prevent="openEditor(r)">{{ r.name }}</a>
                  <div v-if="r.group.name && r.group.name !== r.name" class="d">{{ T('group', { g: r.group.name }) }}</div>
                </td>
                <td><span class="typetag" :class="r.kind">{{ r.kind === 'change' ? T('tagChange') : T('tagFull') }}</span></td>
                <td>
                  <div v-if="r.baseline?.device" class="devcell">
                    <DevChip :name="r.baseline.device.name" :vendor="r.baseline.device.vendor || r.baseline.device.profile" />
                    <ProjSource v-if="markOf(r)" v-bind="markOf(r)!" />
                  </div>
                  <span v-else class="small faint">{{ T('noBase') }}</span>
                </td>
                <td>
                  <span v-if="checkState(r.last_check) === 'never'" class="small faint">{{ T('notChecked') }}</span>
                  <span v-else-if="checkState(r.last_check) === 'ok'" class="ls ok">{{ T('noIssues') }}</span>
                  <span v-else class="cnt">
                    <span v-if="r.last_check!.errors" class="e" :title="T('sev.error')"><span class="sevdot error" /><b>{{ r.last_check!.errors }}</b></span>
                    <span v-if="r.last_check!.warnings" class="w" :title="T('sev.warning')"><span class="sevdot warning" /><b>{{ r.last_check!.warnings }}</b></span>
                    <span v-if="r.last_check!.infos" class="i" :title="T('sev.info')"><span class="sevdot info" /><b>{{ r.last_check!.infos }}</b></span>
                  </span>
                </td>
                <td>
                  <span v-if="r.kind === 'full'" class="small faint">{{ T('na') }}</span>
                  <span v-else class="onoff" :class="{ on: r.order_check !== false }">{{ r.order_check !== false ? T('on') : T('off') }}</span>
                </td>
                <td v-if="ai.configured"><span class="onoff" :class="{ on: r.ai_check }">{{ r.ai_check ? T('on') : T('off') }}</span></td>
                <td class="num"><a href="#" @click.prevent="openEditor(r, 'revisions')">{{ r.revisions }}</a></td>
                <td class="small muted nowrap"><span v-if="r.author" class="m6av" :title="r.author">{{ r.author.charAt(0).toUpperCase() }}</span> {{ fmtTime(r.updated_at) }}</td>
                <td class="right nowrap">
                  <button class="btn btn-sm" type="button" :data-testid="`scripts-open-${r.id}`" @click="openEditor(r)">{{ T('open') }}</button>
                  <button class="btn btn-sm btn-ghost" type="button" @click="openEditor(r, 'diff')">{{ T('diff') }}</button>
                </td>
              </tr>
              <tr v-if="!rows.length">
                <td :colspan="9">
                  <div class="empty" data-testid="scripts-empty">
                    <h3>{{ T('emptyTitle') }}</h3>
                    <p>{{ canWrite ? T('emptyText') : T('emptyRo') }}</p>
                    <button v-if="canWrite" class="btn btn-primary" type="button" @click="openNew"><Icon name="plus" small /><span>{{ T('new') }}</span></button>
                  </div>
                </td>
              </tr>
              <tr v-else-if="!shown.length"><td :colspan="9" class="muted" style="text-align: center; padding: 24px">{{ T('noMatch') }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div v-if="showNew" class="modal-back r31" data-testid="scripts-new-modal" @click.self="showNew = false" @keydown.esc="showNew = false">
      <div class="modal" style="width: min(640px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nsT">
        <div class="modal-h"><h2 id="nsT">{{ T('new') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="showNew = false"><Icon name="x" /></button></div>
        <div class="modal-b form-stack">
          <div class="form-grid">
            <div class="field"><label for="nsName">{{ T('fileName') }}</label><input id="nsName" v-model="nsName" class="input mono" data-testid="scripts-ns-name" @keydown.enter="createScript"></div>
            <div class="field">
              <span class="field-label">{{ T('type') }}</span>
              <div class="seg" role="group" data-testid="scripts-ns-kind">
                <button type="button" :aria-pressed="nsKind === 'change'" @click="nsKind = 'change'">{{ T('kindChange') }}</button>
                <button type="button" :aria-pressed="nsKind === 'full'" @click="nsKind = 'full'">{{ T('kindFull') }}</button>
              </div>
            </div>
            <div class="field">
              <label for="nsDev">{{ T('baseDevice') }}</label>
              <select id="nsDev" v-model="nsDev" class="select" data-testid="scripts-ns-device">
                <option :value="null">{{ T('noBaseOpt') }}</option>
                <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.name }}{{ d.source === 'public' ? ` · ${$t('proj.src.public')}` : '' }}</option>
              </select>
              <div v-if="!devices.length" class="hint">{{ T('noDevices') }}</div>
            </div>
            <div v-if="nsDev !== null" class="field">
              <label for="nsVer">{{ T('baseVersion') }}</label>
              <select id="nsVer" v-model="nsVer" class="select" data-testid="scripts-ns-version">
                <option :value="null">{{ followLabel }}</option>
                <option v-for="v in nsVers" :key="v.id" :value="v.id">{{ T('pinVer', { n: v.seq }) }}</option>
              </select>
              <div class="hint">{{ nsDevice?.source === 'public' ? T('hintPublic') : T('hintPrivate') }}</div>
            </div>
          </div>
          <p v-if="nsKind === 'full' && nsDev !== null" class="small faint">{{ T('hintFull') }}</p>
          <div class="row wrap" style="gap: 18px">
            <label class="check"><span class="switch"><input v-model="nsOrder" type="checkbox" :disabled="nsKind === 'full'"><span /></span><span>{{ T('orderCheck') }}</span></label>
            <label v-if="ai.configured" class="check"><span class="switch"><input v-model="nsAi" type="checkbox"><span /></span><span>{{ T('aiCheck') }}</span></label>
          </div>
          <div v-if="nsErr" class="notice err" data-testid="scripts-ns-error"><Icon name="err" /><div>{{ nsErr }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="showNew = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="nsBusy" data-testid="scripts-ns-create" @click="createScript">{{ T('create') }}</button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.devcell { flex-wrap: wrap; }
.m6av { width: 20px; height: 20px; font-size: 10.5px; vertical-align: middle; }
</style>
