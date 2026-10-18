import { createRouter, createWebHistory } from 'vue-router'
import { api } from '@/api'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/setup', name: 'setup', component: () => import('@/views/WizardView.vue'), meta: { bare: true } },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { bare: true } },
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/devices', name: 'devices', component: () => import('@/views/DevicesView.vue') },
    { path: '/graph/:id?', name: 'device-graph', component: () => import('@/views/DeviceGraphView.vue') },
    { path: '/unknown-lines', name: 'unknown-lines', component: () => import('@/views/UnknownLinesView.vue') },
    { path: '/compare', name: 'compare', component: () => import('@/views/CompareView.vue') },
    { path: '/check', name: 'check', component: () => import('@/views/CheckView.vue') },
    { path: '/cleanup', name: 'cleanup', component: () => import('@/views/CleanupView.vue') },
    { path: '/translate', name: 'translate', component: () => import('@/views/TranslateView.vue') },
    { path: '/templates', name: 'templates', component: () => import('@/views/TemplatesView.vue') },
    { path: '/generate', name: 'generate', component: () => import('@/views/GenerateView.vue') },
    { path: '/schema', name: 'schema-view', component: () => import('@/views/SchemaViewView.vue') },
    { path: '/schema/edit', name: 'schema-edit', component: () => import('@/views/SchemaEditView.vue') },
    { path: '/profiles', name: 'profiles', component: () => import('@/views/ProfilesView.vue') },
    { path: '/coverage', name: 'coverage', component: () => import('@/views/CoverageView.vue') },
    { path: '/review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    { path: '/ingest', name: 'ingest', component: () => import('@/views/IngestView.vue') },
    { path: '/releases', name: 'releases', component: () => import('@/views/ReleasesView.vue') },
    { path: '/ai', name: 'ai-settings', component: () => import('@/views/AiSettingsView.vue') },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

let configured: boolean | null = null

function hasToken(): boolean {
  try {
    return !!localStorage.getItem('lmesh-token')
  } catch {
    return false
  }
}

/** 未配置时进入向导；已配置但没有令牌时进入令牌页。 */
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
  if (configured && !hasToken() && to.name !== 'login') return { name: 'login', query: { next: to.fullPath } }
  return true
})

export function markConfigured(): void {
  configured = true
}
