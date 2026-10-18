import { i18n } from '@/i18n'

export interface ApiBody<T> { code: number; message: string; data: T }

export class ApiError extends Error {
  constructor(public code: number, message: string, public status: number, public data: unknown) { super(message) }
}

function token(): string {
  try { return localStorage.getItem('lmesh-token') ?? '' } catch { return '' }
}

/** 统一请求：带上语言与令牌，按 {code, message, data} 解析；code 非 0 时抛出 ApiError。 */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept-Language', String(i18n.global.locale.value))
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const t = token()
  if (t) headers.set('Authorization', `Bearer ${t}`)
  const res = await fetch(`/api/v1${path}`, { ...init, headers })
  let body: ApiBody<T>
  try { body = await res.json() } catch { throw new ApiError(1000, res.statusText, res.status, null) }
  if (body.code !== 0) {
    if (body.code === 1002 && location.pathname !== '/login') {
      location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
    }
    throw new ApiError(body.code, body.message, res.status, body.data)
  }
  return body.data
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) })
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

/** 下载需要令牌的文件（例如知识库包）。 */
export async function download(path: string, filename: string): Promise<void> {
  const res = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${token()}` } })
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
