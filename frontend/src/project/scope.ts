/**
 * M6（REQ-035）：设备相关接口改走项目路径 /api/v1/projects/{项目}/…。
 * 这里是纯逻辑：哪些接口属于项目（与后端 api/access.py 的 PROJECT 一致）、怎样把旧路径改写成项目路径、
 * 哪些页面路由带项目前缀 /p/<项目>/…、旧网址怎样对应到新网址。api.ts 与 router.ts 共用。
 */

/** 后端 access.PROJECT：同时有项目路径与兼容别名的接口（路径模板，{x} 为一段）。 */
export const PROJECT_API: readonly string[] = [
  '/summary',
  '/configs',
  '/configs/inspect',
  '/devices',
  '/devices/rebuild',
  '/devices/{id}/rebuild',
  '/devices/{id}/delete-preview',
  '/devices/{id}',
  '/devices/{id}/versions/{vid}',
  '/devices/{id}/analysis',
  '/devices/{id}/check',
  '/devices/{id}/graph',
  '/devices/{id}/versions',
  '/devices/{id}/versions/{vid}/text',
  '/devices/{id}/history',
  '/devices/{id}/history/diff',
  '/devices/{id}/history/object',
  '/devices/{id}/history/{vid}/tag',
  '/devices/{id}/history/restore',
  '/devices/{id}/history/report',
  '/devices/{id}/profile-candidates',
  '/devices/{id}/profile',
  '/devices/{id}/support-request',
  '/model-rules',
  '/model-rules/test',
  '/model-rules/{id}',
  '/unknown-lines',
  '/unknown-lines/states',
  '/unknown-lines/review',
  '/check',
  '/cleanup',
  '/check/ignores',
  '/check/ignores/{id}',
  '/compare',
  '/topology',
  '/consistency',
  '/migrate',
  '/migrate/suggest-map',
  '/baseline',
  '/baseline/report',
  '/change',
  '/change/report',
  '/impact',
  '/export/table',
  '/reports',
  '/translate',
  '/translate-rules/test',
  '/templates/check',
  '/templates/extract',
  '/query',
  '/ask',
  '/guard',
  '/generate',
  '/check-projects',
  '/check-projects/ai-rules',
  '/check-projects/{id}',
  '/check-projects/{id}/scripts',
  '/check-projects/{id}/scripts/{sid}',
  '/check-projects/{id}/scripts/{sid}/check',
  '/check-projects/{id}/scripts/{sid}/reorder',
  '/check-projects/{id}/scripts/{sid}/revisions',
  '/check-projects/{id}/scripts/{sid}/revisions/{rid}',
  '/check-projects/{id}/scripts/{sid}/revisions/{rid}/restore',
  '/check-projects/diff',
  '/check-projects/diff/report',
  '/scripts',
]

const PATTERNS: RegExp[] = PROJECT_API.map((p) => new RegExp('^' + p.replace(/\{[a-z]+\}/g, '[^/]+') + '$'))

/** 接口路径（不含 /api/v1，可带查询参数）是否属于项目。 */
export function isProjectApi(path: string): boolean {
  const bare = path.split('?')[0].split('#')[0]
  return PATTERNS.some((r) => r.test(bare))
}

/**
 * 把旧的无项目路径改写为当前项目的路径；已经是 /projects/… 的、不属于项目的、没有当前项目的原样返回。
 * 例：scopedPath('/devices?x=1', 'oam') → '/projects/oam/devices?x=1'。
 */
export function scopedPath(path: string, ref: string | null | undefined): string {
  if (!ref || path.startsWith('/projects/') || !isProjectApi(path)) return path
  // “属主/标识”编码成 属主%2F标识，后端在路由前把这一段还原（api/scoping.py）
  return `/projects/${encodeURIComponent(ref)}${path}`
}

/**
 * 带项目前缀的页面：/p/<标识>/…（自己的项目）或 /p/<属主>/<标识>/…（别人的项目），路由里是可重复参数 :project+。
 * 页面路径的第二段只有数字编号（:id(\d+)），所以“标识/页面”与“属主/标识/页面”不会混淆。旧路径用于兼容重定向。
 */
