import { createRouter, createWebHistory, type RouteComponent, type RouteRecordRaw, type RouteLocationRaw, type RouteLocationNormalized } from 'vue-router'
import { defineComponent } from 'vue'
import { api, ApiError } from '@/api'
import { useAuth } from '@/stores/auth'
import { useProject } from '@/stores/project'
import { basePage, legacyTarget, netName, pageNet, PROJECT_PAGES, refFromParam, refParam, withNetwork, withProject } from '@/project/scope'
import { useNetwork } from '@/stores/network'
import { shouldShowUpgrade, upgradeSeen } from '@/project/upgrade'

/** 项目页面（/p/<项目>/…，REQ-035）的组件；consistency 是拓扑页的另一个视图。 */
const PROJECT_VIEWS: Record<string, () => Promise<RouteComponent | { default: RouteComponent }>> = {
  devices: () => import('@/views/DevicesView.vue'),
  'add-device': () => import('@/views/AddDeviceView.vue'),
  'device-graph': () => import('@/views/DeviceGraphView.vue'),
  'device-analysis': () => import('@/views/DeviceAnalysisView.vue'),
  history: () => import('@/views/HistoryView.vue'),
  'unknown-lines': () => import('@/views/UnknownLinesView.vue'),
  'model-rules': () => import('@/views/ModelRulesView.vue'),
  compare: () => import('@/views/CompareView.vue'),
  check: () => import('@/views/CheckView.vue'),
  cleanup: () => import('@/views/CleanupView.vue'),
  translate: () => import('@/views/TranslateView.vue'),
  change: () => import('@/views/ChangeView.vue'),
  scripts: () => import('@/views/ScriptsView.vue'),
  'check-project': () => import('@/views/CheckProjectView.vue'),
  migration: () => import('@/views/MigrationView.vue'),
  impact: () => import('@/views/ImpactView.vue'),
  topology: () => import('@/views/TopologyView.vue'),
  consistency: () => import('@/views/TopologyView.vue'),
  baseline: () => import('@/views/BaselineView.vue'),
  export: () => import('@/views/ExportView.vue'),
  'project-settings': () => import('@/views/ProjectSettingsView.vue'),
  networks: () => import('@/views/NetworksView.vue'),
  'network-suggest': () => import('@/views/NetworkSuggestView.vue'),
  members: () => import('@/views/NetworkMembersView.vue'),
  'network-home': () => import('@/views/NetworkHomeView.vue'),
}
/** 按网络的页面在项目层（“全部设备”）显示各网络汇总（M9 评审：allpages = summary）。 */
const NetSummary = () => import('@/views/NetSummaryView.vue')

/** 旧网址只用来跳到当前项目的对应页面（守卫里处理），不渲染内容。 */
const Legacy = defineComponent({ render: () => null })

