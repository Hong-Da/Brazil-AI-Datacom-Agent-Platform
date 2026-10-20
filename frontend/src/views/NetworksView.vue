<script setup lang="ts">
/**
 * 网络列表与管理（M9，/p/<项目>/networks；预览 DevelopDocs/ui-preview/M9/networks.html）：
 * 项目概览（全部设备的汇总）、按文件夹列出网络（拖动手柄放进或移出文件夹）、新建 / 改名与移动 / 复制 / 删除网络、
 * 文件夹的新建、改名、删除，以及网络之间共用设备的矩阵。评审决定：删除不进回收站，确认时列出内容并输入网络名；
 * 默认网络可以改名、不能删除；识别色按创建顺序自动分配，可以换成组内其他颜色；复制时一起复制工作数据（已采纳的 AI 结果
 * 与采纳记录注明复制自哪里，待处理的建议不复制）。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import NetChip from '@/components/net-chip.vue'
import NetUpgrade from '@/components/net-upgrade.vue'
import { del, errorText, get, post, put } from '@/api'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { shortTime } from './account/account'
import {
  colorClass, netActivityKey, netName, netOrder, netTree, overlapMatrix, PALETTE, SLUG_RE, slugify,
  type DeletePreview, type DevNet, type NetRow,
} from './networks/logic'

const route = useRoute()
const router = useRouter()
const project = useProject()
const network = useNetwork()
const { t } = useI18n()

const err = ref('')
const msg = ref('')
const canWrite = computed(() => project.canWrite)
const list = computed(() => network.list)
const tree = computed(() => netTree(list.value))
const ov = computed(() => list.value?.overview)
const closed = ref<Set<number>>(new Set())
const label = (n: Pick<NetRow, 'name' | 'default'>) => netName(n, t('net.defaultName'))
const helpOpen = ref(false)
const missing = computed(() => (typeof route.query.missing === 'string' ? route.query.missing : ''))

// 共用矩阵：项目层设备列表每行的 networks
const devNets = ref<{ networks?: DevNet[] }[]>([])
const matrixNets = computed(() => netOrder(list.value))
const matrix = computed(() => overlapMatrix(matrixNets.value, devNets.value))

async function load(force = true): Promise<void> {
  if (!project.ref) return
  err.value = ''
  try {
    await network.load(project.ref, force)
    devNets.value = (await get<{ devices: { networks?: DevNet[] }[] }>('/devices')).devices
  } catch (e) {
    err.value = errorText(e)
  }
}
async function act(fn: () => Promise<unknown>, ok?: string): Promise<boolean> {
  err.value = ''
  msg.value = ''
  try {
    await fn()
    if (ok) msg.value = ok
    await load()
    return true
  } catch (e) {
    err.value = errorText(e)
    return false
  }
}
const netPath = (slug: string) => `/networks/${encodeURIComponent(slug)}`
const base = computed(() => `/projects/${encodeURIComponent(project.ref ?? '')}`)
const urlPre = computed(() => `/p/${project.ref ?? ''}/n/`)

function actText(n: NetRow): string {
  const a = n.last_activity
  if (!a) return '—'
  const k = netActivityKey(a.action)
  return k ? t(`net.act.${k}`) : a.action
}
function sharedWith(n: NetRow): NetRow[] {
  const i = matrixNets.value.findIndex((x) => x.id === n.id)
  if (i < 0) return []
  return matrixNets.value.filter((x, j) => j !== i && !x.default && matrix.value[i][j] > 0)
}

// ---------------------------------------------------------------- 拖动整理
const drag = ref<string | null>(null)
const dropOn = ref<string | null>(null) // 'f:<id>' | 'root'
function onDragStart(e: DragEvent, n: NetRow): void {
  if (!canWrite.value) return
  drag.value = n.slug
  try { e.dataTransfer?.setData('text/plain', n.slug) } catch { /* 忽略 */ }
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
function onDragOver(e: DragEvent, target: string): void {
  if (!drag.value) return
  e.preventDefault()
  dropOn.value = target
}
async function onDrop(e: DragEvent, folderId: number | null): Promise<void> {
  e.preventDefault()
  const slug = drag.value
  drag.value = null
  dropOn.value = null
  if (!slug) return
  const n = list.value?.networks.find((x) => x.slug === slug)
  if (!n || n.folder_id === folderId) return
  await act(() => put(`${base.value}${netPath(slug)}`, { folder_id: folderId, move: true }), folderId ? t('net.movedIn') : t('net.movedOut'))
}

