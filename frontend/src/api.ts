import { i18n } from '@/i18n'
import { scopedPath } from '@/project/scope'

export interface ApiBody<T> { code: number; message: string; data: T }

export class ApiError extends Error {
  constructor(public code: number, message: string, public status: number, public data: unknown) { super(message) }
}

// 以前的版本把 API 令牌存在浏览器里；网页改用账号登录（会话 Cookie）后清掉它
try { localStorage.removeItem('lmesh-token') } catch { /* 忽略 */ }

/** 登录已失效：回到登录页，登录后回到当前页面。登录页和向导自己处理 401。 */
export function toLogin(expired: boolean): void {
  if (location.pathname === '/login' || location.pathname === '/setup') return
  const q = new URLSearchParams({ next: location.pathname + location.search })
  if (expired) q.set('expired', '1')
  location.assign(`/login?${q}`)
}

// M6：当前项目（由 stores/project 设置）。设备相关接口自动改走 /projects/{项目}/…
let currentProject: string | null = null
export function setApiProject(slug: string | null): void { currentProject = slug }
export function apiProject(): string | null { return currentProject }

/** 完整的接口地址：设备相关接口按当前项目改写（project 为 false 时不改写，例如管理员的“全部设备重新解析”）。 */
export function apiUrl(path: string, project: string | false | null = currentProject): string {
  return `/api/v1${project === false ? path : scopedPath(path, project)}`
}

/** 统一请求：带上语言（认证靠同源的会话 Cookie），按 {code, message, data} 解析；code 非 0 时抛出 ApiError。 */
export async function api<T>(path: string, init: RequestInit & { project?: string | false } = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept-Language', String(i18n.global.locale.value))
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const { project, ...rest } = init
  const res = await fetch(apiUrl(path, project === undefined ? currentProject : project), { credentials: 'same-origin', ...rest, headers })
  let body: ApiBody<T>
  try { body = await res.json() } catch { throw new ApiError(1000, res.statusText, res.status, null) }
  if (body.code !== 0) {
    if (body.code === 1002 && res.status === 401 && !path.startsWith('/auth/')) toLogin(true)
    throw new ApiError(body.code, body.message, res.status, body.data)
  }
  return body.data
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown, opts: { project?: string | false } = {}) =>
  api<T>(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}), ...opts })
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })

export interface Task<R = unknown> {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  message: string
  result: R | null
  created_at: string | null
  updated_at: string | null
}

/** 轮询后台任务直到结束；onTick 每次拿到最新状态。 */
export async function waitTask<R>(id: string, onTick?: (t: Task<R>) => void, intervalMs = 800): Promise<Task<R>> {
  for (;;) {
    const t = await get<Task<R>>(`/tasks/${id}`)
    onTick?.(t)
    if (t.status === 'done' || t.status === 'failed') return t
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** 下载需要登录的文件（例如知识库包）。 */
export async function download(path: string, filename: string): Promise<void> {
  const res = await fetch(apiUrl(path), { credentials: 'same-origin' })
  if (!res.ok) throw new ApiError(1000, res.statusText, res.status, null)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
