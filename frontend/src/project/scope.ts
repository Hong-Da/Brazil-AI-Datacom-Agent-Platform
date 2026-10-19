/**
 * M6（REQ-035）：设备相关接口改走项目路径 /api/v1/projects/{项目}/…。
 * 这里是纯逻辑：哪些接口属于项目（与后端 api/access.py 的 PROJECT 一致）、怎样把旧路径改写成项目路径、
 * 哪些页面路由带项目前缀 /p/<项目>/…、旧网址怎样对应到新网址。api.ts 与 router.ts 共用。
 */

/** 后端 access.PROJECT：同时有项目路径与兼容别名的接口（路径模板，{x} 为一段）。 */
export const PROJECT_API: readonly string[] = [
  '/summary',
  '/configs',
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
export function scopedPath(path: string, slug: string | null | undefined): string {
  if (!slug || path.startsWith('/projects/') || !isProjectApi(path)) return path
  return `/projects/${encodeURIComponent(slug)}${path}`
}

/** 带项目前缀 /p/<项目>/… 的页面：旧路径 → 路由名（旧路径用于兼容重定向）。 */
export const PROJECT_PAGES: readonly { name: string; path: string; legacy?: string }[] = [
  { name: 'devices', path: 'devices', legacy: '/devices' },
  { name: 'add-device', path: 'devices/add' },
  { name: 'device-graph', path: 'graph/:id?', legacy: '/graph/:id?' },
  { name: 'device-analysis', path: 'analysis/:id?', legacy: '/analysis/:id?' },
  { name: 'history', path: 'history/:id?', legacy: '/history/:id?' },
  { name: 'unknown-lines', path: 'unknown-lines', legacy: '/unknown-lines' },
  { name: 'compare', path: 'compare', legacy: '/compare' },
  { name: 'check', path: 'check', legacy: '/check' },
  { name: 'cleanup', path: 'cleanup', legacy: '/cleanup' },
  { name: 'translate', path: 'translate', legacy: '/translate' },
  { name: 'change', path: 'change', legacy: '/change' },
  { name: 'scripts', path: 'scripts', legacy: '/check-projects' },
  { name: 'check-project', path: 'scripts/:id', legacy: '/check-projects/:id' },
  { name: 'migration', path: 'migration', legacy: '/migration' },
  { name: 'impact', path: 'impact', legacy: '/impact' },
  { name: 'topology', path: 'topology', legacy: '/topology' },
  { name: 'consistency', path: 'consistency', legacy: '/consistency' },
  { name: 'baseline', path: 'baseline', legacy: '/baseline' },
  { name: 'export', path: 'export', legacy: '/export' },
  { name: 'project-settings', path: 'settings' },
]

export const PROJECT_PAGE_NAMES: ReadonlySet<string> = new Set(PROJECT_PAGES.map((p) => p.name))

/** 旧网址（例如 /graph/12?node=x）对应的新网址：/p/<项目>/graph/12?node=x。 */
export function legacyTarget(fullPath: string, slug: string): string {
  // 配置检查项目并入项目脚本（D-0199）
  const path = fullPath.replace(/^\/check-projects(?=$|[/?#])/, '/scripts')
  return `/p/${encodeURIComponent(slug)}${path}`
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
export function withProject<T>(to: T, slug: string | null): T {
  if (!to || typeof to !== 'object') return to
  const loc = to as unknown as { name?: unknown; params?: Record<string, unknown>; query?: unknown; hash?: unknown }
  if (typeof loc.name !== 'string' || !PROJECT_PAGE_NAMES.has(loc.name) || loc.params?.project) return to
  if (slug) return { ...(to as object), params: { ...(loc.params ?? {}), project: slug } } as T
  // 还不知道当前项目（刚打开网页、路由守卫还没确定项目时外壳已经渲染）：用旧网址，守卫会跳到当前项目的对应页
  return { path: legacyPath(loc.name, loc.params ?? {}), query: loc.query, hash: loc.hash } as T
}

/** 项目页面的旧网址（没有旧网址的页面去“我的项目”）。 */
export function legacyPath(name: string, params: Record<string, unknown> = {}): string {
  const page = PROJECT_PAGES.find((p) => p.name === name)
  if (!page?.legacy) return '/projects'
  return page.legacy.replace(/\/:(\w+)\??/g, (_m, k: string) => (params[k] !== undefined && params[k] !== '' ? `/${encodeURIComponent(String(params[k]))}` : ''))
}
