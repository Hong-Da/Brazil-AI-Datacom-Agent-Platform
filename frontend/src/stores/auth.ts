import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { post } from '@/api'

/** 当前登录的账号（REQ-030）。会话放在 HttpOnly Cookie 里，前端只知道账号名与角色。
 *  M6：角色多了知识库维护员（maintainer）；个人令牌（via = pat）可以是只读的。 */
export type Role = 'admin' | 'maintainer' | 'user'
export interface Me {
  username: string
  role: Role
  via: 'session' | 'token' | 'pat'
  expires_at: string | null
  read_only?: boolean
  token_prefix?: string | null
}

export const normRole = (r: string | null | undefined): Role => (r === 'admin' || r === 'maintainer' ? r : 'user')

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
  /** 知识库与共享内容（规则、模板）可以修改：管理员与维护员（REQ-036） */
  const isKbEditor = computed(() => (me.value?.role === 'admin' || me.value?.role === 'maintainer') && !me.value?.read_only)

  async function load(force = false): Promise<Me | null> {
    if (loaded.value && !force) return me.value
    me.value = await fetchMe()
    loaded.value = true
    return me.value
  }

  function set(user: { username: string; role: string } | null, expires: string | null = null): void {
    me.value = user ? { username: user.username, role: normRole(user.role), via: 'session', expires_at: expires } : null
    loaded.value = true
  }

  async function logout(): Promise<void> {
    try { await post('/auth/logout') } catch { /* 会话已失效时也算登出 */ }
    set(null)
  }

  return { me, loaded, isAdmin, isKbEditor, load, set, logout }
})