// ---------------------------------------------------------------- 新建网络
const newOpen = ref(false)
const nf = reactive({ name: '', slug: '', slugTouched: false, folder: '' as string, color: '' as string, start: 'empty' as 'empty' | 'sugg', busy: false })
function openNew(): void {
  Object.assign(nf, { name: '', slug: '', slugTouched: false, folder: '', color: '', start: 'empty', busy: false })
  newOpen.value = true
  void nextTick(() => (document.getElementById('nwName') as HTMLInputElement | null)?.focus())
}
watch(() => nf.name, (v) => { if (!nf.slugTouched) nf.slug = slugify(v, '') })
const slugOk = (s: string) => !s || SLUG_RE.test(s)
async function createNet(): Promise<void> {
  if (nf.start === 'sugg') {
    newOpen.value = false
    await router.push({ name: 'network-suggest', params: { project: project.ref } })
    return
  }
  if (!nf.name.trim() || !slugOk(nf.slug)) return
  nf.busy = true
  err.value = ''
  try {
    const n = await post<NetRow>(`${base.value}/networks`, {
      name: nf.name.trim(),
      slug: nf.slug || null,
      folder_id: nf.folder ? Number(nf.folder) : null,
      color: nf.color || null,
    })
    newOpen.value = false
    await network.load(project.ref ?? '', true)
    await router.push({ name: 'members', params: { project: project.ref, network: n.slug }, query: { created: '1' } })
  } catch (e) {
    err.value = errorText(e)
  } finally {
    nf.busy = false
  }
}

// ---------------------------------------------------------------- 改名 / 移动 / 颜色
const ren = ref<NetRow | null>(null)
const rf = reactive({ name: '', slug: '', folder: '', color: '' })
function openRen(n: NetRow): void {
  ren.value = n
  Object.assign(rf, { name: label(n), slug: n.slug, folder: n.folder_id ? String(n.folder_id) : '', color: n.color })
}
async function saveRen(): Promise<void> {
  const n = ren.value
  if (!n || !rf.name.trim() || !SLUG_RE.test(rf.slug)) return
  const body: Record<string, unknown> = { folder_id: rf.folder ? Number(rf.folder) : null, move: true, color: rf.color }
  if (rf.name.trim() !== label(n)) body.name = rf.name.trim()
  if (rf.slug !== n.slug) body.slug = rf.slug
  const ok = await act(() => put(`${base.value}${netPath(n.slug)}`, body), t('net.saved'))
  if (ok) {
    ren.value = null
    // 改了当前网络的标识：网址跟着换
    if (route.params.network === n.slug && rf.slug !== n.slug) network.cur = rf.slug
  }
}

// ---------------------------------------------------------------- 复制
const copySrc = ref<NetRow | null>(null)
const cf = reactive({ name: '', slug: '', busy: false })
const copyPreview = ref<DeletePreview | null>(null)
async function openCopy(n: NetRow): Promise<void> {
  copySrc.value = n
  Object.assign(cf, { name: t('net.copyName', { n: label(n) }), slug: slugify(`${n.slug}-copy`), busy: false })
  copyPreview.value = null
  try { copyPreview.value = await get<DeletePreview>(`${base.value}${netPath(n.slug)}/delete-preview`) } catch { /* 只是计数 */ }
}
async function doCopy(): Promise<void> {
  const n = copySrc.value
  if (!n || !cf.name.trim() || !slugOk(cf.slug)) return
  cf.busy = true
  const ok = await act(() => post(`${base.value}${netPath(n.slug)}/copy`, { name: cf.name.trim(), slug: cf.slug || undefined }), t('net.copied'))
  cf.busy = false
  if (ok) copySrc.value = null
}

