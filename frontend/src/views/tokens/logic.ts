/** 个人 API 令牌页（M6-4 / M6-5，预览 DevelopDocs/ui-preview/M6/tokens.html）的数据结构与纯逻辑。 */

export type TokenState = 'active' | 'expired' | 'revoked'

/** GET /tokens 的一行（不含令牌本身）。 */
export interface TokenRow {
  id: number
  name: string
  prefix: string
  read_only: boolean
  created_at: string | null
  expires_at: string | null
  last_used_at: string | null
  last_used_ip: string | null
  revoked_at: string | null
  state: TokenState
}

/** POST /tokens 的返回：多一个只出现这一次的 token。 */
export interface CreatedToken extends TokenRow { token: string; owner: string }

/** 有效期选项（天）；0 表示不过期。 */
export const EXPIRY_DAYS = [30, 90, 365, 0] as const
export const DEFAULT_DAYS = 90

/** 有效的在前，其余按创建时间新的在前。 */
export function sortTokens(rows: TokenRow[]): TokenRow[] {
  const rank = (t: TokenRow) => (t.state === 'active' ? 0 : 1)
  return rows.slice().sort((a, b) => rank(a) - rank(b) || (Date.parse(b.created_at ?? '') || 0) - (Date.parse(a.created_at ?? '') || 0))
}

/** 有效的令牌可以撤销；撤销或过期的可以从列表移除。 */
export const canRevoke = (t: TokenRow): boolean => t.state === 'active'
export const canRemove = (t: TokenRow): boolean => t.state !== 'active'

const TOKEN_VAR = '$LMESH_TOKEN'

/**
 * “用令牌调用 API”示例（项目在路径中，设计问题 1 的结论）。令牌用环境变量占位，不写真实令牌。
 * host：服务地址（例如 location.origin）；slug：当前项目标识；deviceId：示例里检查的设备编号（没有时用 1）。
 */
export function apiExample(host: string, slug: string, deviceId: number | null): { comment: string | null; line: string }[] {
  const p = `/api/v1/projects/${slug}`
  return [
    { comment: 'devices', line: `curl -H "Authorization: Bearer ${TOKEN_VAR}" \\\n  ${host}${p}/devices` },
    { comment: 'check', line: `curl -X POST -H "Authorization: Bearer ${TOKEN_VAR}" -H "Content-Type: application/json" \\\n  ${host}${p}/check -d '{"device_id": ${deviceId ?? 1}}'` },
    { comment: 'projects', line: `curl -H "Authorization: Bearer ${TOKEN_VAR}" ${host}/api/v1/projects` },
  ]
}

/** 命令行示例（全局 --project，在服务器上运行）。 */
export function cliExample(slug: string, device: string | null, placeholder = '<device>'): string[] {
  const d = device && /^[\w.-]+$/.test(device) ? device : placeholder
  return [
    `lmesh --project ${slug} --output json config list`,
    `lmesh --project ${slug} check ${d}`,
    'lmesh project list',
    'lmesh token create jenkins --read-only --days 90',
  ]
}
