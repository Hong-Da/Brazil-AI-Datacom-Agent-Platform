<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { LOGO_SVG } from '@/components/icons'
import { LANGS } from '@/i18n'
import { usePrefs, type Theme } from '@/stores/prefs'
import { useStatus } from '@/stores/status'
import { useTerms } from '@/stores/terms'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import ProjectSwitcher from '@/components/project-switcher.vue'
import ProjRole from '@/components/proj-role.vue'
import { shortTime } from '@/views/account/account'

const prefs = usePrefs()
const status = useStatus()
const terms = useTerms()
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const project = useProject()

interface Item { name: string; icon: string; count?: () => number | undefined; tone?: string; ai?: boolean }
// proj：这一组是当前项目的页面（网址带 /p/<项目>/，REQ-035）
const NAV: { g: string; s: string; admin?: boolean; proj?: boolean; items: Item[] }[] = [
  { g: 'home', s: 'home', items: [{ name: 'dashboard', icon: 'home' }, { name: 'projects', icon: 'folders' }, { name: 'ask', icon: 'spark', ai: true }] },
  {
    g: 'dev', s: 'dev', proj: true, items: [
      { name: 'devices', icon: 'server' },
      { name: 'device-graph', icon: 'graph' },
      { name: 'device-analysis', icon: 'strata' },
      { name: 'history', icon: 'history' },
      { name: 'compare', icon: 'compare' },
      { name: 'translate', icon: 'swap' },
      { name: 'check', icon: 'shield' },
      { name: 'unknown-lines', icon: 'unknown', count: () => status.summary?.unknown.patterns, tone: 'plain' },
    ],
  },
  { g: 'chg', s: 'chg', proj: true, items: [{ name: 'scripts', icon: 'file' }, { name: 'change', icon: 'branch' }, { name: 'migration', icon: 'swap2' }] },
  {
    g: 'ana', s: 'ana', proj: true, items: [
      { name: 'impact', icon: 'target' },
      { name: 'topology', icon: 'network' },
      { name: 'consistency', icon: 'link' },
      { name: 'baseline', icon: 'shield' },
      { name: 'export', icon: 'table' },
    ],
  },
  { g: 'tpl', s: 'tpl', items: [{ name: 'templates', icon: 'stencil' }, { name: 'generate', icon: 'rows' }, { name: 'translate-rules', icon: 'rules' }] },
  {
    g: 'kb', s: 'kb', items: [
      { name: 'schema-view', icon: 'layers' },
      { name: 'schema-edit', icon: 'tree' },
      { name: 'profiles', icon: 'sliders' },
      { name: 'features', icon: 'feature' },
      { name: 'coverage', icon: 'matrix' },
      { name: 'review', icon: 'inbox', count: () => status.summary?.review.pending, tone: 'amber' },
      { name: 'ingest', icon: 'book' },
      { name: 'releases', icon: 'tag' },
    ],
  },
  { g: 'sys', s: 'sys', admin: true, items: [{ name: 'public-devices', icon: 'db' }, { name: 'all-projects', icon: 'folders' }, { name: 'ai-settings', icon: 'spark' }, { name: 'ai-skills', icon: 'skill' }, { name: 'users', icon: 'users' }] },
]
const THEMES: { v: Theme; icon: string }[] = [
  { v: 'auto', icon: 'monitor' },
  { v: 'light', icon: 'sun' },
  { v: 'dark', icon: 'moon' },
]
const kb = computed(() => status.summary?.kb)
// 普通用户看不到管理员分组（AI 接口、账号管理）
// 未配置 AI 时不显示“AI 查询”入口（D-0089），当前就在该页时保留
const nav = computed(() => NAV.filter((g) => !g.admin || auth.isAdmin).map((g) => ({ ...g, items: g.items.filter((it) => !it.ai || status.summary?.ai.configured || route.name === it.name) })))
/** 导航链接：项目页面带上当前项目。 */
function navTo(name: string, proj?: boolean): RouteLocationRaw {
  if (!proj) return { name }
  // 还不知道当前项目时给名称即可：路由会改用旧网址，守卫再跳到当前项目
  return project.slug ? { name, params: { project: project.slug } } : { name }
}
// 同一项导航对应的其他页面（清理属于检查、脚本编辑器属于项目脚本、单个 skill 属于 skill 列表）
const ALIAS: Record<string, string> = { cleanup: 'check', 'check-project': 'scripts', 'ai-skill': 'ai-skills', 'add-device': 'devices' }
const current = computed(() => ALIAS[String(route.name)] ?? String(route.name))
const roleTag = computed(() => (auth.me?.role === 'admin' ? 'admin' : auth.me?.role === 'maintainer' ? 'maintainer' : null))