// ---------------------------------------------------------------- 删除
const delNet = ref<NetRow | null>(null)
const delPreview = ref<DeletePreview | null>(null)
const typed = ref('')
async function openDel(n: NetRow): Promise<void> {
  delNet.value = n
  typed.value = ''
  delPreview.value = null
  try { delPreview.value = await get<DeletePreview>(`${base.value}${netPath(n.slug)}/delete-preview`) } catch (e) { err.value = errorText(e) }
  void nextTick(() => (document.getElementById('nwDelType') as HTMLInputElement | null)?.focus())
}
const delOk = computed(() => !!delNet.value && [delNet.value.name, delNet.value.slug].includes(typed.value.trim()))
async function doDel(): Promise<void> {
  const n = delNet.value
  if (!n || !delOk.value) return
  const ok = await act(() => del(`${base.value}${netPath(n.slug)}?confirm=${encodeURIComponent(typed.value.trim())}`), t('net.deleted'))
  if (ok) {
    delNet.value = null
    if (network.cur === n.slug) network.cur = null
  }
}

// ---------------------------------------------------------------- 文件夹
const folderDlg = ref<{ id: number | null; name: string } | null>(null)
function openFolder(id: number | null = null, name = ''): void {
  folderDlg.value = { id, name }
  void nextTick(() => (document.getElementById('nwFolderName') as HTMLInputElement | null)?.focus())
}
async function saveFolder(): Promise<void> {
  const f = folderDlg.value
  if (!f || !f.name.trim()) return
  const ok = await act(() => (f.id ? put(`${base.value}/network-folders/${f.id}`, { name: f.name.trim() }) : post(`${base.value}/network-folders`, { name: f.name.trim() })), f.id ? t('net.saved') : t('net.folderCreated'))
  if (ok) folderDlg.value = null
}
async function delFolder(id: number): Promise<void> {
  await act(() => del(`${base.value}/network-folders/${id}`), t('net.folderDeleted'))
}
function toggleFolder(id: number): void {
  const s = new Set(closed.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  closed.value = s
}

function onKey(e: KeyboardEvent): void {
  if (e.key !== 'Escape') return
  newOpen.value = false
  ren.value = null
  copySrc.value = null
  delNet.value = null
  folderDlg.value = null
}
onMounted(async () => {
  document.addEventListener('keydown', onKey)
  await load()
  if (route.query.new === '1' && canWrite.value) {
    openNew()
    void router.replace({ query: { ...route.query, new: undefined } })
  }
})
watch(() => project.ref, () => void load())
</script>

<template>
  <main class="main">
    <div class="page" data-testid="networks-page">
      <div class="crumbs"><span>{{ project.info?.name }}</span><span class="sep">/</span><span>{{ $t('nav.networks') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ $t('nav.networks') }}</h1>
          <p class="ph-sub">{{ $t('net.listSub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-ghost" type="button" data-testid="net-help" @click="helpOpen = !helpOpen"><Icon name="info" small />{{ $t('net.help') }}</button>
          <template v-if="canWrite">
          <router-link class="btn" :to="{ name: 'network-suggest', params: { project: project.ref } }" data-testid="to-suggest"><Icon name="wand" small />{{ $t('nav.network-suggest') }}</router-link>
          <button class="btn" type="button" data-testid="new-folder" @click="openFolder()"><Icon name="folder" small />{{ $t('net.newFolder') }}</button>
          <button class="btn btn-primary" type="button" data-testid="new-network" @click="openNew"><Icon name="plus" small />{{ $t('net.new') }}</button>
          </template>
        </div>
      </div>
      <NetUpgrade :force="helpOpen" @close="helpOpen = false" />
      <div v-if="missing" class="notice warn" style="margin-bottom: 12px" data-testid="net-missing"><Icon name="warn" /><div class="grow">{{ $t('net.missing', { n: missing }) }}</div></div>
      <div v-if="err" class="notice err" style="margin-bottom: 12px" data-testid="net-error"><Icon name="err" /><div class="grow">{{ err }}</div></div>
      <div v-if="msg" class="notice ok" style="margin-bottom: 12px" data-testid="net-msg"><Icon name="ok" /><div class="grow">{{ msg }}</div></div>

      <div v-if="ov" class="nw-kpis" style="margin-bottom: 14px" data-testid="net-overview">
        <div><b>{{ ov.devices }}</b><span>{{ $t('net.k.devices') }}</span><small>{{ $t('net.k.pool') }}</small></div>
        <div><b>{{ ov.networks }}</b><span>{{ $t('net.k.networks') }}</span><small>{{ $t('net.k.folders', { n: list?.folders.length ?? 0 }) }}</small></div>
        <div><b>{{ ov.in_several }}</b><span>{{ $t('net.k.several') }}</span><small>{{ $t('net.k.notDefault') }}</small></div>
        <div><b>{{ ov.only_default }}</b><span>{{ $t('net.k.onlyDefault') }}</span><small>{{ $t('net.k.onlyDefaultSub') }}</small></div>
        <div><b>{{ ov.imported_today }}</b><span>{{ $t('net.k.today') }}</span><small>{{ $t('net.k.todaySub', { n: ov.joined_by_rule_today }) }}</small></div>
      </div>

      <section class="panel" :aria-label="$t('nav.networks')">
        <div class="nw-tree" data-testid="net-tree">
          <div class="nw-row head">
            <span /><span>{{ $t('net.colNetwork') }}</span><span>{{ $t('net.colDevices') }}</span><span class="share">{{ $t('net.colShared') }}</span>
            <span class="act">{{ $t('net.colActivity') }}</span><span class="col-rules">{{ $t('net.colRules') }}</span><span />
          </div>
          <template v-for="sec in [{ folder: null, nets: tree.root }, ...tree.folders]" :key="sec.folder?.id ?? 'root'">
            <div
              v-if="sec.folder"
              :class="['nw-frow', { 'is-closed': closed.has(sec.folder.id), 'nw-drop': dropOn === `f:${sec.folder.id}` }]"
              :data-testid="`folder-${sec.folder.id}`"
              @dragover="onDragOver($event, `f:${sec.folder.id}`)" @dragleave="dropOn = null" @drop="onDrop($event, sec.folder.id)"
            >
              <button type="button" class="ftw" :aria-expanded="!closed.has(sec.folder.id)" :aria-label="sec.folder.name" @click="toggleFolder(sec.folder.id)"><Icon name="chevD" small /></button>
              <Icon name="folder" small /><span>{{ sec.folder.name }}</span><span class="meta">{{ $t('net.nNetworks', { n: sec.nets.length }) }}</span>
              <span v-if="canWrite" class="ops">
                <button type="button" class="btn btn-xs btn-ghost" @click="openFolder(sec.folder.id, sec.folder.name)">{{ $t('net.rename') }}</button>
                <button type="button" class="btn btn-xs btn-ghost" :title="$t('net.delFolderTip')" :data-testid="`folder-del-${sec.folder.id}`" @click="delFolder(sec.folder.id)">{{ $t('net.delFolder') }}</button>
              </span>
            </div>
            <template v-if="!sec.folder || !closed.has(sec.folder.id)">
              <div v-if="sec.folder && !sec.nets.length" class="nw-rootzone" style="padding-left: 30px">{{ $t('net.emptyFolder') }}</div>
              <div
                v-for="n in sec.nets" :key="n.slug"
                :class="['nw-row', colorClass(n.color), { 'in-folder': !!sec.folder, 'is-cur': n.slug === network.cur, 'is-dragging': drag === n.slug }]"
                :draggable="canWrite" :data-testid="`net-row-${n.slug}`"
                @dragstart="onDragStart($event, n)" @dragend="drag = null; dropOn = null"
              >
                <span class="grip" :title="$t('net.dragTip')"><Icon v-if="canWrite" name="grip" small /></span>
                <div class="nm">
                  <router-link :to="{ name: 'network-home', params: { project: project.ref, network: n.slug } }"><i class="nw-sq" />{{ label(n) }}<span v-if="n.default" class="nw-def">{{ $t('net.defaultNet') }}</span><span v-if="n.slug === network.cur" class="tag t-blue">{{ $t('net.currentTag') }}</span></router-link>
                  <span class="slug">/n/{{ n.slug }}</span>
                </div>
                <div class="num"><b>{{ n.counts.devices }}</b> {{ $t('net.unitDevices') }}</div>
                <div class="share">
                  <span v-if="n.default" class="small faint">{{ $t('net.includesAllNew') }}</span>
                  <template v-else-if="n.counts.shared">
                    <span><b>{{ n.counts.shared }}</b> {{ $t('net.sharedUnit') }}</span>
                    <span class="nw-chips"><NetChip v-for="x in sharedWith(n)" :key="x.slug" :net="x" /></span>
                  </template>
                  <span v-else class="small faint">{{ $t('net.notShared') }}</span>
                </div>
                <div class="act"><span>{{ actText(n) }}</span><small>{{ n.last_activity?.actor ?? n.created_by ?? '' }} · {{ shortTime(n.last_activity?.at ?? n.created_at) }}</small></div>
                <div class="rules col-rules">
                  <span v-if="n.default" class="nw-rulechip"><Icon name="layers" small />{{ $t('net.allNew') }}</span>
                  <span v-else-if="n.counts.rules" class="nw-rulechip"><Icon name="rules" small />{{ $t('net.nRules', { n: n.counts.rules }) }}</span>
                  <span v-else class="small faint">—</span>
                </div>
                <div class="ops">
                  <router-link class="btn btn-sm" :to="{ name: 'members', params: { project: project.ref, network: n.slug } }" :data-testid="`net-members-${n.slug}`">{{ $t('net.members') }}</router-link>
                  <template v-if="canWrite">
                    <button type="button" class="btn btn-sm btn-ghost btn-icon" :title="$t('net.renTip')" :aria-label="$t('net.renTip')" :data-testid="`net-ren-${n.slug}`" @click="openRen(n)"><Icon name="pencil" small /></button>
                    <button type="button" class="btn btn-sm btn-ghost btn-icon" :title="$t('net.copyTip')" :aria-label="$t('net.copyTip')" :data-testid="`net-copy-${n.slug}`" @click="openCopy(n)"><Icon name="copy" small /></button>
                    <button type="button" class="btn btn-sm btn-ghost btn-icon" :disabled="n.default" :title="n.default ? $t('net.defUndeletable') : $t('net.delTip')" :aria-label="$t('net.delTip')" :data-testid="`net-del-${n.slug}`" @click="openDel(n)"><Icon name="trash" small /></button>
                  </template>
                </div>
              </div>
            </template>
          </template>
          <div v-if="canWrite && tree.folders.length" :class="['nw-rootzone', { 'nw-drop': dropOn === 'root' }]" data-testid="drop-root" @dragover="onDragOver($event, 'root')" @dragleave="dropOn = null" @drop="onDrop($event, null)"><Icon name="move" small />{{ $t('net.dropRoot') }}</div>
        </div>
      </section>

      <div class="nw-notes mt16">
        <section class="panel">
          <div class="panel-h"><h2>{{ $t('net.ovmTitle') }}</h2></div>
          <div class="panel-b" style="overflow-x: auto">
            <table v-if="matrixNets.length > 1" class="nw-ovm" data-testid="net-ovm">
              <thead><tr><th /><th v-for="n in matrixNets" :key="n.slug" :title="label(n)"><span :class="['nw-chip', colorClass(n.color)]" style="background: transparent; border-color: transparent"><i class="nw-sq" /></span></th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in matrixNets" :key="a.slug">
                  <th><NetChip :net="a" /></th>
                  <td v-for="(b, j) in matrixNets" :key="b.slug" :class="i === j ? 'self' : a.default || b.default ? 'all' : matrix[i][j] ? 'hot' : 'zero'">{{ matrix[i][j] }}</td>
                </tr>
              </tbody>
            </table>
            <p class="small muted" style="margin: 10px 0 0">{{ $t('net.ovmNote') }}</p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-h"><h2>{{ $t('net.levelsTitle') }}</h2></div>
          <div class="panel-b" style="display: flex; flex-direction: column; gap: 10px">
            <div><div class="small" style="font-weight: 600; margin-bottom: 4px">{{ $t('net.levelProject') }}</div><ul><li>{{ $t('net.lp1') }}</li><li>{{ $t('net.lp2') }}</li><li>{{ $t('net.lp3') }}</li></ul></div>
            <div><div class="small" style="font-weight: 600; margin-bottom: 4px">{{ $t('net.levelNet') }}</div><ul><li>{{ $t('net.ln1') }}</li><li>{{ $t('net.ln2') }}</li><li>{{ $t('net.ln3') }}</li><li>{{ $t('net.ln4') }}</li><li>{{ $t('net.ln5') }}</li></ul></div>
          </div>
        </section>
      </div>
    </div>

    <!-- 新建网络 -->
    <div v-if="newOpen" class="modal-back" data-testid="new-network-dialog" @click.self="newOpen = false">
      <div class="modal" style="width: min(600px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwNewT">
        <div class="modal-h"><h2 id="nwNewT">{{ $t('net.new') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="newOpen = false"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 14px">
          <div class="form-grid">
            <div class="field"><label for="nwName">{{ $t('net.name') }}</label><input id="nwName" v-model="nf.name" class="input" data-testid="new-name" :disabled="nf.start === 'sugg'"></div>
            <div class="field"><label for="nwFolder">{{ $t('net.inFolder') }}</label><select id="nwFolder" v-model="nf.folder" class="select" :disabled="nf.start === 'sugg'"><option value="">{{ $t('net.noFolder') }}</option><option v-for="f in list?.folders ?? []" :key="f.id" :value="String(f.id)">{{ f.name }}</option></select></div>
          </div>
          <div class="field">
            <label for="nwSlug">{{ $t('net.slug') }}</label>
            <div class="nw-slugrow"><span class="pre">{{ urlPre }}</span><input id="nwSlug" v-model="nf.slug" class="input mono" data-testid="new-slug" :disabled="nf.start === 'sugg'" @input="nf.slugTouched = true"></div>
            <div :class="['hint', { err: !slugOk(nf.slug) }]">{{ $t('net.slugHint') }}</div>
          </div>
          <div class="field">
            <span class="field-label">{{ $t('net.color') }}</span>
            <div class="nw-colors" role="group" :aria-label="$t('net.color')">
              <button type="button" class="btn btn-xs" :aria-pressed="!nf.color" style="width: auto; background: var(--surface); padding: 0 8px" @click="nf.color = ''">{{ $t('net.colorAuto') }}</button>
              <button v-for="c in PALETTE" :key="c" type="button" :class="colorClass(c)" :aria-pressed="nf.color === c" :title="$t(`net.colors.${c}`)" :aria-label="$t(`net.colors.${c}`)" @click="nf.color = c" />
            </div>
          </div>
          <div class="field">
            <span class="field-label">{{ $t('net.startFrom') }}</span>
            <div class="radio-cards">
              <label class="radio-card"><input v-model="nf.start" type="radio" value="empty"><div><div class="rc-t">{{ $t('net.startEmpty') }}</div><div class="rc-d">{{ $t('net.startEmptyD') }}</div></div></label>
              <label class="radio-card"><input v-model="nf.start" type="radio" value="sugg" data-testid="new-from-sugg"><div><div class="rc-t">{{ $t('net.startSugg') }}</div><div class="rc-d">{{ $t('net.startSuggD') }}</div></div></label>
            </div>
          </div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="newOpen = false">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="nf.busy || (nf.start === 'empty' && (!nf.name.trim() || !slugOk(nf.slug)))" data-testid="new-create" @click="createNet">{{ nf.start === 'sugg' ? $t('net.toSugg') : $t('net.create') }}</button>
        </div>
      </div>
    </div>

    <!-- 改名 / 移动 / 颜色 -->
    <div v-if="ren" class="modal-back" data-testid="rename-dialog" @click.self="ren = null">
      <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwRenT">
        <div class="modal-h"><h2 id="nwRenT">{{ $t('net.renTip') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="ren = null"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 14px">
          <div class="field"><label for="nwRName">{{ $t('net.name') }}</label><input id="nwRName" v-model="rf.name" class="input" data-testid="ren-name"></div>
          <div class="field">
            <label for="nwRSlug">{{ $t('net.slug') }}</label>
            <div class="nw-slugrow"><span class="pre">{{ urlPre }}</span><input id="nwRSlug" v-model="rf.slug" class="input mono" data-testid="ren-slug"></div>
            <div :class="['hint', { err: !SLUG_RE.test(rf.slug) }]">{{ $t('net.slugChangeHint') }}</div>
          </div>
          <div class="field"><label for="nwRFolder">{{ $t('net.inFolder') }}</label><select id="nwRFolder" v-model="rf.folder" class="select"><option value="">{{ $t('net.noFolder') }}</option><option v-for="f in list?.folders ?? []" :key="f.id" :value="String(f.id)">{{ f.name }}</option></select><div class="hint">{{ $t('net.dragAlso') }}</div></div>
          <div class="field">
            <span class="field-label">{{ $t('net.color') }}</span>
            <div class="nw-colors" role="group" :aria-label="$t('net.color')">
              <button v-for="c in PALETTE" :key="c" type="button" :class="colorClass(c)" :aria-pressed="rf.color === c" :title="$t(`net.colors.${c}`)" :aria-label="$t(`net.colors.${c}`)" :data-testid="`ren-color-${c}`" @click="rf.color = c" />
            </div>
          </div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="ren = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="!rf.name.trim() || !SLUG_RE.test(rf.slug)" data-testid="ren-save" @click="saveRen">{{ $t('c.save') }}</button>
        </div>
      </div>
    </div>

    <!-- 复制 -->
    <div v-if="copySrc" class="modal-back" data-testid="copy-dialog" @click.self="copySrc = null">
      <div class="modal" style="width: min(640px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwCopyT">
        <div class="modal-h"><h2 id="nwCopyT">{{ $t('net.copyTitle', { n: label(copySrc) }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="copySrc = null"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 14px">
          <div class="form-grid">
            <div class="field"><label for="nwCName">{{ $t('net.copyNewName') }}</label><input id="nwCName" v-model="cf.name" class="input" data-testid="copy-name"></div>
            <div class="field"><label for="nwCSlug">{{ $t('net.slug') }}</label><input id="nwCSlug" v-model="cf.slug" class="input mono" data-testid="copy-slug"></div>
          </div>
          <div class="field">
            <span class="field-label">{{ $t('net.copyWhat') }}</span>
            <div class="nw-dlist" data-testid="copy-what">
              <span>{{ $t('net.cw.members') }}</span><b>{{ copyPreview?.counts.members ?? '…' }}</b>
              <span>{{ $t('net.cw.rules') }}</span><b>{{ copyPreview?.counts.rules ?? '…' }}</b>
              <span>{{ $t('net.cw.annotations') }}</span><b>{{ copyPreview?.counts.annotations ?? '…' }}</b>
              <span>{{ $t('net.cw.checks') }}</span><b>{{ copyPreview ? copyPreview.counts.ignores + copyPreview.counts.overrides : '…' }}</b>
              <span>{{ $t('net.cw.scripts') }}</span><b>{{ copyPreview ? $t('net.cw.scriptsN', { s: copyPreview.counts.scripts, r: copyPreview.counts.revisions }) : '…' }}</b>
              <span>{{ $t('net.cw.ai') }}</span><b>{{ copyPreview?.counts.ai_adopted ?? '…' }}</b>
            </div>
            <div class="hint">{{ $t('net.cw.aiNote') }}</div>
          </div>
          <div class="notice info"><Icon name="info" /><div class="grow small">{{ $t('net.copyNote') }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="copySrc = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="cf.busy || !cf.name.trim() || !slugOk(cf.slug)" data-testid="copy-go" @click="doCopy">{{ $t('net.copyGo') }}</button>
        </div>
      </div>
    </div>

    <!-- 删除 -->
    <div v-if="delNet" class="modal-back" data-testid="delete-dialog" @click.self="delNet = null">
      <div class="modal" style="width: min(560px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwDelT">
        <div class="modal-h"><h2 id="nwDelT">{{ $t('net.delTitle', { n: label(delNet) }) }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="delNet = null"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 14px">
          <div class="small muted">{{ $t('net.delLead') }}</div>
          <div class="nw-dlist" data-testid="delete-what">
            <span>{{ $t('net.cw.annotations') }}</span><b>{{ delPreview?.counts.annotations ?? '…' }}</b>
            <span>{{ $t('net.dw.checks') }}</span><b>{{ delPreview ? $t('net.dw.checksN', { i: delPreview.counts.ignores, o: delPreview.counts.overrides }) : '…' }}</b>
            <span>{{ $t('net.cw.scripts') }}</span><b>{{ delPreview ? $t('net.cw.scriptsN', { s: delPreview.counts.scripts, r: delPreview.counts.revisions }) : '…' }}</b>
            <span>{{ $t('net.dw.ai') }}</span><b>{{ delPreview ? $t('net.dw.aiN', { b: delPreview.counts.ai_batches, s: delPreview.counts.ai_suggestions }) : '…' }}</b>
            <span>{{ $t('net.cw.rules') }}</span><b>{{ delPreview?.counts.rules ?? '…' }}</b>
          </div>
          <div class="nw-keep"><Icon name="ok" small /><span>{{ $t('net.delKeep', { n: delPreview?.counts.members ?? delNet.counts.devices, s: delNet.counts.shared }) }}</span></div>
          <div class="field"><label for="nwDelType">{{ $t('net.delType', { n: delNet.name }) }}</label><input id="nwDelType" v-model="typed" class="input nw-typed" autocomplete="off" data-testid="delete-type"></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="delNet = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-danger-solid" type="button" :disabled="!delOk" data-testid="delete-go" @click="doDel">{{ $t('net.delGo') }}</button>
        </div>
      </div>
    </div>

    <!-- 文件夹 -->
    <div v-if="folderDlg" class="modal-back" data-testid="folder-dialog" @click.self="folderDlg = null">
      <div class="modal" style="width: min(440px, 100%)" role="dialog" aria-modal="true" aria-labelledby="nwFT">
        <div class="modal-h"><h2 id="nwFT">{{ folderDlg.id ? $t('net.renameFolder') : $t('net.newFolder') }}</h2><button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="folderDlg = null"><Icon name="x" /></button></div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 10px">
          <div class="field"><label for="nwFolderName">{{ $t('net.name') }}</label><input id="nwFolderName" v-model="folderDlg.name" class="input" data-testid="folder-name" @keydown.enter="saveFolder"></div>
          <div class="hint small faint">{{ $t('net.folderHint') }}</div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="folderDlg = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" :disabled="!folderDlg.name.trim()" data-testid="folder-save" @click="saveFolder">{{ folderDlg.id ? $t('c.save') : $t('net.createFolder') }}</button>
        </div>
      </div>
    </div>
  </main>
</template>
