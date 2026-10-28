<script setup lang="ts">
/**
 * 顶栏项目切换器（REQ-035，预览 DevelopDocs/ui-preview/M6/devices.html）：搜索、我的项目 / 共享给我的、
 * 管理员另有“所有项目”分组（进入他人项目前确认，访问记入审计）；底部新建、管理我的项目、项目设置。
 * 切换时：在项目页面就换掉网址里的项目，在其他页面留在原页（数据随当前项目变化）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteParamsRaw } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ProjRole from '@/components/proj-role.vue'
import { errorText } from '@/api'
import { useAuth } from '@/stores/auth'
import { useProject, type ProjectRow } from '@/stores/project'
import { useStatus } from '@/stores/status'
import { matchProject } from '@/views/projects/logic'
import { basePage, projectLabel } from '@/project/scope'

const project = useProject()
const auth = useAuth()
const status = useStatus()
const route = useRoute()
const router = useRouter()

const open = ref(false)
const q = ref('')
const err = ref('')
const confirmFor = ref<ProjectRow | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)

const lists = computed(() => project.lists)
const mine = computed(() => (lists.value?.mine ?? []).filter((p) => matchProject(p, q.value)))
const shared = computed(() => (lists.value?.shared ?? []).filter((p) => matchProject(p, q.value)))
const others = computed(() => (lists.value?.others ?? []).filter((p) => matchProject(p, q.value)))

async function toggle(): Promise<void> {
  open.value = !open.value
  if (!open.value) return
  err.value = ''
  try { await project.loadLists() } catch (e) { err.value = errorText(e) }
  await nextTick()
  searchEl.value?.focus()
}
function close(): void { open.value = false; q.value = '' }

async function go(p: ProjectRow, confirmed = false): Promise<void> {
  if (p.role === 'admin' && !confirmed) { confirmFor.value = p; close(); return }
  confirmFor.value = null
  close()
  if (route.meta.project) {
    // 网络属于项目：换项目后回到项目层（“全部设备”），网络概览这类只有网络层的页面去网络列表
    const params: RouteParamsRaw = { ...route.params, project: p.ref, network: null }
    let name = basePage(route.name)
    if (name === 'check-project') { name = 'scripts'; delete params.id }
    await router.push({ name, params, query: keepQuery() })
  } else {
    try { await project.enter(p.ref) } catch (e) { err.value = errorText(e); return }
    void status.refresh()
  }
}
// 换项目后设备编号不再有效：只保留与设备无关的查询参数
function keepQuery(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const k of ['mode', 'view', 'baseline']) if (typeof route.query[k] === 'string') out[k] = route.query[k] as string
  return out
}

function onDoc(e: MouseEvent): void {
  if (open.value && !(e.target as HTMLElement).closest?.('.projsw')) close()
}
function onKey(e: KeyboardEvent): void {
  if (e.key !== 'Escape') return
  if (open.value) close()
  else confirmFor.value = null
}
onMounted(() => { document.addEventListener('click', onDoc); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onKey) })
watch(() => route.fullPath, close)
</script>

<template>
  <div class="projsw-slot">
    <div :class="['projsw', { 'is-foreign': project.foreign, 'is-open': open }]" data-testid="project-switcher">
      <button type="button" class="sw-btn" aria-haspopup="listbox" :aria-expanded="open" :title="$t('proj.switch')" data-testid="project-switcher-button" @click.stop="toggle">
        <Icon :name="project.foreign ? 'shield' : 'folder'" small />
        <span class="sw-k">{{ $t('proj.label') }}</span>
        <span class="sw-cur" data-testid="project-current">{{ project.info ? projectLabel(project.info.name, $t) : $t('proj.none') }}</span>
        <span v-if="project.role === 'read'" class="sw-ro">{{ $t('proj.readOnly') }}</span>
        <span v-if="project.foreign" class="sw-fo">{{ $t('proj.foreign') }}</span>
        <Icon name="chevD" small />
      </button>
      <div v-if="open" class="sw-pop" role="listbox" @click.stop>
        <label class="input-wrap sw-search">
          <Icon name="search" small />
          <input ref="searchEl" v-model="q" class="input" type="search" :placeholder="$t('proj.search')" data-testid="project-switcher-search">
        </label>
        <div v-if="err" class="notice err" style="margin: 0 10px 6px"><Icon name="err" /><div>{{ err }}</div></div>
        <div class="sw-list">
          <div class="sw-gh">{{ $t('proj.mine') }}<b>{{ mine.length }}</b></div>
          <div v-if="!mine.length" class="sw-none">{{ $t('proj.empty') }}</div>
          <button v-for="p in mine" :key="p.ref" type="button" role="option" :class="['sw-item', { 'is-cur': p.ref === project.ref }]" :aria-selected="p.ref === project.ref" :data-testid="`sw-item-${p.ref}`" @click="go(p)">
            <span class="sw-ic"><Icon :name="p.ref === project.ref ? 'check' : 'folder'" small /></span>
            <span class="sw-main"><span class="sw-n">{{ projectLabel(p.name, $t) }}</span><span class="sw-m">{{ $t('proj.devices', { n: p.counts.devices }) }} · {{ $t('proj.scripts', { n: p.counts.scripts }) }}</span></span>
          </button>
          <template v-if="shared.length || !auth.isAdmin">
            <div class="sw-gh">{{ $t('proj.shared') }}<b>{{ shared.length }}</b></div>
            <div v-if="!shared.length" class="sw-none">{{ $t('proj.empty') }}</div>
            <button v-for="p in shared" :key="p.ref" type="button" role="option" :class="['sw-item', { 'is-cur': p.ref === project.ref }]" :aria-selected="p.ref === project.ref" :data-testid="`sw-item-${p.ref}`" @click="go(p)">
              <span class="sw-ic"><Icon :name="p.ref === project.ref ? 'check' : 'folder'" small /></span>
              <span class="sw-main"><span class="sw-n">{{ projectLabel(p.name, $t) }}</span><span class="sw-m">{{ $t('proj.devices', { n: p.counts.devices }) }} · {{ $t('proj.scripts', { n: p.counts.scripts }) }} · {{ $t('proj.ownerIs', { u: p.owner ?? '—' }) }}</span></span>
              <ProjRole :role="p.role" />
            </button>
          </template>
          <template v-if="auth.isAdmin">
            <div class="sw-gh adm"><Icon name="shield" small />{{ $t('proj.others') }}<b>{{ others.length }}</b></div>
            <div class="sw-note">{{ $t('proj.othersNote') }}</div>
            <button v-for="p in others" :key="p.ref" type="button" role="option" :class="['sw-item', { 'is-cur': p.ref === project.ref }]" :aria-selected="p.ref === project.ref" :data-testid="`sw-item-${p.ref}`" @click="go(p)">
              <span class="sw-ic"><Icon :name="p.ref === project.ref ? 'check' : 'folder'" small /></span>
              <span class="sw-main"><span class="sw-n">{{ projectLabel(p.name, $t) }}</span><span class="sw-m">{{ $t('proj.devices', { n: p.counts.devices }) }} · {{ $t('proj.scripts', { n: p.counts.scripts }) }} · {{ $t('proj.ownerIs', { u: p.owner ?? '—' }) }}</span></span>
            </button>
          </template>
        </div>
        <div class="sw-foot">
          <router-link :to="{ name: 'projects', query: { new: '1' } }" class="btn btn-sm" data-testid="sw-new"><Icon name="plus" small />{{ $t('proj.new') }}</router-link>
          <router-link :to="{ name: 'projects' }" class="btn btn-sm btn-ghost" data-testid="sw-manage">{{ $t('proj.manage') }}</router-link>
          <router-link v-if="project.ref" :to="{ name: 'project-settings', params: { project: project.ref } }" class="btn btn-sm btn-ghost ml-auto" data-testid="sw-settings"><Icon name="gear" small />{{ $t('proj.settings') }}</router-link>
        </div>
      </div>
    </div>

    <div v-if="confirmFor" class="modal-back" data-testid="enter-foreign" @click.self="confirmFor = null">
      <div class="modal" style="width: min(480px, 100%)" role="dialog" aria-modal="true" aria-labelledby="foT">
        <div class="modal-h">
          <h2 id="foT">{{ $t('proj.enterTitle') }}</h2>
          <button class="btn btn-ghost btn-icon" type="button" :aria-label="$t('c.close')" @click="confirmFor = null"><Icon name="x" /></button>
        </div>
        <div class="modal-b" style="display: flex; flex-direction: column; gap: 12px">
          <div class="fo-who">
            <span class="m6av">{{ (confirmFor.owner ?? '?').charAt(0).toUpperCase() }}</span>
            <div><b>{{ confirmFor.name }}</b><small>{{ $t('proj.ownerIs', { u: confirmFor.owner ?? '—' }) }}{{ confirmFor.owner_disabled ? $t('proj.ownerDisabled') : '' }}</small></div>
          </div>
          <div class="notice warn"><Icon name="shield" /><div>{{ $t('proj.enterNote') }}</div></div>
        </div>
        <div class="modal-f">
          <button class="btn" type="button" @click="confirmFor = null">{{ $t('c.cancel') }}</button>
          <button class="btn btn-primary" type="button" data-testid="enter-foreign-ok" @click="go(confirmFor, true)"><Icon name="enter" small />{{ $t('proj.enter') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
