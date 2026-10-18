/** 账号相关的纯逻辑（REQ-030）：密码规则、登录后跳转地址、账号状态与可做的操作。 */

export const MIN_PASSWORD = 8

export interface UserRow {
  id: number
  username: string
  role: 'admin' | 'user'
  disabled: boolean
  locked: boolean
  locked_until: string | null
  last_login_at: string | null
  password_changed_at: string | null
  created_at: string | null
}

export type Problem = 'short' | 'mismatch' | 'same'

/** 新密码的问题（与后端一致：至少 8 个字符）；repeat 为 undefined 时不检查两次是否一致。 */
export function passwordProblems(pw: string, repeat?: string, old?: string): Problem[] {
  const out: Problem[] = []
  if (pw.length < MIN_PASSWORD) out.push('short')
  if (old !== undefined && old !== '' && pw === old) out.push('same')
  if (repeat !== undefined && repeat !== pw) out.push('mismatch')
  return out
}

/** 用户名规则（与后端一致）。 */
export function validName(name: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$/.test(name.trim())
}

/** 登录后回到哪里：只接受站内路径，防止 next=//evil.example 之类的跳转。 */
export function safeNext(next: unknown): string {
  const s = Array.isArray(next) ? String(next[0] ?? '') : String(next ?? '')
  if (!s.startsWith('/') || s.startsWith('//') || s.startsWith('/\\') || s.startsWith('/login')) return '/'
  return s
}

export type UserState = 'enabled' | 'locked' | 'disabled'

export function stateOf(u: UserRow): UserState {
  if (u.disabled) return 'disabled'
  if (u.locked) return 'locked'
  return 'enabled'
}

/** 启用中的管理员个数。 */
export function enabledAdmins(rows: UserRow[]): number {
  return rows.filter((u) => u.role === 'admin' && !u.disabled).length
}

/** 最后一个启用的管理员：不能停用、删除、改为普通用户。 */
export function isLastAdmin(u: UserRow, rows: UserRow[]): boolean {
  return u.role === 'admin' && !u.disabled && enabledAdmins(rows) <= 1
}

/** 时间显示到分钟（本地时区）。 */
export function shortTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function counts(rows: UserRow[]): { all: number; admin: number; locked: number; disabled: number } {
  return {
    all: rows.length,
    admin: rows.filter((u) => u.role === 'admin').length,
    locked: rows.filter((u) => stateOf(u) === 'locked').length,
    disabled: rows.filter((u) => u.disabled).length,
  }
}