// 提示条：管理员在他人项目里、只读成员、只读令牌（项目页面与首页、AI 查询这类用当前项目数据的页面）
const scopePage = computed(() => !!route.meta.project || route.name === 'dashboard' || route.name === 'ask')
const scopeBar = computed<'foreign' | 'ro' | 'token' | null>(() => {
  if (!scopePage.value || !project.info) return null
  if (project.foreign) return 'foreign'
  if (project.role === 'read') return 'ro'
  if (auth.me?.read_only) return 'token'
  return null
})
async function leave(): Promise<void> {
  const d = project.defaultSlug ?? (await project.loadDefault())
  if (!d) { await router.push({ name: 'projects' }); return }
  if (route.meta.project) await router.push({ name: route.name as string, params: { project: d } })
  else { await project.enter(d); void status.refresh() }
}
// 换了项目：外壳计数（/summary 按项目）跟着变
watch(() => project.slug, (v, old) => { if (old !== undefined && v !== old) void status.refresh() })

const menuOpen = ref(false)
const initial = computed(() => (auth.me?.username ?? '?').charAt(0).toUpperCase())

function closeMenu(): void { menuOpen.value = false }
async function signOut(): Promise<void> {
  closeMenu()
  await auth.logout()
  await router.replace({ name: 'login' })
  project.reset() // 离开项目页面后再清掉，免得页面上的链接在跳转前缺项目参数
}
function onDocClick(e: MouseEvent): void {
  if (menuOpen.value && !(e.target as HTMLElement).closest?.('.usermenu')) closeMenu()
}
function onKey(e: KeyboardEvent): void { if (e.key === 'Escape') closeMenu() }
onMounted(() => { document.addEventListener('click', onDocClick); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onKey) })
watch(() => route.fullPath, closeMenu)

onMounted(() => { status.refresh(); void terms.load() })
watch(() => route.name, () => { status.refresh(); void terms.load() })
// 知识库发布 / 回滚后术语表可能变化
watch(() => status.summary?.kb.version, (v, old) => { if (old && v !== old) void terms.load(true) })
</script>

