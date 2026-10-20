<script setup lang="ts">
/**
 * 顶栏网络切换器（M9，REQ-045；预览 DevelopDocs/ui-preview/M9/switcher.html，评审选“项目 › 网络两个切换器并排”）：
 * 第一项“全部设备”（项目层的设备池），下面按文件夹列出网络；可以搜索，方向键选择、Enter 切换，Alt+N 打开。
 * 切换时：按网络的页面换掉网址里的网络（选“全部设备”回到项目层网址）；只在项目层的页面（设备池管理、网络管理……）
 * 选网络时进入那个网络的概览。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteParamsRaw } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { errorText } from '@/api'
import { useProject } from '@/stores/project'
import { useNetwork } from '@/stores/network'
import { basePage, pageNet } from '@/project/scope'
import { colorClass, matchNet, netName, netTree, type NetRow } from '@/views/networks/logic'

const project = useProject()
const network = useNetwork()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const open = ref(false)
const q = ref('')
const kb = ref(-1)
const err = ref('')
const searchEl = ref<HTMLInputElement | null>(null)

const cur = computed(() => network.info)
const isAll = computed(() => !network.cur || !cur.value)
const label = (n: NetRow) => netName(n, t('net.defaultName'))
const allLabel = computed(() => t('net.all'))
const curLabel = computed(() => (isAll.value ? allLabel.value : label(cur.value!)))
const curCount = computed(() => (isAll.value ? network.list?.overview.devices : cur.value?.counts.devices))

const tree = computed(() => netTree(network.list))
const showAll = computed(() => matchNet({ name: allLabel.value, slug: 'all' }, q.value))
const root = computed(() => tree.value.root.filter((n) => matchNet(n, q.value, null, label(n))))
const folders = computed(() =>
  tree.value.folders.map((f) => ({ folder: f.folder, nets: f.nets.filter((n) => matchNet(n, q.value, f.folder.name, label(n))) })).filter((f) => f.nets.length),
)
/** 方向键能走到的项（null = 全部设备） */
const items = computed<(string | null)[]>(() => [...(showAll.value ? [null] : []), ...root.value.map((n) => n.slug), ...folders.value.flatMap((f) => f.nets.map((n) => n.slug))])
const total = computed(() => network.networks.length)

/** 当前页面在目标网络里的网址（显示在弹层底部） */
const urlOf = computed(() => route.path)

async function toggle(): Promise<void> {
  open.value = !open.value
  if (!open.value) return
  q.value = ''
  kb.value = -1
  err.value = ''
  if (project.ref) {
    try { await network.load(project.ref, true) } catch (e) { err.value = errorText(e) }
  }
  await nextTick()
  searchEl.value?.focus()
}
function close(): void { open.value = false; q.value = ''; kb.value = -1 }

async function go(slug: string | null): Promise<void> {
  close()
  if (!project.ref) return
  const page = basePage(route.name)
  const level = route.meta.project ? pageNet(page) : undefined
  if (level) {
    // 换网络后脚本编号不再有效：回到脚本列表；设备编号保留（设备可能也在目标网络里，不在时页面提示不存在）
    const params: RouteParamsRaw = { ...route.params, network: slug }
    let name = page
    if (page === 'check-project') { name = 'scripts'; delete params.id }
    await router.push({ name, params, query: keepQuery() })
    return
  }
  if (slug) await router.push({ name: 'network-home', params: { project: project.ref, network: slug } })
  else network.cur = null
}
function keepQuery(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const k of ['mode', 'view', 'baseline']) if (typeof route.query[k] === 'string') out[k] = route.query[k] as string
  return out
}

function onKeyList(e: KeyboardEvent): void {
  const n = items.value.length
  if (!n) return
  if (e.key === 'ArrowDown') { e.preventDefault(); kb.value = Math.min(n - 1, kb.value + 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); kb.value = Math.max(0, kb.value - 1) }
  else if (e.key === 'Enter' && kb.value >= 0) { e.preventDefault(); void go(items.value[kb.value]) }
}
watch(q, (v) => { kb.value = v ? 0 : -1 })
const isKb = (slug: string | null) => kb.value >= 0 && items.value[kb.value] === slug

function onDoc(e: MouseEvent): void {
  if (open.value && !(e.target as HTMLElement).closest?.('.nw-sw')) close()
}
function onKey(e: KeyboardEvent): void {
  if (e.altKey && (e.key === 'n' || e.key === 'N') && project.ref) { e.preventDefault(); void toggle(); return }
  if (e.key === 'Escape' && open.value) close()
}
onMounted(() => { document.addEventListener('click', onDoc); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onKey) })
watch(() => route.fullPath, close)
// 换了项目：读新项目的网络列表（切换器显示设备数）
watch(() => project.ref, (r) => { if (r) void network.load(r).catch(() => undefined) }, { immediate: true })
</script>

