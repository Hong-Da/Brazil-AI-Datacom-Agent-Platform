/** AI 接口（REQ-040）的纯逻辑：管理员的接口表单与保存内容、“我的 AI”的选择、未配置的原因、调用记录筛选与汇总。 */

import { parseIso } from '../ingest/logic'

export const PROVIDERS = ['anthropic', 'openai', 'local'] as const
export type Provider = (typeof PROVIDERS)[number]
/** 各用途的模型（留空用默认模型）。 */
export const TASKS = ['extract', 'merge', 'ask', 'generate'] as const
export type Task = (typeof TASKS)[number]
export type TaskModelKey = `model_${Task}`

/** 没有可用 AI 的原因（后端 effective.reason）。 */
export const REASONS = ['no_connection', 'no_public', 'public_closed', 'personal_missing', 'disabled_by_user'] as const
export type AiReason = (typeof REASONS)[number]
export type Choice = 'auto' | 'connection' | 'personal' | 'none'

interface ModelFields {
  model: string
  model_extract: string
  model_merge: string
  model_ask: string
  model_generate: string
}

/** GET /ai/connections 的一项。 */
export interface Connection extends ModelFields {
  id: number
  name: string
  provider: Provider
  base_url: string
  api_key_set: boolean
  public: boolean
  enabled: boolean
  is_default: boolean
  chosen_by: number
  usage: { calls: number; errors: number; tokens_in: number; tokens_out: number }
  created_at: string | null
  updated_at: string | null
}
export interface ConnectionList { connections: Connection[]; limits: { timeout: number; max_tokens: number } }

export interface Personal extends ModelFields {
  provider: Provider
  base_url: string
  api_key_set: boolean
  updated_at: string | null
}
export interface ConnOption { id: number; name: string; provider: Provider; model: string; public: boolean }
export interface Effective {
  configured: boolean
  source: 'connection' | 'personal' | null
  choice: Choice
  connection: { id: number; name: string; public: boolean } | null
  provider: string | null
  model: string | null
  reason: AiReason | null
}
/** GET /me/ai */
export interface MyAi {
  choice: Choice
  connection_id: number | null
  /** 所选管理员接口的名称（被关闭后仍有；删除后为空） */
  chosen_name?: string | null
  personal: Personal | null
  options: ConnOption[]
  effective: Effective
  is_admin: boolean
  /** 个人偏好：不提示大请求（M8-2；优先于全局 ai.warn_tokens） */
  no_token_warn?: boolean
}

export interface AiStatus { configured: boolean; provider: string | null; models: Record<string, string | null>; effective?: Effective; reason?: AiReason | null }

export interface AiCall {
  id: number
  task: string
  provider: string
  model: string
  tokens_in: number | null
  tokens_out: number | null
  status: string
  error: string | null
  review_item_id: number | null
  created_at: string | null
  user?: string
  connection?: string
  connection_id?: number | null
  source?: string
}

export interface TestResult { model: string; reply: string; tokens_in: number; tokens_out: number }

// ---------- 表单 ----------

export interface ConnForm extends ModelFields {
  name: string
  provider: Provider
  base_url: string
  public: boolean
  enabled: boolean
}

export function emptyForm(): ConnForm {
  return { name: '', provider: 'openai', base_url: '', model: '', model_extract: '', model_merge: '', model_ask: '', model_generate: '', public: false, enabled: true }
}

export function formFrom(c: Partial<Connection> & Partial<Personal>): ConnForm {
  const f = emptyForm()
  return {
    name: c.name ?? '',
    provider: (PROVIDERS as readonly string[]).includes(c.provider ?? '') ? (c.provider as Provider) : f.provider,
    base_url: c.base_url ?? '',
    model: c.model ?? '',
    model_extract: c.model_extract ?? '',
    model_merge: c.model_merge ?? '',
    model_ask: c.model_ask ?? '',
    model_generate: c.model_generate ?? '',
    public: c.public ?? false,
    enabled: c.enabled ?? true,
  }
}

export function needsBaseUrl(p: Provider): boolean {
  return p === 'openai' || p === 'local'
}

/** 本地模型通常不需要 API Key。 */
export function usesKey(p: Provider): boolean {
  return p === 'anthropic' || p === 'openai'
}

export type Problem = 'errName' | 'errBaseUrl' | 'errUrl' | 'errModel' | 'errKey'

/** 表单问题：{字段: 文案键（相对 ai-settings.）}。withName：管理员接口要填名称（个人接口没有名称）。 */
export function validateConn(f: ConnForm, keySet: boolean, keyInput: string, clearKey: boolean, withName = true): Partial<Record<'name' | 'base_url' | 'model' | 'api_key', Problem>> {
  const out: Partial<Record<'name' | 'base_url' | 'model' | 'api_key', Problem>> = {}
  const name = f.name.trim()
  if (withName && (!name || name.length > 64)) out.name = 'errName'
  const url = f.base_url.trim()
  if (needsBaseUrl(f.provider) && !url) out.base_url = 'errBaseUrl'
  else if (url && !/^https?:\/\/\S+$/i.test(url)) out.base_url = 'errUrl'
  if (!f.model.trim()) out.model = 'errModel'
  if (f.provider === 'anthropic' && !keyInput.trim() && (!keySet || clearKey)) out.api_key = 'errKey'
  return out
}

const TEXT_FIELDS = ['name', 'provider', 'base_url', 'model', 'model_extract', 'model_merge', 'model_ask', 'model_generate'] as const