// M9：按网络的页面另有网络层路由 n-<页面>（/p/<项目>/n/<网络>/…）；项目层网址是“全部设备”（net 页面显示各网络汇总）
const projectRoutes: RouteRecordRaw[] = PROJECT_PAGES.flatMap((p) => {
  const meta = { project: true, page: p.name, ...(p.name === 'consistency' ? { view: 'consistency' } : {}) }
  const out: RouteRecordRaw[] = []
  if (p.net !== 'only') {
    out.push({
      path: `/p/:project+/${p.path}`, // /p/<标识>/… 或 /p/<属主>/<标识>/…（标识按属主唯一）
      name: p.name,
      component: p.net === 'net' ? NetSummary : PROJECT_VIEWS[p.name],
      meta,
    })
  }
  if (p.net) {
    out.push({
      // :network 写成自定义正则：排序时与项目层的 :id(\d+)? 同级加分，否则 /p/a/n/b/analysis/1 会被项目层路由当成项目 a/n/b
      path: `/p/:project+/n/:network([^/]+)${p.path ? `/${p.path}` : ''}`,
      name: netName(p.name),
      component: PROJECT_VIEWS[p.name],
      meta: { ...meta, network: true },
    })
  }
  return out
})
const legacyRoutes: RouteRecordRaw[] = PROJECT_PAGES.filter((p) => p.legacy).map((p) => ({
  path: p.legacy as string,
  name: `legacy-${p.name}`,
  component: Legacy,
  meta: { legacy: true },
}))

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/setup', name: 'setup', component: () => import('@/views/WizardView.vue'), meta: { bare: true } },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { bare: true } },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue'), meta: { bare: true } },
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/ask', name: 'ask', component: () => import('@/views/AskView.vue') },
    ...projectRoutes,
    ...legacyRoutes,
    { path: '/projects', name: 'projects', component: () => import('@/views/ProjectsView.vue') },
    { path: '/tokens', name: 'tokens', component: () => import('@/views/TokensView.vue') },
    { path: '/me/ai', name: 'my-ai', component: () => import('@/views/MyAiView.vue') },
    { path: '/me/ai/personal', name: 'my-ai-personal', component: () => import('@/views/MyAiPersonalView.vue') },
    { path: '/upgrade', name: 'upgrade', component: () => import('@/views/UpgradeView.vue') },
    { path: '/public-devices', name: 'public-devices', component: () => import('@/views/PublicDevicesView.vue'), meta: { admin: true } },
    { path: '/admin/projects', name: 'all-projects', component: () => import('@/views/AllProjectsView.vue'), meta: { admin: true } },
    { path: '/templates', name: 'templates', component: () => import('@/views/TemplatesView.vue') },
    { path: '/generate', name: 'generate', component: () => import('@/views/GenerateView.vue') },
    { path: '/translate-rules', name: 'translate-rules', component: () => import('@/views/TranslateRulesView.vue') },
    { path: '/schema', name: 'schema-view', component: () => import('@/views/SchemaViewView.vue') },
    { path: '/schema/edit', name: 'schema-edit', component: () => import('@/views/SchemaEditView.vue') },
    { path: '/profiles', name: 'profiles', component: () => import('@/views/ProfilesView.vue') },
    { path: '/features', name: 'features', component: () => import('@/views/FeaturesView.vue') },
    { path: '/coverage', name: 'coverage', component: () => import('@/views/CoverageView.vue') },
    { path: '/review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    { path: '/ingest', name: 'ingest', component: () => import('@/views/IngestView.vue') },
    { path: '/releases', name: 'releases', component: () => import('@/views/ReleasesView.vue') },
    { path: '/ai', name: 'ai-settings', component: () => import('@/views/AiSettingsView.vue'), meta: { admin: true } },
    { path: '/ai/connections/:id', name: 'ai-connection', component: () => import('@/views/AiConnectionView.vue'), meta: { admin: true } },
    { path: '/ai-skills', name: 'ai-skills', component: () => import('@/views/AiSkillsView.vue'), meta: { admin: true } },
    { path: '/ai-skills/:id', name: 'ai-skill', component: () => import('@/views/AiSkillView.vue'), meta: { admin: true } },
    { path: '/users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { admin: true } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { admin: true } },
    { path: '/password', name: 'password', component: () => import('@/views/PasswordView.vue') },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

// 从非项目页面按名称跳到项目页面（{ name: 'devices' }）时补上当前项目；在项目页面之间跳转时 vue-router 自己沿用
// 按网络的页面（M9）：补上当前网络（有当前网络时去网络层路由 n-<页面>，params.network 为 null 时去项目层）
const { resolve, push, replace } = router
const scoped = (to: RouteLocationRaw): RouteLocationRaw => withProject(withNetwork(to, useNetwork().cur), useProject().ref)
router.resolve = ((to: RouteLocationRaw, current?: Parameters<typeof resolve>[1]) => resolve(scoped(to), current)) as typeof resolve
router.push = ((to: RouteLocationRaw) => push(scoped(to))) as typeof push
router.replace = ((to: RouteLocationRaw) => replace(scoped(to))) as typeof replace

let configured: boolean | null = null
let upgradeChecked = false

/** 未配置时进入向导；已配置但没登录时进入登录页；管理员页面只对管理员开放。 */
router.beforeEach(async (to) => {
  if (configured !== true) {
    try {
      const h = await api<{ configured: boolean }>('/health')
      configured = h.configured
    } catch {
      configured = null
    }
  }
  if (configured === false && to.name !== 'setup') return { name: 'setup' }
  if (configured && to.name === 'setup') return { name: 'dashboard' }
  if (!configured || to.name === 'login' || to.name === 'register') return true
  const auth = useAuth()
  const me = await auth.load()
  if (!me) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.admin && me.role !== 'admin') return { name: 'dashboard' }
  const project = useProject()
  // 旧网址（/devices、/graph/12、/check-projects…）：跳到当前项目（没有时为默认项目）的对应页面
  if (to.meta.legacy) {
    const slug = await project.ensure()
    return slug ? legacyTarget(to.fullPath, slug) : { name: 'projects' }
  }
  if (to.meta.project) {
    const want = refFromParam(to.params.project)
    if (!want) return { name: 'projects', query: { missing: refParam(String(to.params.project ?? '')).join('/') } }
    let detail
    try {
      detail = await project.enter(want)
    } catch (e) {
      // 不存在或不是成员（后端 404 不区分）：回到“我的项目”并说明
      if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
        project.missing = want
        return { name: 'projects', query: { missing: want } }
      }
      // 只写标识而能访问的同名项目有多个：回到“我的项目”列出候选（属主/标识）
      const cands = e instanceof ApiError && e.status === 409 ? (e.data as { candidates?: string[] } | null)?.candidates : null
      if (cands?.length) {
        project.missing = want
        project.candidates = cands
        return { name: 'projects', query: { ambiguous: want } }
      }
      throw e
    }
    // 网址里的写法不是规范引用（例如别人的项目只写了标识、或写了编号）：换成规范的网址
    if (detail.ref !== want) return { name: to.name as string, params: { ...to.params, project: refParam(detail.ref) }, query: to.query, hash: to.hash, replace: true }
    return enterNetwork(to, detail.ref)
  }
  useNetwork().leave()
  // 其他页面（首页、AI 查询、模板……）的设备数据也来自当前项目
  await project.ensure()
  // 升级到 0.6.0 后第一次登录：说明现有数据移入了哪些项目（每次打开网页最多检查一次；看过的账号不再查）
  if (!upgradeChecked && to.name !== 'upgrade') {
    upgradeChecked = true
    if (!upgradeSeen(me.username)) {
      const lists = project.lists ?? (await project.loadLists().catch(() => null))
      if (shouldShowUpgrade(me.username, lists)) return { name: 'upgrade' }
    }
  }
  return true
})