<template>
  <span v-if="project.ref" class="nw-sep" aria-hidden="true"><Icon name="chevR" small /></span>
  <div v-if="project.ref" :class="['nw-sw', isAll ? 'nc-all is-all' : colorClass(cur?.color)]" data-testid="network-switcher">
    <button type="button" class="nw-btn" aria-haspopup="listbox" :aria-expanded="open" :title="$t('net.switchTip')" data-testid="network-switcher-button" @click.stop="toggle">
      <i :class="['nw-sq', { all: isAll }]" />
      <span class="sw-k">{{ $t('net.label') }}</span>
      <span class="sw-cur" data-testid="network-current">{{ curLabel }}</span>
      <span v-if="curCount !== undefined" class="cnt">{{ curCount }}</span>
      <Icon name="chevD" small />
    </button>
    <div v-if="open" class="nw-pop" @click.stop>
      <label class="input-wrap nw-search">
        <Icon name="search" small />
        <input ref="searchEl" v-model="q" class="input" type="search" :placeholder="$t('net.search')" :aria-label="$t('net.search')" data-testid="network-switcher-search" @keydown="onKeyList">
      </label>
      <div v-if="err" class="notice err" style="margin: 0 10px 6px"><Icon name="err" /><div>{{ err }}</div></div>
      <div class="nw-list" role="listbox" :aria-label="$t('nav.networks')">
        <button v-if="showAll" type="button" role="option" :aria-selected="isAll" :class="['nw-item all-item nc-all', { 'is-cur': isAll, 'is-kb': isKb(null) }]" data-testid="nsw-all" @click="go(null)">
          <span class="ck"><Icon v-if="isAll" name="check" small /></span><i class="nw-sq all" />
          <span class="main"><span class="n">{{ allLabel }}</span><span class="m">{{ $t('net.allMeta', { n: network.list?.overview.devices ?? 0 }) }}</span></span>
        </button>
        <template v-if="root.length">
          <div class="nw-gh">{{ $t('nav.networks') }}<b>{{ total }}</b></div>
          <button v-for="n in root" :key="n.slug" type="button" role="option" :aria-selected="n.slug === network.cur" :class="['nw-item', colorClass(n.color), { 'is-cur': n.slug === network.cur && !isAll, 'is-kb': isKb(n.slug) }]" :data-testid="`nsw-${n.slug}`" @click="go(n.slug)">
            <span class="ck"><Icon v-if="n.slug === network.cur && !isAll" name="check" small /></span><i class="nw-sq" />
            <span class="main">
              <span class="n">{{ label(n) }}<span v-if="n.default" class="nw-def">{{ $t('net.default') }}</span></span>
              <span class="m">{{ $t('net.devices', { n: n.counts.devices }) }}{{ n.default ? $t('net.metaDefault') : n.counts.shared ? $t('net.metaShared', { n: n.counts.shared }) : '' }}</span>
            </span>
          </button>
        </template>
        <template v-for="f in folders" :key="f.folder.id">
          <div class="nw-gh"><Icon name="folder" small />{{ f.folder.name }}<b>{{ f.nets.length }}</b></div>
          <button v-for="n in f.nets" :key="n.slug" type="button" role="option" :aria-selected="n.slug === network.cur" :class="['nw-item in-folder', colorClass(n.color), { 'is-cur': n.slug === network.cur && !isAll, 'is-kb': isKb(n.slug) }]" :data-testid="`nsw-${n.slug}`" @click="go(n.slug)">
            <span class="ck"><Icon v-if="n.slug === network.cur && !isAll" name="check" small /></span><i class="nw-sq" />
            <span class="main">
              <span class="n">{{ label(n) }}</span>
              <span class="m">{{ $t('net.devices', { n: n.counts.devices }) }}{{ n.counts.shared ? $t('net.metaShared', { n: n.counts.shared }) : '' }}</span>
            </span>
          </button>
        </template>
        <div v-if="!items.length" class="nw-none">{{ $t('net.noMatch', { q }) }}</div>
      </div>
      <div class="nw-url"><Icon name="link" small /><code>{{ urlOf }}</code></div>
      <div class="nw-foot">
        <router-link :to="{ name: 'networks', params: { project: project.ref }, query: { new: '1' } }" class="btn btn-sm" data-testid="nsw-new"><Icon name="plus" small />{{ $t('net.new') }}</router-link>
        <router-link :to="{ name: 'networks', params: { project: project.ref } }" class="btn btn-sm btn-ghost" data-testid="nsw-manage">{{ $t('net.manage') }}</router-link>
        <span class="nw-kbd"><kbd>↑</kbd><kbd>↓</kbd><kbd>Enter</kbd></span>
      </div>
    </div>
  </div>
</template>
