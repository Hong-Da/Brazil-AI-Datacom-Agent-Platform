<script setup lang="ts">
/** 配置检查项目列表（REQ-031，预览 REQ-031/projects.html）：概况、筛选、项目表、新建项目。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import DevChip from '@/components/m4-dev.vue'
import { errorText, get } from '@/api'
import { useAuth } from '@/stores/auth'
import type { VersionInfo } from '@/views/compare/types'
import NewProjectDialog from './check-projects/NewProjectDialog.vue'
import { filterProjects, fmtTime, projectStats, vendorOf, type ProjectFilter } from './check-projects/logic'
import type { AiRules, Project } from './check-projects/types'
import '@/styles/req031.css'

const { t } = useI18n()
const T = (k: string, p?: Record<string, unknown>) => t(`check-projects.${k}`, p ?? {})
const router = useRouter()
const auth = useAuth()

const list = ref<Project[] | null>(null)
const loadErr = ref('')
const ai = ref<AiRules>({ configured: false, rules: [] })
const verSeq = ref<Record<number, number>>({})
const showNew = ref(false)
const f = ref<ProjectFilter>({ scope: 'all', q: '', vendor: '', me: null })

const me = computed(() => auth.me?.username ?? null)
const rows = computed(() => filterProjects(list.value ?? [], { ...f.value, me: me.value }))
const stats = computed(() => projectStats(list.value ?? [], me.value))
const showOwner = computed(() => auth.isAdmin && f.value.scope === 'all')

async function load(): Promise<void> {
  loadErr.value = ''
  try {
    const [r, a] = await Promise.all([
      get<{ projects: Project[] }>('/check-projects'),
      get<AiRules>('/check-projects/ai-rules').catch(() => ({ configured: false, rules: [] })),
    ])
    list.value = r.projects
    ai.value = a
    void loadPinned(r.projects)
  } catch (e) { loadErr.value = errorText(e) }
}

/** 固定版本的项目：取设备的版本列表，显示版本序号。 */
async function loadPinned(ps: Project[]): Promise<void> {
  const devs = [...new Set(ps.filter((p) => p.version_id !== null && p.device_id !== null).map((p) => p.device_id as number))]
  for (const id of devs) {
    try {
      const vs = (await get<{ versions: VersionInfo[] }>(`/devices/${id}/versions`)).versions
      verSeq.value = { ...verSeq.value, ...Object.fromEntries(vs.map((v) => [v.id, v.seq])) }
    } catch { /* 显示不了序号时只写“指定版本” */ }
  }
}

function onCreated(p: Project): void {
  showNew.value = false
  void router.push({ name: 'check-project', params: { id: p.id } })
}

onMounted(() => { void auth.load(); void load() })
</script>