/** 页面在网络维度上的位置（M9，REQ-045）：
 *  - net：按网络的页面；网址 /p/<项目>/n/<网络>/…，项目层网址（“全部设备”）显示各网络汇总；
 *  - both：项目层与网络里都能用（项目层为项目全部设备，网络里只有本网络的设备与本网络用的版本）；
 *  - only：只有网络层（网络概览）；
 *  - 不写：只在项目层（设备池管理、项目设置、网络管理）。 */
export type NetLevel = 'net' | 'both' | 'only'

export const PROJECT_PAGES: readonly { name: string; path: string; legacy?: string; net?: NetLevel }[] = [
  { name: 'devices', path: 'devices', legacy: '/devices', net: 'both' },
  { name: 'add-device', path: 'devices/add', net: 'both' },
  { name: 'device-graph', path: 'graph/:id(\\d+)?', legacy: '/graph/:id?', net: 'both' },
  { name: 'device-analysis', path: 'analysis/:id(\\d+)?', legacy: '/analysis/:id?', net: 'net' },
  { name: 'history', path: 'history/:id(\\d+)?', legacy: '/history/:id?', net: 'both' },
  { name: 'unknown-lines', path: 'unknown-lines', legacy: '/unknown-lines' },
  { name: 'model-rules', path: 'model-rules', legacy: '/model-rules' },
  { name: 'compare', path: 'compare', legacy: '/compare', net: 'both' },
  { name: 'check', path: 'check', legacy: '/check', net: 'net' },
  { name: 'cleanup', path: 'cleanup', legacy: '/cleanup', net: 'net' },
  { name: 'translate', path: 'translate', legacy: '/translate', net: 'both' },
  { name: 'change', path: 'change', legacy: '/change', net: 'net' },
  { name: 'scripts', path: 'scripts', legacy: '/check-projects', net: 'net' },
  { name: 'check-project', path: 'scripts/:id(\\d+)', legacy: '/check-projects/:id', net: 'net' },
  { name: 'migration', path: 'migration', legacy: '/migration', net: 'net' },
  { name: 'impact', path: 'impact', legacy: '/impact', net: 'net' },
  { name: 'topology', path: 'topology', legacy: '/topology', net: 'net' },
  { name: 'consistency', path: 'consistency', legacy: '/consistency', net: 'net' },
  { name: 'baseline', path: 'baseline', legacy: '/baseline', net: 'net' },
  { name: 'export', path: 'export', legacy: '/export', net: 'net' },
  { name: 'project-settings', path: 'settings' },
  // M9：网络管理（项目层）、成员（按网络）、网络概览（只有网络层）
  { name: 'networks', path: 'networks' },
  { name: 'network-suggest', path: 'networks/suggest' },
  { name: 'members', path: 'members', net: 'net' },
  { name: 'network-home', path: '', net: 'only' },
]

/** 网络层路由的名称：n-<页面>。 */
export const NET_PREFIX = 'n-'
export const netName = (name: string): string => `${NET_PREFIX}${name}`
/** 路由名称 → 页面名称（去掉 n-）。 */
export function basePage(name: unknown): string {
  const s = String(name ?? '')
  return s.startsWith(NET_PREFIX) && PROJECT_PAGES.some((p) => p.name === s.slice(NET_PREFIX.length)) ? s.slice(NET_PREFIX.length) : s
}
/** 页面在网络维度上的位置（见 NetLevel）。 */
export function pageNet(name: unknown): NetLevel | undefined {
  const b = basePage(name)
  return PROJECT_PAGES.find((p) => p.name === b)?.net
}

export const PROJECT_PAGE_NAMES: ReadonlySet<string> = new Set([...PROJECT_PAGES.map((p) => p.name), ...PROJECT_PAGES.filter((p) => p.net).map((p) => netName(p.name))])

/** 项目引用 → 网址里的项目段：oam → oam，liwei/oam → liwei/oam（各段分别编码）。 */
export function refPath(ref: string): string {
  return ref.split('/').map(encodeURIComponent).join('/')
}

/** 项目引用 → 路由参数 :project+（数组）。 */
export function refParam(ref: string): string[] {
  return ref.split('/').filter(Boolean)
}

