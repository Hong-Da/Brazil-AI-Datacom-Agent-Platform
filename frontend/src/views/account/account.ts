/** 账号相关的纯逻辑（REQ-030）：密码规则、登录后跳转地址、账号状态与可做的操作。 */

export const MIN_PASSWORD = 8

export interface UserRow {
  id: number
  username: string
  role: 'admin' | 'maintainer' | 'user'
  disabled: boolean
  locked: boolean
  locked_until: string | null
  last_login_at: string | null
  password_changed_at: string | null
  created_at: string | null
  /** 拥有的非空项目数（M6） */
  projects?: number
  /** 有效的个人 API 令牌数（M6） */
  tokens?: number
  /** 单独授权创建项目（M9-8） */
  can_create_projects?: boolean
  /** active 正常 / pending 自助注册后待审核（REQ-039） */
  status?: 'active' | 'pending'
  /** admin 管理员建 / register 自助注册（REQ-039） */
  origin?: 'admin' | 'register'
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

/** 登录页状态（GET /auth/status）；config_file、token_set 只在还没有账号时返回。 */
export interface AuthStatus {
  configured: boolean
  has_users: boolean
  session_hours: number
  config_file?: string
  token_set?: boolean
  /** 自助注册（REQ-039）：open 登录页显示注册入口；approval 注册后需要管理员审核 */
  registration?: { open: boolean; approval: boolean }
}

/** 还没有账号时怎样创建第一个管理员：token = 网页上用 API 令牌创建；cli = 令牌未设置，只能用命令行或先设置令牌。 */
export function bootMode(s: AuthStatus | null): 'token' | 'cli' | null {
  if (!s || s.has_users) return null
  return s.token_set === false ? 'cli' : 'token'
}

export type UserState = 'enabled' | 'locked' | 'disabled' | 'pending'

export function stateOf(u: UserRow): UserState {
  if (u.disabled) return 'disabled'
  if (u.status === 'pending') return 'pending'
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

export function counts(rows: UserRow[]): { all: number; admin: number; maint: number; pending: number; locked: number; disabled: number } {
  return {
    all: rows.filter((u) => u.status !== 'pending').length,
    pending: rows.filter((u) => u.status === 'pending').length,
    admin: rows.filter((u) => u.role === 'admin').length,
    maint: rows.filter((u) => u.role === 'maintainer').length,
    locked: rows.filter((u) => stateOf(u) === 'locked').length,
    disabled: rows.filter((u) => u.disabled).length,
  }
}

export const ROLES = ['user', 'maintainer', 'admin'] as const
export type AccountRole = (typeof ROLES)[number]

/** 账号拥有的非空项目（GET /users/{u}/projects）。 */
export interface OwnedProject { id: number; slug: string; name: string; devices: number; scripts: number }

/** 删除账号时可以接收项目的账号：启用中、不是被删除的账号本身。 */
export function transferTargets(rows: UserRow[], deleting: string): string[] {
  return rows.filter((u) => !u.disabled && u.username !== deleting).map((u) => u.username)
}

/** 删除账号的请求路径：拥有项目时必须选择转交（transfer_to）或一并删除（delete_projects）。 */
export function deleteUserPath(username: string, owned: number, mode: 'transfer' | 'delete', to: string): string | null {
  const base = `/users/${encodeURIComponent(username)}`
  if (!owned) return base
  if (mode === 'delete') return `${base}?delete_projects=true`
  return to ? `${base}?transfer_to=${encodeURIComponent(to)}` : null
}

/**
 * 角色权限矩阵（REQ-036，依据 docs/project-spec.md“权限模型”的实现结果与 api/access.py）：
 * y 可修改 / c 可查看与计算 / r 只读 / s 只读、可提建议 / n 不可用。列：管理员、维护员、普通用户（属主 / 可编辑）、只读成员。
 */
export type Perm = 'y' | 'c' | 'r' | 's' | 'n'
export const PERM_MATRIX: { key: string; cells: [Perm, Perm, Perm, Perm] }[] = [
  { key: 'kb', cells: ['y', 'y', 's', 's'] },
  { key: 'release', cells: ['y', 'y', 'r', 'r'] },
  { key: 'shared', cells: ['y', 'y', 's', 's'] },
  { key: 'ruleAdjust', cells: ['y', 'y', 'y', 'r'] },
  { key: 'mine', cells: ['y', 'y', 'y', 'y'] },
  { key: 'projWrite', cells: ['y', 'y', 'y', 'r'] },
  { key: 'projCompute', cells: ['y', 'y', 'y', 'c'] },
  { key: 'rebuildProject', cells: ['y', 'y', 'y', 'n'] },
  { key: 'rebuildAll', cells: ['y', 'n', 'n', 'n'] },
  { key: 'public', cells: ['y', 'r', 'r', 'r'] },
  { key: 'system', cells: ['y', 'n', 'n', 'n'] },
]

/** 注册表单的检查项（REQ-039，与后端规则一致）：用户名长度、用户名字符、密码长度、两次一致；值为 null 表示还没填。 */
export function signUpChecks(name: string, pw: string, pw2: string): { nameLen: boolean | null; nameChars: boolean | null; pwLen: boolean | null; same: boolean | null } {
  const n = name.trim()
  return {
    nameLen: n ? n.length >= 2 && n.length <= 64 : null,
    nameChars: n ? /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(n) : null,
    pwLen: pw ? pw.length >= MIN_PASSWORD : null,
    same: pw2 ? pw === pw2 : null,
  }
}

/** 自助注册设置（GET / PUT /auth/settings）。 */
export interface RegSettings { registration: boolean; approval: boolean; rate_per_hour: number }

/** 每小时次数是否合格（1–1000 的整数）。 */
export function validRate(v: unknown): boolean {
  const n = Number(v)
  return Number.isInteger(n) && n >= 1 && n <= 1000
}

/** 设置面板里改了哪些项（PUT 的请求体）；没有改动时为空对象。 */
export function regPatch(saved: RegSettings, draft: RegSettings): Partial<RegSettings> {
  const out: Partial<RegSettings> = {}
  if (draft.registration !== saved.registration) out.registration = draft.registration
  if (draft.approval !== saved.approval) out.approval = draft.approval
  if (Number(draft.rate_per_hour) !== saved.rate_per_hour) out.rate_per_hour = Number(draft.rate_per_hour)
  return out
}