<template>
  <div :class="['shell', { 'has-scope': scopeBar }]">
    <header class="topbar">
      <router-link class="brand" to="/">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span v-html="LOGO_SVG" style="display: contents" />
        <span class="brand-name">{{ $t('app.name') }}</span>
      </router-link>
      <ProjectSwitcher />
      <router-link v-if="kb" class="kbchip" to="/releases" :title="$t('kb.chipTitle')" data-testid="kb-chip">
        <span v-if="kb.draft_changes" class="dot" />
        KB <b>{{ kb.version }}</b>
        <span>{{ kb.draft_changes ? $t('kb.draftChanges', { n: kb.draft_changes }) : $t('kb.noDraft') }}</span>
      </router-link>
      <span class="top-spacer" />
      <div class="top-tools">
        <select v-model="prefs.lang" class="lang-select" aria-label="Language" data-testid="lang-switch">
          <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
        <div class="seg" role="group" :aria-label="$t('style.label')" :title="$t('style.tip')" data-testid="style-switch">
          <button v-for="s in terms.styles" :key="s" type="button" :aria-pressed="terms.style === s" :data-style="s" @click="terms.style = s">
            <span>{{ $t(`style.${s}`) }}</span>
          </button>
        </div>
        <div class="seg" role="group" :aria-label="$t('shell.theme')" data-testid="theme-switch">
          <button v-for="t in THEMES" :key="t.v" type="button" :aria-pressed="prefs.theme === t.v" @click="prefs.theme = t.v">
            <Icon :name="t.icon" small /><span>{{ $t(`theme.${t.v}`) }}</span>
          </button>
        </div>
        <div v-if="auth.me" class="usermenu" data-testid="user-menu">
          <button type="button" class="um-btn" :aria-expanded="menuOpen" aria-haspopup="menu" :aria-label="$t('account.menu')"
            data-testid="user-menu-button" @click="menuOpen = !menuOpen">
            <span class="av" aria-hidden="true">{{ initial }}</span>
            <span class="un">{{ auth.me.username }}</span>
            <span v-if="roleTag === 'admin'" class="tag t-teal">{{ $t('account.admin') }}</span>
            <span v-else-if="roleTag === 'maintainer'" class="tag t-amber">{{ $t('account.maintainer') }}</span>
            <Icon name="chevD" small />
          </button>
          <div v-if="menuOpen" class="um-pop" role="menu">
            <div class="um-h">
              <b>{{ auth.me.username }}</b>
              <span v-if="auth.me.via === 'token'">{{ $t('account.viaToken') }}</span>
              <span v-else-if="auth.me.via === 'pat'">{{ $t(auth.me.read_only ? 'account.viaPatRo' : 'account.viaPat', { p: auth.me.token_prefix ?? '' }) }}</span>
              <span v-else>{{ $t(auth.isAdmin ? 'account.sessionAdmin' : roleTag === 'maintainer' ? 'account.sessionMaintainer' : 'account.sessionUser', { t: shortTime(auth.me.expires_at) }) }}</span>
            </div>
            <router-link v-if="auth.me.via === 'session'" role="menuitem" :to="{ name: 'password' }" data-testid="menu-password"><Icon name="key" small />{{ $t('account.changePassword') }}</router-link>
            <router-link v-if="auth.me.via !== 'token'" role="menuitem" :to="{ name: 'tokens' }" data-testid="menu-tokens"><Icon name="key" small />{{ $t('nav.tokens') }}</router-link>
            <router-link role="menuitem" :to="{ name: 'projects' }" data-testid="menu-projects"><Icon name="folders" small />{{ $t('nav.projects') }}</router-link>
            <router-link v-if="auth.isAdmin" role="menuitem" :to="{ name: 'users' }" data-testid="menu-users"><Icon name="users" small />{{ $t('nav.users') }}</router-link>
            <button type="button" role="menuitem" data-testid="menu-logout" @click="signOut"><Icon name="logout" small />{{ $t('account.signOut') }}</button>
          </div>
        </div>
      </div>
    </header>
    <nav class="nav" aria-label="Main">
      <template v-for="(g, gi) in nav" :key="g.g">
      <div v-if="g.proj && !nav.slice(0, gi).some((x) => x.proj)" :class="['nav-proj-band', { 'is-foreign': project.foreign }]" data-testid="nav-project-band">
        <div class="npb-k"><Icon name="folder" small /><span>{{ $t('proj.current') }}</span></div>
        <div class="npb-n" :title="project.info?.name">{{ project.info?.name ?? $t('proj.none') }}</div>
        <div class="npb-m">
          <ProjRole :role="project.role" />
          <router-link v-if="project.slug" :to="{ name: 'project-settings', params: { project: project.slug } }" class="npb-set" :title="$t('proj.settingsTip')" data-testid="band-settings"><Icon name="gear" small /></router-link>
        </div>
        <div class="npb-h">{{ $t('proj.bandHint') }}</div>
      </div>
      <div :class="['nav-group', { 'is-proj': g.proj }]">
        <div class="nav-gh"><i :class="['stratum', `s-${g.s}`]" /><span>{{ $t(`grp.${g.g}`) }}</span></div>
        <router-link
          v-for="it in g.items"
          :key="it.name"
          :to="navTo(it.name, g.proj)"
          :data-stratum="g.s"
          :title="$t(`nav.${it.name}`)"
          :aria-current="current === it.name ? 'page' : undefined"
          :data-testid="`nav-${it.name}`"
        >
          <Icon :name="it.icon" />
          <span class="lbl">{{ $t(`nav.${it.name}`) }}</span>
          <span v-if="it.count && it.count()" :class="['count', it.tone]">{{ it.count() }}</span>
        </router-link>
      </div>
      </template>
      <div class="nav-foot">
        <div :class="status.summary?.ai.configured ? 'ai-on' : 'ai-off'"><i /><span>{{ status.summary?.ai.configured ? $t('foot.aiOn') : $t('foot.ai') }}</span></div>
        <div v-if="status.appVersion">{{ $t('foot.version', { v: status.appVersion }) }}</div>
      </div>
    </nav>
    <div v-if="scopeBar === 'foreign'" class="scope-bar foreign" data-testid="scope-foreign">
      <Icon name="shield" />
      <div class="grow"><b>{{ $t('proj.foreignBar', { u: project.info?.owner ?? '—', p: project.info?.name ?? '' }) }}</b> · {{ $t('proj.foreignNote') }}</div>
      <router-link v-if="auth.isAdmin" class="btn btn-sm" :to="{ name: 'all-projects' }">{{ $t('proj.allProjects') }}</router-link>
      <button type="button" class="btn btn-sm" data-testid="scope-leave" @click="leave"><Icon name="logout" small />{{ $t('proj.leave') }}</button>
    </div>
    <div v-else-if="scopeBar === 'ro'" class="scope-bar ro" data-testid="scope-readonly">
      <Icon name="eye" />
      <div class="grow"><b>{{ $t('proj.roBar') }}</b> · {{ $t('proj.roNote', { u: project.info?.owner ?? '—' }) }}</div>
    </div>
    <div v-else-if="scopeBar === 'token'" class="scope-bar ro" data-testid="scope-token">
      <Icon name="key" />
      <div class="grow"><b>{{ $t('proj.roToken') }}</b> · {{ $t('proj.roTokenNote') }}</div>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.usermenu { position: relative; }
