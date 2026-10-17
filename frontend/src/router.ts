import { createRouter, createWebHistory } from 'vue-router'
import { api } from '@/api'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/setup', name: 'setup', component: () => import('@/views/WizardView.vue'), meta: { bare: true } },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { bare: true } },
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
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
  if (configured && to.name === 'setup') return { name: 'home' }
  if (configured && !hasToken() && to.name !== 'login') return { name: 'login', query: { next: to.fullPath } }
  return true
})

export function markConfigured(): void {
  configured = true
}