<template>
  <main class="main">
    <div class="page r31">
      <div class="crumbs"><span>{{ $t('grp.chg') }}</span><span class="sep">/</span><span>{{ $t('nav.check-projects') }}</span></div>
      <div class="ph">
        <div class="ph-text">
          <h1>{{ T('title') }}</h1>
          <p class="ph-sub">{{ T('sub') }}</p>
        </div>
        <div class="ph-actions">
          <button class="btn btn-primary" type="button" data-testid="cp-new" @click="showNew = true"><Icon name="plus" small /><span>{{ T('newProject') }}</span></button>
        </div>
      </div>

      <div v-if="loadErr" class="notice err"><Icon name="err" /><div class="grow">{{ loadErr }}</div><button class="btn btn-sm" type="button" @click="load">{{ $t('c.retry') }}</button></div>
      <section v-else-if="list === null" class="panel"><div class="empty">{{ $t('c.loading') }}</div></section>

      <section v-else-if="!list.length" class="panel" data-testid="cp-empty">
        <div class="empty pj-empty">
          <svg class="art" viewBox="0 0 150 96" aria-hidden="true">
            <rect x="24" y="10" width="78" height="76" rx="6" fill="var(--surface-2)" stroke="var(--line-strong)" />
            <g font-family="Consolas, monospace" font-size="7" fill="var(--ink-3)"><text x="44" y="26">system-view</text><text x="44" y="38">interface GE0/2/2</text><text x="48" y="50">ip binding …</text><text x="44" y="62">bgp 65000</text><text x="44" y="74">commit</text></g>
            <rect x="24" y="10" width="14" height="76" rx="6" fill="var(--surface-3)" />
            <circle cx="31" cy="36" r="3" fill="var(--red)" /><circle cx="31" cy="48" r="3" fill="var(--amber)" />
            <path d="M36 51 q4 -3 8 0 t8 0 t8 0 t8 0 t8 0" fill="none" stroke="var(--amber)" stroke-width="1.2" />
            <rect x="94" y="30" width="42" height="40" rx="5" fill="var(--surface)" stroke="var(--blue-line)" />
            <path d="M102 42h26M102 50h20M102 58h24" stroke="var(--line-strong)" stroke-width="2" stroke-linecap="round" />
          </svg>
          <h3>{{ T('emptyTitle') }}</h3>
          <p>{{ T('emptyText') }}</p>
          <button class="btn btn-primary" type="button" @click="showNew = true"><Icon name="plus" small /><span>{{ T('newProject') }}</span></button>
          <p class="small faint">{{ T('emptyNoDevice') }} <router-link :to="{ name: 'devices' }">{{ $t('nav.devices') }}</router-link></p>
        </div>
      </section>

      <template v-else>
        <div class="pj-strip" data-testid="cp-strip">
          <div><div class="k">{{ T('kpi.projects') }}</div><div class="v">{{ stats.total }}<small v-if="auth.isAdmin">{{ T('kpi.mine', { n: stats.mine }) }}</small></div></div>
          <div><div class="k">{{ T('kpi.withErrors') }}</div><div class="v" :style="stats.withErrors ? 'color: var(--red-ink)' : ''">{{ stats.withErrors }}</div></div>
          <div><div class="k">{{ T('kpi.scripts') }}</div><div class="v">{{ stats.scripts }}</div></div>
          <div><div class="k">{{ T('kpi.latest') }}</div><div class="v">{{ stats.latest }}<small>{{ T('kpi.latestRest') }}</small></div></div>
        </div>

        <section class="panel">
          <div class="panel-h toolbar" style="padding: 8px 12px">
            <div v-if="auth.isAdmin" class="seg" role="group" data-testid="cp-scope">
              <button type="button" :aria-pressed="f.scope === 'all'" @click="f.scope = 'all'">{{ T('scopeAll') }}</button>
              <button type="button" :aria-pressed="f.scope === 'mine'" @click="f.scope = 'mine'">{{ T('scopeMine') }}</button>
            </div>
            <label class="input-wrap" style="width: 240px"><Icon name="search" small /><input v-model="f.q" class="input" type="search" :placeholder="T('filterPh')" data-testid="cp-q"></label>
            <select v-model="f.vendor" class="select" style="width: auto" :aria-label="T('platform')">
              <option value="">{{ T('allPlatforms') }}</option>
              <option value="huawei">{{ T('plat.huawei') }}</option>
              <option value="cisco">{{ T('plat.cisco') }}</option>
              <option value="nokia">{{ T('plat.nokia') }}</option>
            </select>
            <span class="grow" />
            <span v-if="!auth.isAdmin" class="small faint">{{ T('ownOnly') }}</span>
          </div>
          <div class="tbl-wrap">
            <table class="tbl pj-tbl" data-testid="cp-table">
              <thead><tr>
                <th>{{ T('col.project') }}</th>
                <th>{{ T('baseDevice') }}</th>
                <th>{{ T('platform') }}</th>
                <th class="num">{{ T('kpi.scripts') }}</th>
                <th>{{ T('col.lastCheck') }}</th>
                <th>{{ T('orderCheck') }}</th>
                <th v-if="ai.configured">{{ T('aiCheck') }}</th>
                <th>{{ T('col.updated') }}</th>
                <th v-if="showOwner">{{ T('owner') }}</th>
                <th />
              </tr></thead>
              <tbody>
                <tr v-for="p in rows" :key="p.id" :data-testid="`cp-row-${p.id}`">
                  <td class="pj-name"><router-link :to="{ name: 'check-project', params: { id: p.id } }">{{ p.name }}</router-link><div v-if="p.description" class="d">{{ p.description }}</div></td>
                  <td>
                    <div v-if="p.device" class="pj-base">
                      <DevChip :name="p.device.name" :vendor="p.device.vendor || p.device.profile" />
                      <span v-if="p.version_id === null" class="v latest">{{ T('latest') }}</span>
                      <span v-else class="v">{{ verSeq[p.version_id] ? T('pinnedSeq', { n: verSeq[p.version_id] }) : T('pinned') }}</span>
                    </div>
                    <span v-else class="small faint">{{ T('noBaseline') }}</span>
                  </td>
                  <td class="plat">{{ vendorOf(p) ? T(`plat.${vendorOf(p)}`) : '' }}<div v-if="p.device?.profile" class="small faint mono">{{ p.device.profile }}</div></td>
                  <td class="num">{{ p.scripts }}</td>
                  <td>
                    <span v-if="!p.last_check?.checked" class="unchecked">{{ T('notChecked') }}</span>
                    <span v-else-if="!p.last_check.errors && !p.last_check.warnings" class="ls ok">{{ T('noIssues') }}</span>
                    <span v-else class="cnt">
                      <span :class="p.last_check.errors ? 'e' : 'zero'" :title="T('sev.error')"><span class="sevdot" :class="p.last_check.errors ? 'error' : ''" :style="p.last_check.errors ? '' : 'background: var(--line-strong)'" /><b>{{ p.last_check.errors }}</b></span>
                      <span :class="p.last_check.warnings ? 'w' : 'zero'" :title="T('sev.warning')"><span class="sevdot" :class="p.last_check.warnings ? 'warning' : ''" :style="p.last_check.warnings ? '' : 'background: var(--line-strong)'" /><b>{{ p.last_check.warnings }}</b></span>
                    </span>
                  </td>
                  <td><span class="onoff" :class="{ on: p.order_check }">{{ p.order_check ? T('on') : T('off') }}</span></td>
                  <td v-if="ai.configured"><span class="onoff" :class="{ on: p.ai_check }">{{ p.ai_check ? T('onRules', { n: p.ai_rules.length }) : T('off') }}</span></td>
                  <td class="small muted nowrap">{{ fmtTime(p.updated_at) }}</td>
                  <td v-if="showOwner"><span v-if="p.owner" class="owner"><i>{{ p.owner.username.charAt(0).toUpperCase() }}</i>{{ p.owner.username }}</span><span v-else class="small faint">{{ T('ownerToken') }}</span></td>
                  <td class="right"><router-link class="btn btn-sm" :to="{ name: 'check-project', params: { id: p.id } }">{{ T('open') }}</router-link></td>
                </tr>
                <tr v-if="!rows.length"><td :colspan="10" class="muted" style="text-align: center; padding: 24px">{{ T('noMatch') }}</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>
    <NewProjectDialog v-if="showNew" class="r31" :ai-configured="ai.configured" @close="showNew = false" @created="onCreated" />
  </main>
</template>

<style scoped>
.pj-tbl th.c, .pj-tbl td.c { text-align: center; }
.unchecked { font-size: 12px; color: var(--ink-3); }
</style>
