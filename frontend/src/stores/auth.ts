import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { post } from '@/api'

/** 当前登录的账号（REQ-030）。会话放在 HttpOnly Cookie 里，前端只知道账号名与角色。 */
export interface Me {
  username: string
  role: 'admin' | 'user'
  via: 'session' | 'token'
  expires_at: string | null
}

/** 读当前账号：没登录时返回 null（不跳转，路由守卫自己决定去登录页）。 */
export async function fetchMe(): Promise<Me | null> {
  try {
    const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
    if (!res.ok) return null
    const body = (await res.json()) as { code: number; data: Me }
    return body.code === 0 ? body.data : null
  } catch {
    return null
  }
}

export const useAuth = defineStore('auth', () => {
  const me = ref<Me | null>(null)
  const loaded = ref(false)
  const isAdmin = computed(() => me.value?.role === 'admin')

  async function load(force = false): Promise<Me | null> {
    if (loaded.value && !force) return me.value
    me.value = await fetchMe()
    loaded.value = true
    return me.value
  }

  function set(user: { username: string; role: string } | null, expires: string | null = null): void {
    me.value = user ? { username: user.username, role: user.role === 'admin' ? 'admin' : 'user', via: 'session', expires_at: expires } : null
    loaded.value = true
  }

  async function logout(): Promise<void> {
    try { await post('/auth/logout') } catch { /* 会话已失效时也算登出 */ }
    set(null)
  }

  return { me, loaded, isAdmin, load, set, logout }
})
