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
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const t = token()
  if (t) headers.set('Authorization', `Bearer ${t}`)
  const res = await fetch(`/api/v1${path}`, { ...init, headers })
  let body: ApiBody<T>
  try { body = await res.json() } catch { throw new ApiError(1000, res.statusText, res.status, null) }
  if (body.code !== 0) throw new ApiError(body.code, body.message, res.status, body.data)
  return body.data
}