/**
 * 网络（M9）：网络层网址 → 当前网络（不存在时回到网络列表并说明）；项目层的按网络页面 → “全部设备”汇总，
 * 只有默认网络时、或网址指向具体对象（设备、脚本编号，?device=）时直接进默认网络（默认网络包含全部设备）。
 */
async function enterNetwork(to: RouteLocationNormalized, ref: string): Promise<true | RouteLocationRaw> {
  const network = useNetwork()
  if (network.project !== ref) network.reset()
  const page = basePage(to.name)
  const level = pageNet(page)
  if (!level) {
    network.leave()
    return true
  }
  if (to.meta.network) {
    const want = String(to.params.network ?? '')
    let list = await network.load(ref)
    if (!list.networks.some((n) => n.slug === want)) list = await network.load(ref, true) // 刚建的或刚改名的网络
    if (!list.networks.some((n) => n.slug === want)) {
      network.enter(null)
      return { name: 'networks', params: { project: refParam(ref) }, query: { missing: want } }
    }
    network.enter(want)
    return true
  }
  network.enter(null)
  if (level !== 'net') return true
  const list = await network.load(ref)
  const def = list.networks.find((n) => n.default)
  const specific = to.params.id !== undefined && to.params.id !== '' || typeof to.query.device === 'string'
  if (def && (list.networks.length <= 1 || specific)) {
    network.enter(def.slug)
    return { name: netName(page), params: { ...to.params, network: def.slug }, query: to.query, hash: to.hash, replace: true }
  }
  return true
}

export function markConfigured(): void {
  configured = true
}
