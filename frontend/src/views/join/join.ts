/**
 * 创建项目的权限与加入项目（M9-8，REQ-050，预览 DevelopDocs/ui-preview/M9-8/）：接口类型、请求与纯函数。
 */
import { del, get, post } from '@/api'

export type JoinStatus = 'pending' | 'approved' | 'declined' | 'cancelled'
export type MemberRole = 'manage' | 'edit' | 'read'

export interface DiscoverRow {
  id: number
  ref: string
  name: string
  description: string
  owner: string | null
  devices: number
  my_status: 'owner' | 'member' | 'pending' | 'declined' | 'none'
  my_role: string | null
  request_id: number | null
}

export interface JoinRequest {
  id: number
  project: { id: number; ref: string; name: string; owner: string | null }
  username: string
  role: MemberRole
  reason: string
  via: 'search' | 'invite'
  invite_prefix: string | null
  status: JoinStatus
  decided_by: string | null
  decided_role: MemberRole | null
  note: string
  created_at: string | null
  decided_at: string | null
}

export interface Invite {
  id: number
  prefix: string
  role: MemberRole
  requires_approval: boolean
  note: string
  created_by: string
  uses: number
  expires_at: string | null
  revoked_at: string | null
  created_at: string | null
  state: 'active' | 'expired' | 'revoked'
  token?: string
  path?: string
}

export interface CreateRequest {
  id: number
  username: string
  reason: string
  status: JoinStatus
  decided_by: string | null
  note: string
  created_at: string | null
  decided_at: string | null
}

export interface CreatePermission {
  can_create: boolean
  open: boolean
  admin: boolean
  granted: boolean
  request: CreateRequest | null
}

export interface InviteInfo {
  project: { id: number; ref: string; name: string; description: string; owner: string | null; devices: number }
  my_status: DiscoverRow['my_status']
  my_role: string | null
  role: MemberRole
  requires_approval: boolean
  expires_at: string | null
  state: Invite['state']
  invited_by: string
}

export interface Notifications {
  join_requests: number
  by_project: { id: number; ref: string; name: string; count: number }[]
  create_requests: number
  total: number
}

const enc = encodeURIComponent
/** 项目路径段：“属主/标识”写成“属主~标识”（后端两种都认，~ 不用转义）。 */
export const refSeg = (ref: string): string => enc(ref.replace('/', '~'))

export const discover = (q = '') => get<{ projects: DiscoverRow[]; count: number }>(`/discover${q ? `?q=${enc(q)}` : ''}`)
export const requestJoin = (id: number, role: 'read' | 'edit', reason: string) => post<JoinRequest>(`/discover/${id}/join-requests`, { role, reason })
export const myRequests = () => get<{ requests: JoinRequest[] }>('/me/join-requests')
export const cancelRequest = (id: number) => del<JoinRequest>(`/me/join-requests/${id}`)
export const createPermission = () => get<CreatePermission>('/me/create-permission')
export const requestCreate = (reason: string) => post<CreateRequest>('/me/create-permission/request', { reason })
export const cancelCreate = () => del<CreateRequest>('/me/create-permission/request')
export const notifications = () => get<Notifications>('/me/notifications')
export const inviteInfo = (token: string) => get<InviteInfo>(`/invites/${enc(token)}`)
export const acceptInvite = (token: string, reason = '') =>
  post<{ status: 'joined' | 'pending' | 'member'; project: string; role: string; request_id?: number }>(`/invites/${enc(token)}/accept`, { reason })

export const listRequests = (ref: string, status: JoinStatus | 'all' = 'pending') =>
  get<{ requests: JoinRequest[] }>(`/projects/${refSeg(ref)}/join-requests?status=${status}`)
export const approveRequest = (ref: string, id: number, role: MemberRole) => post<JoinRequest>(`/projects/${refSeg(ref)}/join-requests/${id}/approve`, { role })
export const declineRequest = (ref: string, id: number, note = '') => post<JoinRequest>(`/projects/${refSeg(ref)}/join-requests/${id}/decline`, { note })
export const listInvites = (ref: string) => get<{ invites: Invite[] }>(`/projects/${refSeg(ref)}/invites`)
export const createInvite = (ref: string, body: { role: MemberRole; days: number; requires_approval: boolean; note: string }) =>
  post<Invite>(`/projects/${refSeg(ref)}/invites`, body)
export const revokeInvite = (ref: string, id: number) => del<Invite>(`/projects/${refSeg(ref)}/invites/${id}`)

export const listCreateRequests = () => get<{ requests: CreateRequest[]; count: number }>('/admin/create-requests')
export const approveCreate = (id: number) => post<CreateRequest>(`/admin/create-requests/${id}/approve`, {})
export const declineCreate = (id: number, note = '') => post<CreateRequest>(`/admin/create-requests/${id}/decline`, { note })

/** 邀请链接的完整地址（令牌只在新建时拿到一次）。 */
export function inviteUrl(path: string, origin: string = location.origin): string {
  return origin.replace(/\/$/, '') + path
}

/** 邀请链接的有效天数选项。 */
export const EXPIRY_DAYS = [1, 7, 30] as const

/** 状态标签的样式与图标。 */
export function statusIcon(s: JoinStatus | Invite['state']): string {
  return { pending: 'clock', approved: 'check', declined: 'x', cancelled: 'rollback', active: 'check', expired: 'clock', revoked: 'x' }[s]
}

/** 文字里匹配搜索词的部分（高亮用）：返回 [前, 匹配, 后]；没有匹配时匹配为空。 */
export function splitMatch(text: string, q: string): [string, string, string] {
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1
  if (i < 0) return [text, '', '']
  return [text.slice(0, i), text.slice(i, i + q.length), text.slice(i + q.length)]
}

/** 从输入里取出邀请令牌：可以是令牌本身，也可以是包含 /invite/<令牌> 的链接。 */
export function tokenFrom(input: string): string {
  const t = input.trim()
  const m = t.match(/\/invite\/([^/?#\s]+)/)
  return m ? decodeURIComponent(m[1]) : t
}
