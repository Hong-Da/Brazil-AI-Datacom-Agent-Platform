import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ApiError, get, setApiProject } from '@/api'
import { RECENT_KEY } from '@/project/scope'
import { useAuth } from '@/stores/auth'

/** 项目在列表里的一行（GET /projects、/admin/projects）。 */
export interface ProjectRow {
  id: number
  slug: string
  name: string
  description: string
  owner: string | null
  owner_disabled?: boolean
  role: 'owner' | 'edit' | 'read' | 'admin' | null
  members: number
  member_names?: string[]
  settings: { style?: string; rule_set?: string; baseline?: string }
  migrated_from?: { type: string; [k: string]: unknown } | null
  last_activity: { at: string; actor?: string | null; action: string } | null
  counts: { devices: number; private: number; refs: number; scripts: number; scripts_with_errors: number; check_projects: number }
  created_at: string | null
  updated_at: string | null
  default?: boolean
}
export interface Member { username: string; role: 'owner' | 'edit' | 'read'; disabled?: boolean; since: string | null }
export interface ProjectDetail extends ProjectRow {
  member_list: Member[]
  overrides: { rule: string; enabled: boolean; severity: string | null; reason: string; updated_by?: string | null; updated_at?: string | null }[]
}
export interface ProjectLists { mine: ProjectRow[]; shared: ProjectRow[]; others: ProjectRow[]; default_project: string | null }

// 最近用过的项目按账号分开记（同一个浏览器可能换账号登录）
const recentKey = (): string => `${RECENT_KEY}:${useAuth().me?.username ?? ''}`
function readRecent(): string | null {
  try { return localStorage.getItem(recentKey()) } catch { return null }
}
function writeRecent(slug: string): void {
  try { localStorage.setItem(recentKey(), slug) } catch { /* 忽略 */ }
}

/**
 * 当前项目（REQ-035）：网址 /p/<项目>/… 优先，其次最近用过的项目，最后是工作空间的默认项目。
 * 设置后 api.ts 把设备相关接口改走 /projects/<项目>/…。
 */
export const useProject = defineStore('project', () => {
  const slug = ref<string | null>(null)
  const info = ref<ProjectDetail | null>(null)
  const lists = ref<ProjectLists | null>(null)
  const defaultSlug = ref<string | null>(null)
  /** 刚才请求的项目不存在或无权访问（显示在“我的项目”页） */
  const missing = ref<string | null>(null)

  const role = computed(() => info.value?.role ?? null)
  /** 能修改本项目的数据：属主、可编辑成员、管理员；只读的个人令牌不行 */
  const canWrite = computed(() => ['owner', 'edit', 'admin'].includes(role.value ?? '') && !useAuth().me?.read_only)
  /** 能管理成员、转交、删除：属主与管理员 */
  const canManage = computed(() => (role.value === 'owner' || role.value === 'admin') && !useAuth().me?.read_only)
  /** 管理员正在访问不是自己参与的项目 */
  const foreign = computed(() => role.value === 'admin')
  const readOnly = computed(() => !!info.value && !canWrite.value)

  async function loadLists(): Promise<ProjectLists> {
    const auth = useAuth()
    const data = await get<ProjectLists>(`/projects${auth.isAdmin ? '?all=true' : ''}`)
    lists.value = { mine: data.mine ?? [], shared: data.shared ?? [], others: data.others ?? [], default_project: data.default_project }
    return lists.value
  }

  async function loadDefault(): Promise<string | null> {
    try {
      const ws = await get<{ default_project: string | null }>('/workspace')
      defaultSlug.value = ws.default_project
    } catch { /* 取不到时没有默认项目 */ }
    return defaultSlug.value
  }

  /** 没有网址里的项目时用哪个：最近用过的（仍可访问）→ 默认项目。 */
  async function ensure(): Promise<string | null> {
    if (slug.value) return slug.value
    const recent = readRecent()
    if (recent) {
      try {
        await enter(recent)
        return slug.value
      } catch { /* 最近的项目已删除或不再共享：用默认项目 */ }
    }
    const d = defaultSlug.value ?? (await loadDefault())
    if (d) {
      try { await enter(d) } catch { return null }
    }
    return slug.value
  }

  /** 进入项目：读详情（我的角色、成员、设置）；不存在或无权访问时抛出 ApiError（404）。 */
  async function enter(s: string): Promise<ProjectDetail> {
    if (slug.value === s && info.value) return info.value
    const detail = await get<ProjectDetail>(`/projects/${encodeURIComponent(s)}`)
    slug.value = detail.slug
    info.value = detail
    setApiProject(detail.slug)
    writeRecent(detail.slug)
    missing.value = null
    return detail
  }

  /** 修改设置、成员后重新读当前项目。 */
  async function reload(): Promise<void> {
    if (!slug.value) return
    try {
      info.value = await get<ProjectDetail>(`/projects/${encodeURIComponent(slug.value)}`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) forget()
      else throw e
    }
  }

  /** 当前项目被删除、转走或退出后：清掉，下次用默认项目。 */
  function forget(): void {
    slug.value = null
    info.value = null
    setApiProject(null)
    try { localStorage.removeItem(recentKey()) } catch { /* 忽略 */ }
  }

  function reset(): void {
    forget()
    lists.value = null
    defaultSlug.value = null
  }

  return { slug, info, lists, defaultSlug, missing, role, canWrite, canManage, foreign, readOnly, loadLists, loadDefault, ensure, enter, reload, forget, reset }
})