/** 路由参数 :project+ → 项目引用；不是一段（标识）或两段（属主/标识）时返回 null。 */
export function refFromParam(p: unknown): string | null {
  const parts = (Array.isArray(p) ? p : [p]).map((x) => String(x ?? '')).filter(Boolean)
  return parts.length >= 1 && parts.length <= 2 ? parts.join('/') : null
}

/** 旧网址（例如 /graph/12?node=x）对应的新网址：/p/<项目>/graph/12?node=x。 */
export function legacyTarget(fullPath: string, ref: string): string {
  // 配置检查项目并入项目脚本（D-0199）
  const path = fullPath.replace(/^\/check-projects(?=$|[/?#])/, '/scripts')
  return `/p/${refPath(ref)}${path}`
}

/** 最近用过的项目：放在浏览器本地（只是方便，取不到时用默认项目）。 */
export const RECENT_KEY = 'lmesh-project'

/** 后端“最近活动”的 action 是“方法 路由”，例如 "POST /configs"；映射为页面文案键，映射不到返回 null（显示原文）。 */
const ACTIVITY: [RegExp, string][] = [
  [/^create$/, 'create'],
  [/^POST \/configs$/, 'import'],
  [/^DELETE \/devices\/\{device_id\}$/, 'deleteDevice'],
  [/^DELETE \/devices\/\{device_id\}\/versions\/\{version_id\}$/, 'deleteVersion'],
  [/^POST \/(devices\/rebuild|devices\/\{device_id\}\/rebuild)$/, 'rebuild'],
  [/^(POST|PUT|DELETE) \/refs(\/\{device_id\})?$/, 'refs'],
  [/^POST \/devices\/copy-in$/, 'copyIn'],
  [/^(PUT|DELETE) \/rules\/\{rule_id\}$/, 'rules'],
  [/^PUT $/, 'settings'],
  [/^(PUT|DELETE) \/members\/\{username\}$/, 'members'],
  [/^POST \/(scripts|check-projects)$/, 'newScript'],
  [/^(PUT|POST|DELETE) \/check-projects\/\{pid\}\/scripts(\/.*)?$/, 'editScript'],
  [/^(PUT|DELETE) \/check-projects\/\{pid\}$/, 'editScript'],
  [/^(POST|DELETE) \/check\/ignores(\/\{ignore_id\})?$/, 'ignores'],
  [/^POST \/devices\/\{device_id\}\/history\/\{version_id\}\/tag$/, 'tag'],
  [/^POST \/unknown-lines\/review$/, 'review'],
]

export function activityKey(action: string | null | undefined): string | null {
  if (!action) return null
  for (const [re, key] of ACTIVITY) if (re.test(action)) return key
  return null
}

/** 路由跳转目标：去带项目前缀的页面却没给项目时补上当前项目（从非项目页面跳过去，例如首页 → 设备）。 */
export function withProject<T>(to: T, ref: string | null): T {
  if (!to || typeof to !== 'object') return to
  const loc = to as unknown as { name?: unknown; params?: Record<string, unknown>; query?: unknown; hash?: unknown }
  if (typeof loc.name !== 'string' || !PROJECT_PAGE_NAMES.has(loc.name)) return to
  const given = loc.params?.project
  // 给了项目引用（字符串，可能是“属主/标识”）：换成路由参数数组，网址才是 /p/属主/标识/…（而不是 %2F）
  if (typeof given === 'string' && given) return { ...(to as object), params: { ...loc.params, project: refParam(given) } } as T
  if (given) return to
  if (ref) return { ...(to as object), params: { ...(loc.params ?? {}), project: refParam(ref) } } as T
  // 还不知道当前项目（刚打开网页、路由守卫还没确定项目时外壳已经渲染）：用旧网址，守卫会跳到当前项目的对应页
  return { path: legacyPath(loc.name, loc.params ?? {}), query: loc.query, hash: loc.hash } as T
}

/** 项目页面的旧网址（没有旧网址的页面去“我的项目”）。 */
export function legacyPath(name: string, params: Record<string, unknown> = {}): string {
  const page = PROJECT_PAGES.find((p) => p.name === basePage(name))
  if (!page?.legacy) return '/projects'
  return page.legacy.replace(/\/:(\w+)\??/g, (_m, k: string) => (params[k] !== undefined && params[k] !== '' ? `/${encodeURIComponent(String(params[k]))}` : ''))
}

/**
 * 跳到页面时带上当前网络（M9）：按网络的页面（net / both / only）在有当前网络时用网络层路由 n-<页面>，没有时用项目层。
 * params.network 明确给出时按它（null / '' = 项目层“全部设备”）；已经是 n-<页面> 且没给 network 时交给 vue-router 沿用当前参数。
 * 只有网络层的页面（网络概览）没有网络时去网络列表。
 */
export function withNetwork<T>(to: T, net: string | null): T {
  if (!to || typeof to !== 'object') return to
  const loc = to as unknown as { name?: unknown; params?: Record<string, unknown> }
  if (typeof loc.name !== 'string') return to
  const base = basePage(loc.name)
  const level = pageNet(base)
  const params = { ...(loc.params ?? {}) }
  if (!level) {
    if (!('network' in params)) return to
    delete params.network
    return { ...(to as object), params } as T
  }
  const given = 'network' in params
  const want = given ? params.network : loc.name.startsWith(NET_PREFIX) ? undefined : net
  delete params.network
  if (given || !loc.name.startsWith(NET_PREFIX)) {
    if (typeof want === 'string' && want) return { ...(to as object), name: netName(base), params: { ...params, network: want } } as T
    if (level === 'only') return { ...(to as object), name: 'networks', params } as T
    return { ...(to as object), name: base, params } as T
  }
  return to
}

// ---------------------------------------------------------------- 接口路径：按网络（M9，与后端 api/access.network_ok 一致）

/** 只在项目层、不挂网络路径的接口（后端 NETWORK_EXCLUDE）：[方法, 路径模板]。 */
const NETWORK_EXCLUDE: readonly [string, string][] = [
  ['DELETE', '/devices/{id}'],
  ['DELETE', '/devices/{id}/versions/{vid}'],
  ['GET', '/devices/{id}/delete-preview'],
  ['*', '/model-rules'],
  ['*', '/model-rules/test'],
  ['*', '/model-rules/{id}'],
  ['PUT', '/devices/{id}/history/{vid}/tag'],
  ['DELETE', '/devices/{id}/history/{vid}/tag'],
]
const EXCLUDE_RE = NETWORK_EXCLUDE.map(([m, p]) => [m, new RegExp('^' + p.replace(/\{[a-z]+\}/g, '[^/]+') + '$')] as const)
/** 只在项目路径下、按网络的接口（后端 NETWORK_PROJECT_ONLY）。 */
const NETWORK_PROJECT_ONLY = ['/rules', '/scripts', '/ai/', '/view-annotations']

/** 项目路径后面的部分（例如 /topology、/view-annotations?x=1）是否也挂在网络路径下。 */
export function networkable(method: string, rest: string): boolean {
  const bare = rest.split('?')[0].split('#')[0]
  const m = method.toUpperCase()
  if (EXCLUDE_RE.some(([em, re]) => (em === '*' || em === m) && re.test(bare))) return false
  if (bare === '/ai/kb/sanitize-redact') return false
  if (isProjectApi(bare)) return true
  return NETWORK_PROJECT_ONLY.some((x) => bare === x || bare.startsWith(x.endsWith('/') ? x : `${x}/`))
}

/**
 * 当前项目的接口路径改走当前网络：/projects/<项目>/topology → /projects/<项目>/n/<网络>/topology。
 * 没有当前网络（项目层）、不是当前项目、已经带网络、项目层的接口原样返回。
 */
export function networkPath(path: string, ref: string | null | undefined, net: string | null | undefined, method = 'GET'): string {
  if (!ref || !net) return path
  const pre = `/projects/${encodeURIComponent(ref)}`
  if (!path.startsWith(`${pre}/`)) return path
  const rest = path.slice(pre.length)
  if (rest.startsWith('/n/') || !networkable(method, rest)) return path
  return `${pre}/n/${encodeURIComponent(net)}${rest}`
}