.um-btn { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 8px 0 4px; border: 1px solid var(--line); border-radius: var(--r-ctl); cursor: pointer; background: var(--surface); color: var(--ink); font: inherit; font-size: 12.5px; }
.um-btn:hover { border-color: var(--line-strong); }
.um-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
.av { width: 22px; height: 22px; border-radius: 50%; background: var(--teal-soft); color: var(--teal-ink); border: 1px solid var(--teal-line); display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 11.5px; }
.un { max-width: 12ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.um-btn .tag { height: 18px; font-size: 11px; }
.um-pop { position: absolute; right: 0; top: calc(100% + 6px); min-width: 240px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow-pop); padding: 6px; z-index: 60; display: flex; flex-direction: column; }
.um-h { display: flex; flex-direction: column; gap: 2px; padding: 6px 8px 8px; border-bottom: 1px solid var(--line); margin-bottom: 4px; }
.um-h span { font-size: 11.5px; color: var(--ink-3); }
.um-pop a, .um-pop button { display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: 5px; color: var(--ink); text-decoration: none; font: inherit; font-size: 13px; background: none; border: 0; cursor: pointer; text-align: left; width: 100%; }
.um-pop a:hover, .um-pop button:hover, .um-pop a:focus-visible, .um-pop button:focus-visible { background: var(--surface-2); outline: none; }
@media (max-width: 760px) { .un, .um-btn .tag { display: none; } }
</style>