export type Payload = Partial<Omit<ConnForm, never>> & { api_key?: string; clear_api_key?: boolean }

/** 保存内容：新建时提交全部；修改时只提交改动的项。API Key 只在输入了新值时提交，清除时 clear_api_key。
 *  withName / withFlags：个人接口没有名称与公共、启用开关。 */
export function buildPayload(orig: ConnForm | null, f: ConnForm, keyInput: string, clearKey: boolean, keySet: boolean, withName = true, withFlags = true): Payload {
  const out: Payload = {}
  for (const k of TEXT_FIELDS) {
    if (k === 'name' && !withName) continue
    const v = f[k].trim()
    if (!orig || v !== orig[k]) (out as Record<string, unknown>)[k] = v
  }
  if (withFlags) {
    for (const k of ['public', 'enabled'] as const) if (!orig || f[k] !== orig[k]) out[k] = f[k]
  }
  if (keyInput.trim()) out.api_key = keyInput.trim()
  else if (clearKey && keySet) out.clear_api_key = true
  return out
}

export function payloadIsEmpty(p: Payload): boolean {
  return Object.keys(p).length === 0
}

/** 各用途里填写了专门模型的项（列表里显示）。 */
export function taskModels(c: ModelFields): [Task, string][] {
  return TASKS.filter((t) => c[`model_${t}`]?.trim()).map((t) => [t, c[`model_${t}`].trim()])
}

// ---------- 我的 AI ----------

/** 单选框的值：auto / personal / none / c:<接口编号>。 */
export function choiceValue(choice: Choice, connectionId: number | null): string {
  return choice === 'connection' ? `c:${connectionId ?? ''}` : choice
}

export function parseChoice(v: string): { choice: Choice; connection_id: number | null } {
  if (v.startsWith('c:')) {
    const id = Number(v.slice(2))
    return { choice: 'connection', connection_id: Number.isFinite(id) && id > 0 ? id : null }
  }
  return { choice: (['auto', 'personal', 'none'].includes(v) ? v : 'auto') as Choice, connection_id: null }
}

/** 选了某个接口，但它已不在可选列表里（被关闭、停用或删除）。 */
export function chosenClosed(my: Pick<MyAi, 'choice' | 'connection_id' | 'options'>): boolean {
  return my.choice === 'connection' && !my.options.some((o) => o.id === my.connection_id)
}

/** “自动”现在会落到哪个接口：管理员第一个可选的，普通用户第一个公开的（options 已按后端规则过滤、按编号排序）。 */
export function autoTarget(my: Pick<MyAi, 'options' | 'is_admin'>): ConnOption | null {
  return my.options.find((o) => my.is_admin || o.public) ?? null
}

/** 未配置提示的去处：管理员缺接口时去“AI 接口”，其余去“我的 AI”。 */
export function reasonTarget(reason: AiReason | null | undefined, isAdmin: boolean): 'ai-settings' | 'my-ai' {
  return reason === 'no_connection' && isAdmin ? 'ai-settings' : 'my-ai'
}

/** 需要用户处理的原因用醒目（琥珀色）样式；用户自己选了不用、或系统没有接口时用普通样式。 */
export function reasonTone(reason: AiReason | null | undefined): 'warn' | 'plain' {
  return reason === 'no_public' || reason === 'public_closed' || reason === 'personal_missing' ? 'warn' : 'plain'
}

export function normReason(r: unknown): AiReason | null {
  return typeof r === 'string' && (REASONS as readonly string[]).includes(r) ? (r as AiReason) : null
}

// ---------- 调用记录 ----------

export interface CallFilter { user?: string; connection?: string; task?: string }

export function filterCalls(calls: AiCall[], f: CallFilter): AiCall[] {
  return calls.filter((c) => (!f.user || (c.user ?? '') === f.user) && (!f.connection || (c.connection ?? '') === f.connection) && (!f.task || c.task === f.task))
}

/** 下拉框选项：去重、排序，空值不列。 */
export function distinct(calls: AiCall[], key: 'user' | 'connection' | 'task'): string[] {
  return [...new Set(calls.map((c) => String(c[key] ?? '')).filter(Boolean))].sort()
}

export interface TaskUsage { task: string; calls: number; ok: number; errors: number; tokensIn: number; tokensOut: number }

/** 按任务汇总调用记录（只算 since 之后的记录；since 为空时全部）。 */
export function usageByTask(calls: AiCall[], since?: Date): TaskUsage[] {
  const m = new Map<string, TaskUsage>()
  for (const c of calls) {
    if (since && !(parseIso(c.created_at) >= since.getTime())) continue
    const u = m.get(c.task) ?? { task: c.task, calls: 0, ok: 0, errors: 0, tokensIn: 0, tokensOut: 0 }
    u.calls += 1
    if (c.status === 'ok') u.ok += 1
    else u.errors += 1
    u.tokensIn += c.tokens_in ?? 0
    u.tokensOut += c.tokens_out ?? 0
    m.set(c.task, u)
  }
  return [...m.values()].sort((a, b) => b.tokensIn + b.tokensOut - (a.tokensIn + a.tokensOut))
}

export function monthStart(now = new Date()): Date {
  return new Date(now.getFullYear(), now.getMonth(), 1)
}

export function fmtTokens(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (v >= 10_000) return `${(v / 1000).toFixed(1)}k`
  return v.toLocaleString('en-US')
}
