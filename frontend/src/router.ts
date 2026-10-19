import { createRouter, createWebHistory } from 'vue-router'
import { api } from '@/api'
import { useAuth } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/setup', name: 'setup', component: () => import('@/views/WizardView.vue'), meta: { bare: true } },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { bare: true } },
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/ask', name: 'ask', component: () => import('@/views/AskView.vue') },
    { path: '/devices', name: 'devices', component: () => import('@/views/DevicesView.vue') },
    { path: '/graph/:id?', name: 'device-graph', component: () => import('@/views/DeviceGraphView.vue') },
    { path: '/analysis/:id?', name: 'device-analysis', component: () => import('@/views/DeviceAnalysisView.vue') },
    { path: '/history/:id?', name: 'history', component: () => import('@/views/HistoryView.vue') },
    { path: '/unknown-lines', name: 'unknown-lines', component: () => import('@/views/UnknownLinesView.vue') },
    { path: '/compare', name: 'compare', component: () => import('@/views/CompareView.vue') },
    { path: '/check', name: 'check', component: () => import('@/views/CheckView.vue') },
    { path: '/cleanup', name: 'cleanup', component: () => import('@/views/CleanupView.vue') },
    { path: '/translate', name: 'translate', component: () => import('@/views/TranslateView.vue') },
    { path: '/templates', name: 'templates', component: () => import('@/views/TemplatesView.vue') },
    { path: '/generate', name: 'generate', component: () => import('@/views/GenerateView.vue') },
    { path: '/translate-rules', name: 'translate-rules', component: () => import('@/views/TranslateRulesView.vue') },
    { path: '/change', name: 'change', component: () => import('@/views/ChangeView.vue') },
    { path: '/check-projects', name: 'check-projects', component: () => import('@/views/CheckProjectsView.vue') },
    { path: '/check-projects/:id', name: 'check-project', component: () => import('@/views/CheckProjectView.vue') },
    { path: '/migration', name: 'migration', component: () => import('@/views/MigrationView.vue') },
    { path: '/impact', name: 'impact', component: () => import('@/views/ImpactView.vue') },
    { path: '/topology', name: 'topology', component: () => import('@/views/TopologyView.vue') },
    { path: '/consistency', name: 'consistency', component: () => import('@/views/TopologyView.vue'), meta: { view: 'consistency' } },
    { path: '/baseline', name: 'baseline', component: () => import('@/views/BaselineView.vue') },
    { path: '/export', name: 'export', component: () => import('@/views/ExportView.vue') },
    { path: '/schema', name: 'schema-view', component: () => import('@/views/SchemaViewView.vue') },
    { path: '/schema/edit', name: 'schema-edit', component: () => import('@/views/SchemaEditView.vue') },
    { path: '/profiles', name: 'profiles', component: () => import('@/views/ProfilesView.vue') },
    { path: '/features', name: 'features', component: () => import('@/views/FeaturesView.vue') },
    { path: '/coverage', name: 'coverage', component: () => import('@/views/CoverageView.vue') },
    { path: '/review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    { path: '/ingest', name: 'ingest', component: () => import('@/views/IngestView.vue') },
    { path: '/releases', name: 'releases', component: () => import('@/views/ReleasesView.vue') },
    { path: '/ai', name: 'ai-settings', component: () => import('@/views/AiSettingsView.vue'), meta: { admin: true } },
    { path: '/ai-skills', name: 'ai-skills', component: () => import('@/views/AiSkillsView.vue'), meta: { admin: true } },
    { path: '/ai-skills/:id', name: 'ai-skill', component: () => import('@/views/AiSkillView.vue'), meta: { admin: true } },
    { path: '/users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { admin: true } },
    { path: '/password', name: 'password', component: () => import('@/views/PasswordView.vue') },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

let configured: boolean | null = null

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
  if (!configured || to.name === 'login') return true
  const auth = useAuth()
  const me = await auth.load()
  if (!me) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.admin && me.role !== 'admin') return { name: 'dashboard' }
  return true
})

export function markConfigured(): void {
  configured = true
}
